"""P4 authority-property evaluation matrix. Not a model benchmark."""

from __future__ import annotations

import copy
import json
import logging
from datetime import timedelta
from types import SimpleNamespace

import pytest

from authority_agent.commercegov_read import CommerceGovReadError
from authority_agent.context_source import CONTEXT_SOURCE_LIVE, CONTEXT_SOURCE_SYNTHETIC
from authority_agent.demo_surface import CSP
from authority_agent.deterministic_control import enforce_authority_boundary
from authority_agent.evidence_view import project_assessment_evidence
from authority_agent.handler import handle_payload
from authority_agent.inbound_auth import StaticBearerAuthenticator
from authority_agent.lambda_runtime import handle_api_event
from authority_agent.normalization import normalize_commercegov_event
from authority_agent.oauth_credentials import OAuthCredentialError
from authority_agent.strands_provider import SemanticProviderFailure, SemanticProviderTimeout
from tests.integration.test_p1_strands_provider import FakeAgent, output, provider_for
from tests.integration.test_p3a_operational_ingress import invoke as invoke_operational
from tests.integration.test_p3a_operational_ingress import operational_event
from tests.integration.test_p3b_live_context import CapturingLedger, live_processor
from tests.integration.test_p4_demo_runtime import demo_get, demo_run, invoke as invoke_demo
from tests.integration.test_p4_demo_runtime import settings as demo_settings
from tests.integration.test_p4_oauth_refresh import (
    Secrets,
    build_manager,
    response,
)
from tests.p1_helpers import FakeReadTransport, PRODUCT_RESPONSE
from tests.unit.test_oauth_credentials import (
    NOW as OAUTH_NOW,
    FakeLeaseTable,
    FakeResponse,
    FakeSecrets,
    envelope_json,
    manager,
)
from conftest import make_processor

AGENCY = "shop_controlled-demo_myshopify_com"
SHOP = "controlled-demo.myshopify.com"
OPERATIONAL_TOKEN = "p3a-test-bearer"


def _floor(body: dict) -> None:
    assert body["intelligence_classification"] == "AUTHORITY_AT_RISK"
    assert body["status"] == "HUMAN_AUTHORITY_REQUIRED"
    assert body.get("autonomous_processing", "STOP") in {"STOP", None}


def test_01_valid_operational_event(canonical_payload) -> None:
    processor, provider = make_processor(
        {
            "classification": "REVIEW_REQUIRED",
            "summary": "Review the governed title.",
            "recommended_operator_action": "REVIEW_EXTERNAL_CHANGE",
        }
    )
    response_body = invoke_operational(processor, operational_event(canonical_payload))
    body = json.loads(response_body["body"])
    assert response_body["statusCode"] == 200
    _floor(body)
    assert provider.calls == 1


def test_02_wrong_inbound_bearer(canonical_payload) -> None:
    processor, provider = make_processor({})
    wrong = invoke_operational(
        processor,
        operational_event(
            canonical_payload,
            headers={"content-type": "application/json", "authorization": "Bearer wrong-token"},
        ),
    )
    assert wrong["statusCode"] == 401
    assert provider.calls == 0


def test_03_wrong_agency(canonical_payload) -> None:
    processor, provider = make_processor({}, bindings=[("other-agency", "demo-shop.myshopify.com")])
    response_body = invoke_operational(processor, operational_event(canonical_payload))
    assert response_body["statusCode"] == 403
    assert json.loads(response_body["body"])["terminal_status"] == "FAIL_CLOSED"
    assert provider.calls == 0


def test_04_wrong_shop(canonical_payload) -> None:
    processor, provider = make_processor({}, bindings=[("demo-agency", "other.myshopify.com")])
    response_body = invoke_operational(processor, operational_event(canonical_payload))
    assert response_body["statusCode"] == 403
    assert provider.calls == 0


def test_05_wrong_product_target(canonical_payload) -> None:
    product = copy.deepcopy(PRODUCT_RESPONSE)
    product["product_id"] = "9999"
    agent = FakeAgent(output())
    processor, _provider, ledger, _builder = live_processor(
        canonical_payload, FakeReadTransport(product=product), agent
    )
    result = handle_payload(processor, canonical_payload)
    assert agent.calls == []
    assert result["body"]["status"] == "HUMAN_AUTHORITY_REQUIRED"
    assert ledger.evidence["semantic_status"] == "provider_error"


def test_06_missing_commercegov_context(canonical_payload) -> None:
    agent = FakeAgent(output())
    processor, _provider, ledger, _builder = live_processor(
        canonical_payload,
        FakeReadTransport(error=CommerceGovReadError("commercegov_read_failed")),
        agent,
    )
    result = handle_payload(processor, canonical_payload)
    assert agent.calls == []
    assert ledger.evidence["semantic_status"] == "provider_error"
    assert result["body"]["intelligence_classification"] == "AUTHORITY_AT_RISK"


def test_07_commercegov_timeout(canonical_payload) -> None:
    from authority_agent.commercegov_read import CommerceGovReadClient
    from authority_agent.semantic_context import SemanticContextBuilder
    from authority_agent.strands_provider import StrandsSemanticProvider

    event = normalize_commercegov_event(canonical_payload)
    builder = SemanticContextBuilder(
        CommerceGovReadClient(FakeReadTransport(error=TimeoutError("read timeout")))
    )
    timed = StrandsSemanticProvider(context_builder=builder, agent_factory=lambda _tools: FakeAgent(output()))
    with pytest.raises(SemanticProviderFailure):
        timed.assess(event)


def test_08_oauth_access_token_expiry_recovery(monkeypatch: pytest.MonkeyPatch) -> None:
    secrets = Secrets()
    refresh_calls: list[dict] = []
    oauth = build_manager(secrets, refresh_calls)
    seen: list[str] = []

    def get(url: str, **kwargs):
        auth = kwargs["headers"]["Authorization"]
        seen.append(auth)
        if auth == "Bearer access-old":
            return response(401, {"error": {"code": "token_expired"}})
        return response(200, {"ok": True})

    monkeypatch.setattr("authority_agent.commercegov_read.httpx.get", get)
    from authority_agent.live_read_transport import LazyHttpsCommerceGovReadTransport

    transport = LazyHttpsCommerceGovReadTransport(
        base_url="https://app.commercegov.io",
        credential_manager=oauth,
        timeout_seconds=5.0,
    )
    assert transport.get_json("/api/integration/v1/shops/demo/policy") == {"ok": True}
    assert seen == ["Bearer access-old", "Bearer access-new"]
    assert refresh_calls


def test_09_oauth_refresh_failure() -> None:
    secrets = FakeSecrets(envelope_json(expires_at=OAUTH_NOW + timedelta(seconds=30)))
    table = FakeLeaseTable()
    mgr = manager(
        secrets,
        table,
        http_post=lambda *args, **kwargs: FakeResponse(400, {"error": "invalid_grant"}),
    )
    with pytest.raises(OAuthCredentialError) as exc:
        mgr.access_token()
    assert exc.value.code == "oauth_refresh_rejected"
    assert secrets.put_calls == []
    assert "refresh-old" not in str(exc.value)


def test_10_bedrock_timeout(canonical_payload) -> None:
    event, provider, _captured = provider_for(
        canonical_payload, FakeAgent(output(), delay=0.03), timeout_seconds=0.001
    )
    with pytest.raises(SemanticProviderTimeout):
        provider.assess(event)


def test_11_bedrock_provider_error(canonical_payload) -> None:
    event, provider, _captured = provider_for(
        canonical_payload, FakeAgent(error=RuntimeError("model unavailable"))
    )
    with pytest.raises(SemanticProviderFailure):
        provider.assess(event)
    processor, _inner = make_processor(error=RuntimeError("model unavailable"))
    result = handle_payload(processor, canonical_payload)
    assert result["status_code"] == 200
    assert result["body"]["intelligence_classification"] == "AUTHORITY_AT_RISK"
    assert result["body"]["status"] == "HUMAN_AUTHORITY_REQUIRED"


def test_12_model_downgrade_protection_fixture(canonical_payload) -> None:
    event = normalize_commercegov_event(canonical_payload)
    result = enforce_authority_boundary(
        event,
        {
            "classification": "NO_ACTION_REQUIRED",
            "summary": "FIXTURE: MODEL_DOWNGRADE_PROTECTION",
            "recommended_operator_action": "REVIEW_EXTERNAL_CHANGE",
        },
    )
    assert result.classification == "AUTHORITY_AT_RISK"
    assert result.terminal_status == "HUMAN_AUTHORITY_REQUIRED"
    assert result.autonomous_processing == "STOP"
    processor, _provider = make_processor(
        {
            "classification": "NO_ACTION_REQUIRED",
            "summary": "FIXTURE: MODEL_DOWNGRADE_PROTECTION",
            "recommended_operator_action": "REVIEW_EXTERNAL_CHANGE",
        }
    )
    handled = handle_payload(processor, canonical_payload)
    assert handled["body"]["intelligence_classification"] == "AUTHORITY_AT_RISK"
    assert handled["body"]["status"] == "HUMAN_AUTHORITY_REQUIRED"


def test_13_duplicate_event(canonical_payload) -> None:
    processor, provider = make_processor({})
    first = invoke_operational(processor, operational_event(canonical_payload))
    duplicate = invoke_operational(processor, operational_event(canonical_payload))
    assert first["statusCode"] == duplicate["statusCode"] == 200
    assert duplicate["headers"]["x-commercegov-cache"] == "HIT"
    assert provider.calls == 1


def test_14_conflicting_duplicate(canonical_payload) -> None:
    processor, provider = make_processor({})
    invoke_operational(processor, operational_event(canonical_payload))
    conflict_payload = copy.deepcopy(canonical_payload)
    conflict_payload["current_value"] = "Conflicting synthetic value"
    conflict_payload["policy_context"]["observed_shopify_value"] = "Conflicting synthetic value"
    conflict = invoke_operational(processor, operational_event(conflict_payload))
    assert conflict["statusCode"] == 409
    assert json.loads(conflict["body"])["error"] == "conflicting_duplicate"
    assert provider.calls == 1


def test_15_malformed_event(canonical_payload) -> None:
    processor, provider = make_processor({})
    malformed = invoke_operational(processor, operational_event(canonical_payload, body="{"))
    assert malformed["statusCode"] == 400
    assert json.loads(malformed["body"])["terminal_status"] == "FAIL_CLOSED"
    assert provider.calls == 0


def test_16_cross_tenant_context_substitution(canonical_payload) -> None:
    policy = copy.deepcopy(__import__("tests.p1_helpers", fromlist=["POLICY_RESPONSE"]).POLICY_RESPONSE)
    policy["shop_id"] = "other.myshopify.com"
    agent = FakeAgent(output())
    processor, _provider, ledger, _builder = live_processor(
        canonical_payload, FakeReadTransport(policy=policy), agent
    )
    result = handle_payload(processor, canonical_payload)
    assert agent.calls == []
    assert result["body"]["status"] == "HUMAN_AUTHORITY_REQUIRED"
    assert ledger.evidence["semantic_status"] == "provider_error"


def test_17_access_token_leakage_blocked() -> None:
    view = project_assessment_evidence(
        body={
            "event_id": "e",
            "shop_id": SHOP,
            "target_id": "1",
            "mutation_class": "product.title",
            "intelligence_classification": "AUTHORITY_AT_RISK",
            "status": "HUMAN_AUTHORITY_REQUIRED",
        },
        cached=False,
        ledger_evidence={"access_token": "cgint_live_secret", "semantic_summary": "ok access_token=cgint_live_secret"},
    )
    blob = json.dumps(view)
    assert "cgint_live_secret" not in blob
    assert "access_token" not in blob


def test_18_refresh_token_leakage_blocked() -> None:
    view = project_assessment_evidence(
        body={"event_id": "e", "intelligence_classification": "AUTHORITY_AT_RISK", "status": "HUMAN_AUTHORITY_REQUIRED"},
        cached=False,
        ledger_evidence={"refresh_token": "cgrfr_secret", "Authorization": "Bearer inbound"},
    )
    blob = json.dumps(view)
    assert "cgrfr_secret" not in blob
    assert "Bearer inbound" not in blob


def test_19_live_product_context_hash(canonical_payload) -> None:
    agent = FakeAgent(output(classification="NO_ACTION_REQUIRED"))
    processor, _provider, ledger, _builder = live_processor(
        canonical_payload, FakeReadTransport(), agent
    )
    handle_payload(processor, canonical_payload)
    assert ledger.evidence["context_source"] == CONTEXT_SOURCE_LIVE
    assert str(ledger.evidence["product_context_hash"]).startswith("sha256:")


def test_20_live_policy_hash(canonical_payload) -> None:
    agent = FakeAgent(output())
    processor, _provider, ledger, _builder = live_processor(
        canonical_payload, FakeReadTransport(), agent
    )
    handle_payload(processor, canonical_payload)
    assert ledger.evidence["policy_hash"] == "sha256:demo-policy"
    assert ledger.evidence["context_source"] == CONTEXT_SOURCE_LIVE


def test_21_synthetic_context_not_labeled_live(canonical_payload) -> None:
    from authority_agent.context_source import RecordingContextBuilder
    from authority_agent.lambda_runtime import ObservedSemanticProvider
    from authority_agent.orchestration import AuthorityProcessor, InMemoryIdempotencyLedger, TenantBindingRegistry
    from authority_agent.runtime_context import SyntheticProofContextBuilder
    from authority_agent.strands_provider import StrandsSemanticProvider

    synthetic = RecordingContextBuilder(SyntheticProofContextBuilder(), CONTEXT_SOURCE_SYNTHETIC)
    processor = AuthorityProcessor(
        bindings=TenantBindingRegistry([("demo-agency", "demo-shop.myshopify.com")]),
        ledger=CapturingLedger(),
        semantic_provider=ObservedSemanticProvider(
            StrandsSemanticProvider(
                context_builder=synthetic,
                agent_factory=lambda _tools: FakeAgent(output()),
            ),
            synthetic,
        ),
    )
    handle_payload(processor, canonical_payload)
    assert processor.ledger.evidence["context_source"] == CONTEXT_SOURCE_SYNTHETIC
    assert processor.ledger.evidence["context_source"] != CONTEXT_SOURCE_LIVE


def test_22_final_human_authority_required(canonical_payload) -> None:
    result = handle_payload(make_processor({})[0], canonical_payload)
    assert result["body"]["status"] == "HUMAN_AUTHORITY_REQUIRED"


def test_23_final_stop(canonical_payload) -> None:
    event = normalize_commercegov_event(canonical_payload)
    result = enforce_authority_boundary(event, None, semantic_status="provider_error")
    assert result.autonomous_processing == "STOP"


def test_24_public_demo_rejects_arbitrary_query() -> None:
    processor, provider = make_processor({}, bindings=[(AGENCY, SHOP)])
    query = invoke_demo(demo_run(rawQueryString="shop=evil.myshopify.com"), processor, demo_settings())
    evidence = invoke_demo(demo_get(rawQueryString="evidence_id=evidence:abc"), processor, demo_settings())
    assert query["statusCode"] == 400
    assert evidence["statusCode"] == 400
    assert provider.calls == 0
    assert "generic evidence" not in query["body"].lower()


def test_25_public_demo_rejects_arbitrary_body() -> None:
    processor, provider = make_processor({}, bindings=[(AGENCY, SHOP)])
    body = invoke_demo(
        demo_run(headers={"content-type": "application/json"}, body='{"shop_id":"evil.myshopify.com"}'),
        processor,
        demo_settings(),
    )
    assert body["statusCode"] == 400
    assert provider.calls == 0


def test_26_same_demo_bucket_does_not_call_bedrock_twice() -> None:
    processor, provider = make_processor(
        {"classification": "SAFE", "summary": "ok", "recommended_operator_action": "REVIEW_EXTERNAL_CHANGE"},
        bindings=[(AGENCY, SHOP)],
    )
    clock = {"now": demo_settings().clock()}

    def current():
        return clock["now"]

    settings = demo_settings(clock=current)
    first = invoke_demo(demo_run(), processor, settings)
    second = invoke_demo(demo_run(), processor, settings)
    assert first["statusCode"] == second["statusCode"] == 200
    assert "CACHED — IDEMPOTENT REPLAY" in second["body"]
    assert provider.calls == 1
    clock["now"] = clock["now"] + timedelta(minutes=5)
    third = invoke_demo(demo_run(), processor, settings)
    assert provider.calls == 2
    assert third["statusCode"] == 200
    assert CSP in first["headers"].values() or first["headers"]["content-security-policy"] == CSP


def test_public_html_and_logs_omit_secrets(canonical_payload, caplog) -> None:
    caplog.set_level(logging.INFO)
    processor, _provider = make_processor({})
    invoke_operational(processor, operational_event(canonical_payload))
    assert OPERATIONAL_TOKEN not in caplog.text
    assert "SecretString" not in caplog.text
    html = invoke_demo(demo_run(), make_processor({}, bindings=[(AGENCY, SHOP)])[0], demo_settings())["body"]
    lowered = html.lower()
    assert "access_token" not in lowered
    assert "refresh_token" not in lowered
    assert "secretstring" not in lowered
    assert "arn:aws:secretsmanager" not in lowered
