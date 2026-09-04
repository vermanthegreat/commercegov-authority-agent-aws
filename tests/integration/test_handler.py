from __future__ import annotations

import copy
import json
from pathlib import Path

from authority_agent.handler import handle_payload, main

from conftest import ROOT, make_processor


def test_canonical_handler_result_is_always_human_required(canonical_payload) -> None:
    processor, provider = make_processor(
        {
            "classification": "NO_ACTION_REQUIRED",
            "summary": "The model says no action.",
            "recommended_operator_action": "APPLY",
            "authority": "AUTO_APPROVE",
        }
    )
    response = handle_payload(processor, canonical_payload)
    assert response["status_code"] == 200
    assert response["body"]["intelligence_classification"] == "AUTHORITY_AT_RISK"
    assert response["body"]["status"] == "HUMAN_AUTHORITY_REQUIRED"
    assert response["body"]["recommended_operator_action"] == "REVIEW_EXTERNAL_CHANGE"
    assert provider.calls == 1


def test_semantic_provider_exception_fails_safely(canonical_payload) -> None:
    processor, provider = make_processor(error=RuntimeError("provider unavailable"))
    response = handle_payload(processor, canonical_payload)
    assert response["status_code"] == 200
    assert response["body"]["intelligence_classification"] == "AUTHORITY_AT_RISK"
    assert response["body"]["status"] == "HUMAN_AUTHORITY_REQUIRED"
    assert provider.calls == 1


def test_empty_semantic_result_fails_safely(canonical_payload) -> None:
    processor, _provider = make_processor(None)
    response = handle_payload(processor, canonical_payload)
    assert response["status_code"] == 200
    assert response["body"]["intelligence_classification"] == "AUTHORITY_AT_RISK"
    assert response["body"]["status"] == "HUMAN_AUTHORITY_REQUIRED"


def test_binding_failure_prevents_semantic_invocation(canonical_payload) -> None:
    processor, provider = make_processor({}, bindings=[("other", "other.myshopify.com")])
    response = handle_payload(processor, canonical_payload)
    assert response["status_code"] == 403
    assert response["body"]["terminal_status"] == "FAIL_CLOSED"
    assert provider.calls == 0


def test_malformed_event_returns_400_without_semantic_invocation(canonical_payload) -> None:
    processor, provider = make_processor({})
    payload = copy.deepcopy(canonical_payload)
    payload["shop_id"] = "bad-shop"
    response = handle_payload(processor, payload)
    assert response["status_code"] == 400
    assert response["body"]["terminal_status"] == "FAIL_CLOSED"
    assert provider.calls == 0


def test_local_runner_processes_canonical_fixture(capsys) -> None:
    fixture = ROOT / "fixtures" / "external_product_title_change.json"
    assert main([str(fixture)]) == 0
    rendered = json.loads(capsys.readouterr().out)
    assert rendered["status_code"] == 200
    assert rendered["body"]["intelligence_classification"] == "AUTHORITY_AT_RISK"
    assert rendered["body"]["status"] == "HUMAN_AUTHORITY_REQUIRED"


def test_fixture_files_are_valid_json() -> None:
    for name in (
        "external_product_title_change.json",
        "duplicate_conflict.json",
        "malformed_event.json",
    ):
        assert isinstance(json.loads((ROOT / "fixtures" / name).read_text()), dict)
