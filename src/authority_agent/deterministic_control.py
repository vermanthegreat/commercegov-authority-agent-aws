"""Non-agentic authority controls. Semantic output cannot change these rules."""

from __future__ import annotations

from typing import Any, Mapping

from authority_agent.contracts import AuthorityEvent, AuthorityResult, SemanticAssessment

_SAFE_RECOMMENDATIONS = frozenset(
    {
        "INVESTIGATE_RISK",
        "REVIEW_EXTERNAL_CHANGE",
        "COMPARE_WITH_GOVERNED_VALUE",
        "RESTORE_GOVERNED_VALUE",
    }
)
_DEFAULT_SUMMARY = (
    "A governed production value changed outside the governed CommerceGov path."
)


def _semantic_fields(value: Any) -> tuple[str, str, str]:
    if isinstance(value, SemanticAssessment):
        return value.classification, value.summary, value.recommended_operator_action
    if isinstance(value, Mapping):
        classification = value.get("classification")
        summary = value.get("summary")
        recommendation = value.get("recommended_operator_action")
        return (
            classification if isinstance(classification, str) else "",
            summary if isinstance(summary, str) else "",
            recommendation if isinstance(recommendation, str) else "",
        )
    return "", "", ""


def enforce_authority_boundary(
    event: AuthorityEvent,
    semantic_output: Any,
    *,
    semantic_status: str = "valid",
) -> AuthorityResult:
    """Apply the immutable external-change authority floor."""

    _classification, raw_summary, raw_recommendation = _semantic_fields(semantic_output)
    summary = raw_summary.strip()
    if not summary or len(summary) > 1000:
        summary = _DEFAULT_SUMMARY
        semantic_status = "invalid"

    recommendation = raw_recommendation.strip().upper()
    if recommendation not in _SAFE_RECOMMENDATIONS:
        recommendation = "REVIEW_EXTERNAL_CHANGE"
        if raw_recommendation:
            semantic_status = "unsafe_recommendation_replaced"

    return AuthorityResult(
        event=event,
        classification="AUTHORITY_AT_RISK",
        summary=summary,
        reason=(
            "Deterministic policy requires human production authority for an "
            "external change to a governed mutation class."
        ),
        recommended_operator_action=recommendation,
        authority_mode="PROPOSE_ONLY",
        human_authority_required=True,
        autonomous_processing="STOP",
        terminal_status="HUMAN_AUTHORITY_REQUIRED",
        semantic_status=semantic_status,
    )

