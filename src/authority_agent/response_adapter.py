"""Adapter for the exact audited CommerceGov operational response shape."""

from __future__ import annotations

from typing import Any

from authority_agent.contracts import AuthorityResult

COMMERCEGOV_RESPONSE_FIELDS = frozenset(
    {
        "event_id",
        "agency_id",
        "shop_id",
        "target_type",
        "target_id",
        "mutation_class",
        "status",
        "intelligence_classification",
        "summary",
        "reason",
        "affected_scope",
        "evidence_refs",
        "recommended_operator_action",
        "attention_key",
    }
)


def to_commercegov_response(result: AuthorityResult) -> dict[str, Any]:
    event = result.event
    evidence_refs = [event.event_id]
    if event.decision_version_id:
        evidence_refs.append(event.decision_version_id)
    if event.audit_id is not None:
        evidence_refs.append(f"audit:{event.audit_id}")
    return {
        "event_id": event.event_id,
        "agency_id": event.agency_id,
        "shop_id": event.shop_id,
        "target_type": event.target_type,
        "target_id": event.target_id,
        "mutation_class": event.mutation_class,
        "status": result.terminal_status,
        "intelligence_classification": result.classification,
        "summary": result.summary,
        "reason": result.reason,
        "affected_scope": event.target_type,
        "evidence_refs": evidence_refs,
        "recommended_operator_action": result.recommended_operator_action,
        "attention_key": f"authority-risk:{event.agency_id}:{event.shop_id}:{event.event_id}",
    }

