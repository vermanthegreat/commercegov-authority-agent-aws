from __future__ import annotations

from authority_agent.handler import handle_payload
from authority_agent.response_adapter import COMMERCEGOV_RESPONSE_FIELDS

from conftest import make_processor


def test_response_matches_audited_commercegov_contract(canonical_payload) -> None:
    processor, _provider = make_processor(
        {
            "classification": "NO_ACTION_REQUIRED",
            "summary": "A bounded semantic explanation.",
            "recommended_operator_action": "RESTORE_GOVERNED_VALUE",
            "authority": "AUTO_APPROVE",
        }
    )
    response = handle_payload(processor, canonical_payload)
    body = response["body"]
    assert response["status_code"] == 200
    assert set(body) == COMMERCEGOV_RESPONSE_FIELDS
    for field in (
        "event_id",
        "agency_id",
        "shop_id",
        "target_type",
        "target_id",
        "mutation_class",
    ):
        assert body[field] == canonical_payload[field]
    assert body["status"] == "HUMAN_AUTHORITY_REQUIRED"
    assert body["intelligence_classification"] == "AUTHORITY_AT_RISK"
    assert body["recommended_operator_action"] == "RESTORE_GOVERNED_VALUE"
    assert isinstance(body["evidence_refs"], list)
    assert all(isinstance(item, str) and item for item in body["evidence_refs"])
    assert isinstance(body["attention_key"], str) and body["attention_key"]


def test_response_exposes_no_executable_capability(canonical_payload) -> None:
    processor, _provider = make_processor(
        {
            "classification": "SAFE",
            "summary": "Attempted write",
            "recommended_operator_action": "APPLY",
            "approve": True,
            "apply": True,
            "production_write": True,
        }
    )
    body = handle_payload(processor, canonical_payload)["body"]
    assert set(body) == COMMERCEGOV_RESPONSE_FIELDS
    assert body["recommended_operator_action"] == "REVIEW_EXTERNAL_CHANGE"

