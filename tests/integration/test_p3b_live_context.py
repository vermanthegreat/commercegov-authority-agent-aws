from __future__ import annotations

import copy
import json
import logging
from types import SimpleNamespace

from authority_agent.commercegov_read import CommerceGovReadClient, CommerceGovReadError
from authority_agent.context_source import CONTEXT_SOURCE_LIVE, CONTEXT_SOURCE_SYNTHETIC, RecordingContextBuilder
from authority_agent.handler import handle_payload
from authority_agent.inbound_auth import StaticBearerAuthenticator
from authority_agent.lambda_runtime import ObservedSemanticProvider, RuntimeConfig, handle_api_event
from authority_agent.orchestration import (
    AuthorityProcessor,
    InMemoryIdempotencyLedger,
    TenantBindingRegistry,
)
from authority_agent.runtime_context import SyntheticProofContextBuilder
from authority_agent.semantic_context import SemanticContextBuilder
from authority_agent.strands_provider import StrandsSemanticProvider
from tests.integration.test_p1_strands_provider import FakeAgent, output
from tests.p1_helpers import POLICY_RESPONSE, PRODUCT_RESPONSE, FakeReadTransport

from conftest import make_processor

OPERATIONAL_TOKEN = "p3b-test-bearer"
READ_TOKEN = "p3b-read-token-should-never-appear"


class CapturingLedger(InMemoryIdempotencyLedger):
    def __init__(self) -> None:
        super().__init__()
        self.evidence: dict | None = None

    def complete(self, event, request_hash, response, evidence=None):
        self.evidence = dict(evidence or {})
        super().complete(event, request_hash, response, evidence)


def live_processor(canonical_payload, transport, agent):
    builder = RecordingContextBuilder(
        SemanticContextBuilder(CommerceGovReadClient(transport)),
        CONTEXT_SOURCE_LIVE,
    )

    def factory(tools):
        return agent

    inner = StrandsSemanticProvider(context_builder=builder, agent_factory=factory)
    provider = ObservedSemanticProvider(inner, builder)
    ledger = CapturingLedger()
    processor = AuthorityProcessor(
        bindings=TenantBindingRegistry([("demo-agency", "demo-shop.myshopify.com")]),
        ledger=ledger,
        semantic_provider=provider,
    )
    return processor, provider, ledger, builder


def operational_event(payload, **changes):
    event = {
        "version": "2.0",
        "routeKey": "POST /events/operational",
        "rawPath": "/events/operational",
        "headers": {
            "content-type": "application/json",
            "authorization": f"Bearer {OPERATIONAL_TOKEN}",
        },
        "requestContext": {"requestId": "p3b-1", "http": {"method": "POST"}},
        "body": json.dumps(payload),
        "isBase64Encoded": False,
    }
    event.update(changes)
    return event


def test_live_config_absent_keeps_synthetic_behavior(canonical_payload) -> None:
    base = {
        "AUTHORITY_TABLE_NAME": "table",
        "ALLOWED_AGENCY_ID": "demo-agency",
        "ALLOWED_SHOP_ID": "demo-shop.myshopify.com",
        "AWS_REGION": "us-east-1",
        "INBOUND_BEARER_SECRET_ARN": "arn:aws:secretsmanager:us-east-1:1:secret:inbound",
    }
    assert RuntimeConfig.from_env(base).live_context_enabled is False
    assert RuntimeConfig.from_env(base | {"COMMERCEGOV_BASE_URL": "https://commercegov.example"}).live_context_enabled is False
    assert RuntimeConfig.from_env(
        base | {"COMMERCEGOV_READ_SECRET_ARN": "arn:aws:secretsmanager:us-east-1:1:secret:read"}
    ).live_context_enabled is False
    assert RuntimeConfig.from_env(
        base
        | {
            "COMMERCEGOV_BASE_URL": "http://commercegov.example",
            "COMMERCEGOV_READ_SECRET_ARN": "arn:aws:secretsmanager:us-east-1:1:secret:read",
        }
    ).live_context_enabled is False

    processor, provider = make_processor(
        {
            "classification": "NO_ACTION_REQUIRED",
            "summary": "Synthetic fallback downgrade.",
            "recommended_operator_action": "APPLY",
        }
    )
    response = handle_api_event(
        operational_event(canonical_payload),
        SimpleNamespace(),
        processor,
        bearer_authenticator=StaticBearerAuthenticator(OPERATIONAL_TOKEN),
    )
    body = json.loads(response["body"])
    assert response["statusCode"] == 200
    assert body["intelligence_classification"] == "AUTHORITY_AT_RISK"
    assert body["status"] == "HUMAN_AUTHORITY_REQUIRED"
    assert "scope_key" not in canonical_payload
    assert provider.calls == 1


def test_valid_live_context_reaches_semantic_provider_and_preserves_floor(canonical_payload) -> None:
    transport = FakeReadTransport()
    agent = FakeAgent(output(classification="NO_ACTION_REQUIRED"))
    processor, _provider, ledger, _builder = live_processor(canonical_payload, transport, agent)
    response = handle_payload(processor, canonical_payload)
    assert transport.paths == [
        "/api/integration/v1/shops/demo-shop.myshopify.com/products/7001/content",
        "/api/integration/v1/shops/demo-shop.myshopify.com/policy",
    ]
    assert agent.calls
    assert response["body"]["intelligence_classification"] == "AUTHORITY_AT_RISK"
    assert response["body"]["status"] == "HUMAN_AUTHORITY_REQUIRED"
    assert ledger.evidence["context_source"] == CONTEXT_SOURCE_LIVE
    assert ledger.evidence["policy_hash"] == POLICY_RESPONSE["effective_policy_hash"]
    assert str(ledger.evidence["product_context_hash"]).startswith("sha256:")
    assert ledger.evidence["read_status"] == "ok"
    rendered = json.dumps(ledger.evidence)
    assert READ_TOKEN not in rendered
    assert "Bearer " not in rendered


def test_product_identity_mismatch_skips_bedrock(canonical_payload) -> None:
    product = copy.deepcopy(PRODUCT_RESPONSE)
    product["product_id"] = "9999"
    transport = FakeReadTransport(product=product)
    agent = FakeAgent(output())
    processor, _provider, ledger, _builder = live_processor(canonical_payload, transport, agent)
    response = handle_payload(processor, canonical_payload)
    assert agent.calls == []
    assert response["status_code"] == 200
    assert response["body"]["intelligence_classification"] == "AUTHORITY_AT_RISK"
    assert response["body"]["status"] == "HUMAN_AUTHORITY_REQUIRED"
    assert ledger.evidence["semantic_status"] == "provider_error"
    assert ledger.evidence["context_source"] == CONTEXT_SOURCE_LIVE
    assert ledger.evidence["read_status"] == "failed"


def test_policy_identity_mismatch_skips_bedrock(canonical_payload) -> None:
    policy = copy.deepcopy(POLICY_RESPONSE)
    policy["shop_id"] = "other.myshopify.com"
    transport = FakeReadTransport(policy=policy)
    agent = FakeAgent(output())
    processor, _provider, ledger, _builder = live_processor(canonical_payload, transport, agent)
    response = handle_payload(processor, canonical_payload)
    assert agent.calls == []
    assert response["body"]["status"] == "HUMAN_AUTHORITY_REQUIRED"
    assert ledger.evidence["semantic_status"] == "provider_error"


def test_timeout_and_5xx_preserve_human_required_floor(canonical_payload) -> None:
    agent = FakeAgent(output())
    processor, _provider, ledger, _builder = live_processor(
        canonical_payload,
        FakeReadTransport(error=CommerceGovReadError("commercegov_read_failed")),
        agent,
    )
    response = handle_payload(processor, canonical_payload)
    assert agent.calls == []
    assert response["body"]["intelligence_classification"] == "AUTHORITY_AT_RISK"
    assert response["body"]["status"] == "HUMAN_AUTHORITY_REQUIRED"
    assert ledger.evidence["semantic_status"] == "provider_error"


def test_malformed_commercegov_response_fails_closed(canonical_payload) -> None:
    product = copy.deepcopy(PRODUCT_RESPONSE)
    product.pop("content")
    agent = FakeAgent(output())
    processor, _provider, ledger, _builder = live_processor(
        canonical_payload, FakeReadTransport(product=product), agent
    )
    response = handle_payload(processor, canonical_payload)
    assert agent.calls == []
    assert response["body"]["status"] == "HUMAN_AUTHORITY_REQUIRED"
    assert ledger.evidence["semantic_status"] == "provider_error"


def test_assess_stays_synthetic_when_operational_is_live(canonical_payload) -> None:
    synthetic = RecordingContextBuilder(SyntheticProofContextBuilder(), CONTEXT_SOURCE_SYNTHETIC)
    live_transport = FakeReadTransport()
    live = RecordingContextBuilder(
        SemanticContextBuilder(CommerceGovReadClient(live_transport)),
        CONTEXT_SOURCE_LIVE,
    )
    synthetic_agent = FakeAgent(output())
    live_agent = FakeAgent(output(classification="NO_ACTION_REQUIRED"))
    bindings = TenantBindingRegistry([("demo-agency", "demo-shop.myshopify.com")])
    ledger = CapturingLedger()
    assess_processor = AuthorityProcessor(
        bindings=bindings,
        ledger=InMemoryIdempotencyLedger(),
        semantic_provider=ObservedSemanticProvider(
            StrandsSemanticProvider(
                context_builder=synthetic,
                agent_factory=lambda _tools: synthetic_agent,
            ),
            synthetic,
        ),
    )
    operational_processor = AuthorityProcessor(
        bindings=bindings,
        ledger=ledger,
        semantic_provider=ObservedSemanticProvider(
            StrandsSemanticProvider(
                context_builder=live,
                agent_factory=lambda _tools: live_agent,
            ),
            live,
        ),
    )
    assess_event = {
        "version": "2.0",
        "routeKey": "POST /assess",
        "headers": {"content-type": "application/json"},
        "requestContext": {
            "requestId": "assess-1",
            "http": {"method": "POST"},
            "authorizer": {"iam": {"userArn": "arn:aws:iam::1:user/synthetic"}},
        },
        "body": json.dumps(canonical_payload),
        "isBase64Encoded": False,
    }
    assess = handle_api_event(assess_event, SimpleNamespace(), assess_processor, operational_processor=operational_processor)
    assert json.loads(assess["body"])["status"] == "HUMAN_AUTHORITY_REQUIRED"
    assert live_transport.paths == []
    assert live_agent.calls == []
    assert synthetic_agent.calls

    operational = handle_api_event(
        operational_event(canonical_payload),
        SimpleNamespace(),
        assess_processor,
        bearer_authenticator=StaticBearerAuthenticator(OPERATIONAL_TOKEN),
        operational_processor=operational_processor,
    )
    assert json.loads(operational["body"])["status"] == "HUMAN_AUTHORITY_REQUIRED"
    assert live_transport.paths
    assert ledger.evidence["context_source"] == CONTEXT_SOURCE_LIVE


def test_logs_do_not_include_read_or_inbound_tokens(canonical_payload, caplog) -> None:
    caplog.set_level(logging.INFO, logger="authority_agent.runtime")
    processor, _provider = make_processor({})
    handle_api_event(
        operational_event(canonical_payload),
        SimpleNamespace(),
        processor,
        bearer_authenticator=StaticBearerAuthenticator(OPERATIONAL_TOKEN),
    )
    assert OPERATIONAL_TOKEN not in caplog.text
    assert READ_TOKEN not in caplog.text
    assert "scope_key" not in canonical_payload
