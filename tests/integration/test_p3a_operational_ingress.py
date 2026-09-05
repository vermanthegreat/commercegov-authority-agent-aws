from __future__ import annotations

import copy
import json
import logging
from types import SimpleNamespace

from authority_agent.inbound_auth import StaticBearerAuthenticator
from authority_agent.lambda_runtime import handle_api_event

from conftest import make_processor

OPERATIONAL_TOKEN = "p3a-test-bearer"


def api_event(payload, **changes):
    event = {
        "version": "2.0",
        "routeKey": "POST /assess",
        "rawPath": "/assess",
        "headers": {"content-type": "application/json", "authorization": "never-log-this"},
        "requestContext": {
            "requestId": "request-1",
            "http": {"method": "POST"},
            "authorizer": {"iam": {"userArn": "arn:aws:iam::111122223333:user/synthetic"}},
        },
        "body": json.dumps(payload),
        "isBase64Encoded": False,
    }
    event.update(changes)
    return event


def operational_event(payload, **changes):
    event = api_event(payload)
    event["routeKey"] = "POST /events/operational"
    event["rawPath"] = "/events/operational"
    event["requestContext"] = {
        "requestId": "request-operational-1",
        "http": {"method": "POST"},
    }
    event["headers"] = {
        "content-type": "application/json",
        "authorization": f"Bearer {OPERATIONAL_TOKEN}",
    }
    event.update(changes)
    return event


def invoke(processor, payload_event):
    return handle_api_event(
        payload_event,
        SimpleNamespace(aws_request_id="lambda-p3a"),
        processor,
        bearer_authenticator=StaticBearerAuthenticator(OPERATIONAL_TOKEN),
    )


def test_valid_operational_event_keeps_certified_authority_floor(canonical_payload) -> None:
    processor, provider = make_processor(
        {
            "classification": "NO_ACTION_REQUIRED",
            "summary": "Attempted operational downgrade.",
            "recommended_operator_action": "APPLY",
        }
    )
    response = invoke(processor, operational_event(canonical_payload))
    body = json.loads(response["body"])
    assert response["statusCode"] == 200
    assert body["event_id"] == canonical_payload["event_id"]
    assert body["agency_id"] == canonical_payload["agency_id"]
    assert body["shop_id"] == canonical_payload["shop_id"]
    assert body["target_type"] == canonical_payload["target_type"]
    assert body["target_id"] == canonical_payload["target_id"]
    assert body["mutation_class"] == canonical_payload["mutation_class"]
    assert body["intelligence_classification"] == "AUTHORITY_AT_RISK"
    assert body["status"] == "HUMAN_AUTHORITY_REQUIRED"
    assert "scope_key" not in canonical_payload
    assert canonical_payload["policy_context"]["scope_key"]
    assert provider.calls == 1


def test_missing_and_wrong_bearer_reject_before_model(canonical_payload) -> None:
    processor, provider = make_processor({})
    missing = invoke(processor, operational_event(canonical_payload, headers={"content-type": "application/json"}))
    wrong = invoke(
        processor,
        operational_event(
            canonical_payload,
            headers={"content-type": "application/json", "authorization": "Bearer wrong-token"},
        ),
    )
    assert missing["statusCode"] == 401
    assert json.loads(missing["body"])["error"] == "bearer_authorization_required"
    assert wrong["statusCode"] == 401
    assert json.loads(wrong["body"])["error"] == "bearer_authorization_invalid"
    assert provider.calls == 0


def test_malformed_and_identity_mismatch_fail_closed_after_auth(canonical_payload) -> None:
    processor, provider = make_processor({})
    malformed = invoke(processor, operational_event(canonical_payload, body="{"))
    assert malformed["statusCode"] == 400
    assert json.loads(malformed["body"])["terminal_status"] == "FAIL_CLOSED"

    bound, bound_provider = make_processor({}, bindings=[("other", "other.myshopify.com")])
    mismatch = invoke(bound, operational_event(canonical_payload))
    assert mismatch["statusCode"] == 403
    assert json.loads(mismatch["body"])["terminal_status"] == "FAIL_CLOSED"
    assert provider.calls == 0
    assert bound_provider.calls == 0


def test_duplicate_and_conflict_share_kernel_ledger_with_assess(canonical_payload) -> None:
    processor, provider = make_processor(
        {
            "classification": "AUTHORITY_AT_RISK",
            "summary": "Governed title mismatch.",
            "recommended_operator_action": "RESTORE_GOVERNED_VALUE",
        }
    )
    first = invoke(processor, operational_event(canonical_payload))
    duplicate = invoke(processor, operational_event(canonical_payload))
    assert first["statusCode"] == duplicate["statusCode"] == 200
    assert json.loads(duplicate["body"]) == json.loads(first["body"])
    assert duplicate["headers"]["x-commercegov-cache"] == "HIT"
    assert provider.calls == 1

    conflict_payload = copy.deepcopy(canonical_payload)
    conflict_payload["current_value"] = "Conflicting synthetic value"
    conflict_payload["policy_context"]["observed_shopify_value"] = "Conflicting synthetic value"
    conflict = invoke(processor, operational_event(conflict_payload))
    assert conflict["statusCode"] == 409
    assert json.loads(conflict["body"]) == {
        "error": "conflicting_duplicate",
        "terminal_status": "FAIL_CLOSED",
    }
    assert provider.calls == 1

    assess = handle_api_event(
        api_event(canonical_payload),
        SimpleNamespace(),
        processor,
        bearer_authenticator=StaticBearerAuthenticator(OPERATIONAL_TOKEN),
    )
    assert assess["statusCode"] == 200
    assert assess["headers"]["x-commercegov-cache"] == "HIT"
    assert json.loads(assess["body"]) == json.loads(first["body"])
    assert provider.calls == 1


def test_assess_still_requires_iam_even_with_bearer(canonical_payload) -> None:
    processor, provider = make_processor({})
    event = api_event(canonical_payload)
    event["requestContext"].pop("authorizer")
    event["headers"]["authorization"] = f"Bearer {OPERATIONAL_TOKEN}"
    response = invoke(processor, event)
    assert response["statusCode"] == 403
    assert json.loads(response["body"])["error"] == "iam_authorization_required"
    assert provider.calls == 0


def test_operational_logs_do_not_include_bearer(canonical_payload, caplog) -> None:
    processor, _provider = make_processor({})
    caplog.set_level(logging.INFO, logger="authority_agent.runtime")
    invoke(processor, operational_event(canonical_payload))
    assert OPERATIONAL_TOKEN not in caplog.text
    assert "Bearer " not in caplog.text
