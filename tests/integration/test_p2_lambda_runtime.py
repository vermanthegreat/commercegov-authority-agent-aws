from __future__ import annotations

import json
import logging
from types import SimpleNamespace

import pytest

from authority_agent.lambda_runtime import RuntimeConfig, handle_api_event
from conftest import make_processor


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


def test_lambda_request_and_response_adapter(canonical_payload) -> None:
    processor, provider = make_processor(
        {
            "classification": "SAFE",
            "summary": "Attempted hosted downgrade.",
            "recommended_operator_action": "APPLY",
        }
    )
    response = handle_api_event(api_event(canonical_payload), SimpleNamespace(aws_request_id="lambda-1"), processor)
    body = json.loads(response["body"])
    assert response["statusCode"] == 200
    assert response["headers"]["content-type"] == "application/json"
    assert response["headers"]["x-commercegov-cache"] == "MISS"
    assert body["intelligence_classification"] == "AUTHORITY_AT_RISK"
    assert body["status"] == "HUMAN_AUTHORITY_REQUIRED"
    assert body["recommended_operator_action"] != "APPLY"
    assert provider.calls == 1


def test_hosted_timeout_still_returns_safe_deterministic_result(canonical_payload) -> None:
    processor, _provider = make_processor(error=TimeoutError("bedrock timeout"))
    response = handle_api_event(api_event(canonical_payload), SimpleNamespace(), processor)
    body = json.loads(response["body"])
    assert response["statusCode"] == 200
    assert body["intelligence_classification"] == "AUTHORITY_AT_RISK"
    assert body["status"] == "HUMAN_AUTHORITY_REQUIRED"


@pytest.mark.parametrize(
    ("mutate", "status"),
    [
        (lambda event: event["requestContext"].pop("authorizer"), 403),
        (lambda event: event["requestContext"]["http"].update(method="GET"), 405),
        (lambda event: event["headers"].update({"content-type": "text/plain"}), 415),
        (lambda event: event.update(body="not-json"), 400),
    ],
)
def test_transport_validation_fails_before_processing(canonical_payload, mutate, status) -> None:
    processor, provider = make_processor({})
    event = api_event(canonical_payload)
    mutate(event)
    response = handle_api_event(event, SimpleNamespace(), processor)
    assert response["statusCode"] == status
    assert json.loads(response["body"])["terminal_status"] == "FAIL_CLOSED"
    assert provider.calls == 0


def test_safe_logs_do_not_include_headers_or_payload_values(canonical_payload, caplog) -> None:
    processor, _provider = make_processor({})
    caplog.set_level(logging.INFO, logger="authority_agent.runtime")
    handle_api_event(api_event(canonical_payload), SimpleNamespace(), processor)
    rendered = caplog.text
    assert "never-log-this" not in rendered
    assert canonical_payload["current_value"] not in rendered
    assert "request-1" in rendered
    assert canonical_payload["event_id"] in rendered


def test_runtime_configuration_is_explicit_and_model_locked() -> None:
    base = {
        "AUTHORITY_TABLE_NAME": "table",
        "ALLOWED_AGENCY_ID": "demo-agency",
        "ALLOWED_SHOP_ID": "demo-shop.myshopify.com",
        "AWS_REGION": "us-east-1",
        "BEDROCK_MODEL_ID": "global.anthropic.claude-sonnet-4-6",
        "SEMANTIC_TIMEOUT_SECONDS": "24",
        "RUNTIME_BUILD_ID": "candidate",
    }
    assert RuntimeConfig.from_env(base).region_name == "us-east-1"
    with pytest.raises(ValueError, match="unapproved_bedrock_model"):
        RuntimeConfig.from_env(base | {"BEDROCK_MODEL_ID": "random-model"})
    with pytest.raises(ValueError, match="missing_runtime_configuration"):
        RuntimeConfig.from_env(base | {"AUTHORITY_TABLE_NAME": ""})
    with pytest.raises(ValueError, match="invalid_semantic_timeout"):
        RuntimeConfig.from_env(base | {"SEMANTIC_TIMEOUT_SECONDS": "25"})
