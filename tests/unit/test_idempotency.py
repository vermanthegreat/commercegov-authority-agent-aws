from __future__ import annotations

import copy

from authority_agent.handler import handle_payload

from conftest import make_processor


def test_exact_completed_duplicate_returns_cached_result(canonical_payload) -> None:
    processor, provider = make_processor(
        {
            "classification": "NO_ACTION_REQUIRED",
            "summary": "Semantic result",
            "recommended_operator_action": "REVIEW_EXTERNAL_CHANGE",
        }
    )
    first = handle_payload(processor, canonical_payload)
    second = handle_payload(processor, canonical_payload)
    assert first["status_code"] == second["status_code"] == 200
    assert first["body"] == second["body"]
    assert first["cached"] is False
    assert second["cached"] is True
    assert provider.calls == 1


def test_same_identity_with_different_payload_is_conflict(canonical_payload) -> None:
    processor, provider = make_processor({})
    assert handle_payload(processor, canonical_payload)["status_code"] == 200
    conflict = copy.deepcopy(canonical_payload)
    conflict["current_value"] = "different"
    conflict["policy_context"]["observed_shopify_value"] = "different"
    result = handle_payload(processor, conflict)
    assert result["status_code"] == 409
    assert result["body"] == {
        "error": "conflicting_duplicate",
        "terminal_status": "FAIL_CLOSED",
    }
    assert provider.calls == 1


def test_same_event_id_under_different_allowed_tenant_fails_closed(
    canonical_payload,
) -> None:
    processor, provider = make_processor(
        {},
        bindings=[
            ("demo-agency", "demo-shop.myshopify.com"),
            ("other-agency", "other-shop.myshopify.com"),
        ],
    )
    assert handle_payload(processor, canonical_payload)["status_code"] == 200
    other = copy.deepcopy(canonical_payload)
    other["agency_id"] = "other-agency"
    other["shop_id"] = "other-shop.myshopify.com"
    result = handle_payload(processor, other)
    assert result["status_code"] == 409
    assert result["body"]["error"] == "event_tenant_identity_conflict"
    assert provider.calls == 1

