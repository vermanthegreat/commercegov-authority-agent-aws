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

from authority_agent.dynamodb_ledger import DynamoDbIdempotencyLedger
from authority_agent.handler import handle_payload
from authority_agent.inbound_auth import BearerAuthError, BearerAuthenticator, SecretsManagerBearerAuthenticator
from authority_agent.orchestration import AuthorityProcessor, TenantBindingRegistry
from authority_agent.runtime_context import SyntheticProofContextBuilder
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
        )


class ObservedSemanticProvider:
    provider_name = "StrandsSemanticProvider"

    def __init__(self, provider: StrandsSemanticProvider) -> None:
        self._provider = provider
        self.model_id = provider.model_id

    def assess(self, event):
        _safe_log(
            "semantic_assessment_started",
            event_id=event.event_id,
            agency_id=event.agency_id,
            shop_id=event.shop_id,
            model_id=self.model_id,
        )
        try:
            result = self._provider.assess(event)
        except Exception as exc:
            _safe_log(
                "semantic_assessment_failed",
                event_id=event.event_id,
                error_category=type(exc).__name__,
                model_id=self.model_id,
            )
            raise
        _safe_log(
            "semantic_assessment_completed",
            event_id=event.event_id,
            semantic_classification=result.classification,
            model_id=self.model_id,
        )
        return result


def build_processor(config: RuntimeConfig) -> AuthorityProcessor:
    table = boto3.resource("dynamodb", region_name=config.region_name).Table(config.table_name)
    ledger = DynamoDbIdempotencyLedger(table, build_id=config.build_id, logger=LOGGER)
    provider = ObservedSemanticProvider(
        StrandsSemanticProvider(
            context_builder=SyntheticProofContextBuilder(),
            model_id=config.model_id,
            region_name=config.region_name,
            timeout_seconds=config.semantic_timeout_seconds,
        )
    )
    return AuthorityProcessor(
        bindings=TenantBindingRegistry([(config.allowed_agency_id, config.allowed_shop_id)]),
        ledger=ledger,
        semantic_provider=provider,
    )


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
    try:
        result = handle_payload(processor, payload)
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
_BEARER_AUTHENTICATOR: SecretsManagerBearerAuthenticator | None = None


def lambda_handler(event: Mapping[str, Any], context: Any) -> dict[str, Any]:
    global _PROCESSOR, _BEARER_AUTHENTICATOR
    if _PROCESSOR is None or _BEARER_AUTHENTICATOR is None:
        config = RuntimeConfig.from_env()
        _PROCESSOR = build_processor(config)
        _BEARER_AUTHENTICATOR = SecretsManagerBearerAuthenticator(
            boto3.client("secretsmanager", region_name=config.region_name),
            config.inbound_bearer_secret_arn,
        )
    return handle_api_event(event, context, _PROCESSOR, bearer_authenticator=_BEARER_AUTHENTICATOR)
