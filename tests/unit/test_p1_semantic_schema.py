from __future__ import annotations

import pytest
from pydantic import ValidationError

from authority_agent.strands_provider import SemanticAssessmentSchema


def valid_output() -> dict:
    return {
        "classification": "REVIEW_REQUIRED",
        "summary": "The observed title differs from the governed value.",
        "recommended_operator_action": "COMPARE_WITH_GOVERNED_VALUE",
        "confidence": 0.91,
    }


def test_schema_accepts_only_advisory_output() -> None:
    parsed = SemanticAssessmentSchema.model_validate(valid_output())
    assert parsed.classification == "REVIEW_REQUIRED"
    assert parsed.confidence == 0.91


@pytest.mark.parametrize(
    "change",
    [
        {"authority": "AUTO_APPROVE"},
        {"apply": True},
        {"classification": "APPROVED"},
        {"classification": "SAFE"},
        {"recommended_operator_action": "APPLY"},
        {"recommended_operator_action": "APPROVE"},
        {"recommended_operator_action": "AUTO_REMEDIATE"},
        {"recommended_operator_action": "WRITE_PRODUCTION"},
        {"summary": ""},
        {"confidence": 1.01},
    ],
)
def test_schema_rejects_executable_or_malformed_output(change) -> None:
    candidate = valid_output() | change
    with pytest.raises(ValidationError):
        SemanticAssessmentSchema.model_validate(candidate)
