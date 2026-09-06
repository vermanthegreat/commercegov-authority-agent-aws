"""Thin API Gateway/Lambda adapter for the durable P2 AWS runtime."""

from __future__ import annotations

import base64
from dataclasses import dataclass
import json
import logging
import os
from time import monotonic
from typing import Any, Mapping

import boto3

from authority_agent.commercegov_read import CommerceGovReadClient
from authority_agent.context_source import (
    CONTEXT_SOURCE_LIVE,
    CONTEXT_SOURCE_SYNTHETIC,
    RecordingContextBuilder,
)
from authority_agent.dynamodb_ledger import DynamoDbIdempotencyLedger
from authority_agent.handler import handle_payload
from authority_agent.inbound_auth import (
    BearerAuthError,
    BearerAuthenticator,
    SecretsManagerBearerAuthenticator,
)
from authority_agent.live_read_transport import LazyHttpsCommerceGovReadTransport
from authority_agent.oauth_credentials import CommerceGovOAuthCredentialManager
from authority_agent.orchestration import AuthorityProcessor, TenantBindingRegistry
from authority_agent.runtime_context import SyntheticProofContextBuilder
from authority_agent.semantic_context import SemanticContextBuilder
from authority_agent.strands_provider import DEFAULT_BEDROCK_MODEL_ID, StrandsSemanticProvider

LOGGER = logging.getLogger("authority_agent.runtime")
LOGGER.setLevel(logging.INFO)
MAX_BODY_BYTES = 131_072


def _safe_log(message: str, **fields: Any) -> None:
    LOGGER.info(json.dumps({"message": message, **fields}, sort_keys=True, default=str))


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    table_name: str
    allowed_agency_id: str
    allowed_shop_id: str
    region_name: str
    model_id: str
    semantic_timeout_seconds: float
    build_id: str
    inbound_bearer_secret_arn: str
    commercegov_base_url: str = ""
    commercegov_read_secret_arn: str = ""

    @property
    def live_context_enabled(self) -> bool:
        url = self.commercegov_base_url.strip()
        arn = self.commercegov_read_secret_arn.strip()
        return bool(url) and bool(arn) and url.startswith("https://")

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "RuntimeConfig":
        values = os.environ if environ is None else environ
        required = {
            "AUTHORITY_TABLE_NAME": values.get("AUTHORITY_TABLE_NAME", "").strip(),
            "ALLOWED_AGENCY_ID": values.get("ALLOWED_AGENCY_ID", "").strip(),
            "ALLOWED_SHOP_ID": values.get("ALLOWED_SHOP_ID", "").strip(),
            "AWS_REGION": values.get("AWS_REGION", "").strip(),
            "INBOUND_BEARER_SECRET_ARN": values.get("INBOUND_BEARER_SECRET_ARN", "").strip(),
        }
        if any(not value for value in required.values()):
            raise ValueError("missing_runtime_configuration")
        timeout = float(values.get("SEMANTIC_TIMEOUT_SECONDS", "24"))
        if not 0 < timeout <= 24:
            raise ValueError("invalid_semantic_timeout")
        model_id = values.get("BEDROCK_MODEL_ID", DEFAULT_BEDROCK_MODEL_ID).strip()
        if model_id != DEFAULT_BEDROCK_MODEL_ID:
            raise ValueError("unapproved_bedrock_model")
        return cls(
            table_name=required["AUTHORITY_TABLE_NAME"],
            allowed_agency_id=required["ALLOWED_AGENCY_ID"],
            allowed_shop_id=required["ALLOWED_SHOP_ID"],
            region_name=required["AWS_REGION"],
            model_id=model_id,
            semantic_timeout_seconds=timeout,
            build_id=values.get("RUNTIME_BUILD_ID", "unknown").strip() or "unknown",
            inbound_bearer_secret_arn=required["INBOUND_BEARER_SECRET_ARN"],
            commercegov_base_url=values.get("COMMERCEGOV_BASE_URL", "").strip(),
            commercegov_read_secret_arn=values.get("COMMERCEGOV_READ_SECRET_ARN", "").strip(),
        )


class ObservedSemanticProvider:
    provider_name = "StrandsSemanticProvider"

    def __init__(self, provider: StrandsSemanticProvider, context_builder: Any) -> None:
        self._provider = provider
        self._context_builder = context_builder
        self.model_id = provider.model_id
        self.context_evidence: dict[str, Any] = dict(getattr(context_builder, "last_evidence", {}) or {})

    def assess(self, event):
        _safe_log(
            "semantic_assessment_started",
            event_id=event.event_id,
            agency_id=event.agency_id,
            shop_id=event.shop_id,
            model_id=self.model_id,
            context_source=self.context_evidence.get("context_source"),
        )
        try:
            result = self._provider.assess(event)
        except Exception as exc:
            self.context_evidence = dict(getattr(self._context_builder, "last_evidence", {}) or {})
            _safe_log(
                "semantic_assessment_failed",
                event_id=event.event_id,
                error_category=type(exc).__name__,
                model_id=self.model_id,
                context_source=self.context_evidence.get("context_source"),
                read_status=self.context_evidence.get("read_status"),
            )
            raise
        self.context_evidence = dict(getattr(self._context_builder, "last_evidence", {}) or {})
        _safe_log(
            "semantic_assessment_completed",
            event_id=event.event_id,
            semantic_classification=result.classification,
            model_id=self.model_id,
            context_source=self.context_evidence.get("context_source"),
            read_status=self.context_evidence.get("read_status"),
        )
        return result


def _synthetic_builder() -> RecordingContextBuilder:
    return RecordingContextBuilder(SyntheticProofContextBuilder(), CONTEXT_SOURCE_SYNTHETIC)


def _live_builder(
    config: RuntimeConfig,
    secrets_client: Any,
    lease_table: Any,
) -> RecordingContextBuilder:
    credential_manager = CommerceGovOAuthCredentialManager(
        base_url=config.commercegov_base_url,
        secret_arn=config.commercegov_read_secret_arn,
        secrets_client=secrets_client,
        lease_table=lease_table,
        logger=LOGGER,
    )
    transport = LazyHttpsCommerceGovReadTransport(
        base_url=config.commercegov_base_url,
        credential_manager=credential_manager,
        timeout_seconds=5.0,
    )
    return RecordingContextBuilder(
        SemanticContextBuilder(CommerceGovReadClient(transport)),
        CONTEXT_SOURCE_LIVE,
    )


def _semantic_provider(config: RuntimeConfig, context_builder: RecordingContextBuilder) -> ObservedSemanticProvider:
    return ObservedSemanticProvider(
        StrandsSemanticProvider(
            context_builder=context_builder,
            model_id=config.model_id,
            region_name=config.region_name,
            timeout_seconds=config.semantic_timeout_seconds,
        ),
        context_builder,
    )


def build_processor(config: RuntimeConfig) -> AuthorityProcessor:
    return build_processors(config)[0]


def build_processors(
    config: RuntimeConfig, *, secrets_client: Any | None = None
) -> tuple[AuthorityProcessor, AuthorityProcessor]:
    table = boto3.resource("dynamodb", region_name=config.region_name).Table(config.table_name)
    ledger = DynamoDbIdempotencyLedger(table, build_id=config.build_id, logger=LOGGER)
    bindings = TenantBindingRegistry([(config.allowed_agency_id, config.allowed_shop_id)])
    synthetic_builder = _synthetic_builder()
    assess_processor = AuthorityProcessor(
        bindings=bindings,
        ledger=ledger,
        semantic_provider=_semantic_provider(config, synthetic_builder),
    )
    if not config.live_context_enabled:
        _safe_log("live_context_disabled", reason="incomplete_or_absent_live_config")
        return assess_processor, assess_processor
    client = secrets_client or boto3.client("secretsmanager", region_name=config.region_name)
    live_builder = _live_builder(config, client, table)
    operational_processor = AuthorityProcessor(
        bindings=bindings,
        ledger=ledger,
        semantic_provider=_semantic_provider(config, live_builder),
    )
    _safe_log("live_context_enabled", context_source=CONTEXT_SOURCE_LIVE)
    return assess_processor, operational_processor


def _response(status_code: int, body: Mapping[str, Any], *, cached: bool = False) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {
            "content-type": "application/json",
            "cache-control": "no-store",
            "x-commercegov-cache": "HIT" if cached else "MISS",
        },
        "body": json.dumps(dict(body), sort_keys=True, separators=(",", ":")),
        "isBase64Encoded": False,
    }


def _assess_iam_denied(request_context: Mapping[str, Any]) -> bool:
    authorizer = request_context.get("authorizer")
    iam = authorizer.get("iam") if isinstance(authorizer, Mapping) else None
    return not isinstance(iam, Mapping) or not iam.get("userArn")


def handle_api_event(
    event: Mapping[str, Any],
    context: Any,
    processor: AuthorityProcessor,
    bearer_authenticator: BearerAuthenticator | None = None,
    operational_processor: AuthorityProcessor | None = None,
) -> dict[str, Any]:
    started = monotonic()
    request_context = event.get("requestContext")
    if not isinstance(request_context, Mapping):
        return _response(400, {"error": "invalid_api_gateway_request", "terminal_status": "FAIL_CLOSED"})
    http = request_context.get("http")
    method = http.get("method") if isinstance(http, Mapping) else None
    route_key = event.get("routeKey") or request_context.get("routeKey")
    if method != "POST":
        return _response(405, {"error": "unsupported_route", "terminal_status": "FAIL_CLOSED"})
    if route_key == "POST /assess":
        if _assess_iam_denied(request_context):
            return _response(403, {"error": "iam_authorization_required", "terminal_status": "FAIL_CLOSED"})
    elif route_key == "POST /events/operational":
        if bearer_authenticator is None:
            return _response(503, {"error": "inbound_bearer_unavailable", "terminal_status": "FAIL_CLOSED"})
        try:
            bearer_authenticator.authenticate(event.get("headers") if isinstance(event.get("headers"), Mapping) else None)
        except BearerAuthError as exc:
            return _response(exc.status_code, {"error": exc.code, "terminal_status": "FAIL_CLOSED"})
    else:
        return _response(405, {"error": "unsupported_route", "terminal_status": "FAIL_CLOSED"})
    headers = event.get("headers")
    content_type = ""
    if isinstance(headers, Mapping):
        content_type = str(headers.get("content-type") or headers.get("Content-Type") or "")
    if content_type.split(";", 1)[0].strip().lower() != "application/json":
        return _response(415, {"error": "application_json_required", "terminal_status": "FAIL_CLOSED"})
    raw_body = event.get("body")
    if not isinstance(raw_body, str):
        return _response(400, {"error": "invalid_json_body", "terminal_status": "FAIL_CLOSED"})
    try:
        body_bytes = base64.b64decode(raw_body, validate=True) if event.get("isBase64Encoded") else raw_body.encode("utf-8")
        if len(body_bytes) > MAX_BODY_BYTES:
            return _response(413, {"error": "request_too_large", "terminal_status": "FAIL_CLOSED"})
        payload = json.loads(body_bytes)
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return _response(400, {"error": "invalid_json_body", "terminal_status": "FAIL_CLOSED"})
    if not isinstance(payload, Mapping):
        return _response(400, {"error": "json_object_required", "terminal_status": "FAIL_CLOSED"})

    request_id = request_context.get("requestId") or getattr(context, "aws_request_id", "unknown")
    safe_identity = {
        key: payload.get(key)
        for key in ("event_id", "agency_id", "shop_id", "target_type", "target_id", "mutation_class")
    }
    _safe_log("request_received", request_id=request_id, **safe_identity)
    selected = processor
    if route_key == "POST /events/operational" and operational_processor is not None:
        selected = operational_processor
    try:
        result = handle_payload(selected, payload)
    except Exception as exc:
        _safe_log(
            "request_failed",
            request_id=request_id,
            error_category=type(exc).__name__,
            latency_ms=round((monotonic() - started) * 1000),
            **safe_identity,
        )
        return _response(500, {"error": "runtime_failure", "terminal_status": "FAIL_CLOSED"})
    terminal_status = result["body"].get("status") or result["body"].get("terminal_status")
    _safe_log(
        "request_completed",
        request_id=request_id,
        status_code=result["status_code"],
        terminal_status=terminal_status,
        cached=result["cached"],
        latency_ms=round((monotonic() - started) * 1000),
        **safe_identity,
    )
    return _response(result["status_code"], result["body"], cached=result["cached"])


_PROCESSOR: AuthorityProcessor | None = None
_OPERATIONAL_PROCESSOR: AuthorityProcessor | None = None
_BEARER_AUTHENTICATOR: SecretsManagerBearerAuthenticator | None = None


def lambda_handler(event: Mapping[str, Any], context: Any) -> dict[str, Any]:
    global _PROCESSOR, _OPERATIONAL_PROCESSOR, _BEARER_AUTHENTICATOR
    if _PROCESSOR is None or _OPERATIONAL_PROCESSOR is None or _BEARER_AUTHENTICATOR is None:
        config = RuntimeConfig.from_env()
        _PROCESSOR, _OPERATIONAL_PROCESSOR = build_processors(config)
        _BEARER_AUTHENTICATOR = SecretsManagerBearerAuthenticator(
            boto3.client("secretsmanager", region_name=config.region_name),
            config.inbound_bearer_secret_arn,
        )
    return handle_api_event(
        event,
        context,
        _PROCESSOR,
        bearer_authenticator=_BEARER_AUTHENTICATOR,
        operational_processor=_OPERATIONAL_PROCESSOR,
    )
