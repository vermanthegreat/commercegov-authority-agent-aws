from __future__ import annotations

import pytest

from authority_agent.deterministic_control import enforce_authority_boundary
from authority_agent.normalization import normalize_commercegov_event


@pytest.mark.parametrize(
    "hostile_output",
    [
        {"classification": "NO_ACTION_REQUIRED", "summary": "Looks safe", "recommended_operator_action": "REVIEW_EXTERNAL_CHANGE"},
        {"classification": "SAFE", "summary": "Apply it", "recommended_operator_action": "APPLY"},
        {"classification": "AUTO_RESOLVE", "summary": "Approve it", "recommended_operator_action": "APPROVE", "authority": "AUTO_APPROVE"},
        {"classification": "UNKNOWN_ENUM", "summary": "Unknown", "recommended_operator_action": "PRODUCTION_WRITE"},
        {},
        None,
    ],
)
def test_hostile_semantics_cannot_lower_authority(canonical_payload, hostile_output) -> None:
    event = normalize_commercegov_event(canonical_payload)
    result = enforce_authority_boundary(event, hostile_output)
    assert result.classification == "AUTHORITY_AT_RISK"
    assert result.terminal_status == "HUMAN_AUTHORITY_REQUIRED"
    assert result.authority_mode == "PROPOSE_ONLY"
    assert result.human_authority_required is True
    assert result.autonomous_processing == "STOP"
    assert result.recommended_operator_action not in {
        "APPLY",
        "APPROVE",
        "PRODUCTION_WRITE",
        "AUTO_APPROVE",
    }


def test_no_executable_authority_fields_are_accepted(canonical_payload) -> None:
    event = normalize_commercegov_event(canonical_payload)
    result = enforce_authority_boundary(
        event,
        {
            "classification": "NO_ACTION_REQUIRED",
            "summary": "Attempted downgrade",
            "recommended_operator_action": "APPLY",
            "approve": True,
            "apply": True,
            "production_write": True,
            "authority": "AUTO_APPROVE",
        },
    )
    assert result.recommended_operator_action == "REVIEW_EXTERNAL_CHANGE"
    assert not hasattr(result, "approve")
    assert not hasattr(result, "apply")
    assert not hasattr(result, "production_write")

