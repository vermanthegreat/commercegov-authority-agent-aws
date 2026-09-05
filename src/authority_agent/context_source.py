"""Bounded context-source evidence for synthetic and live CommerceGov reads."""

from __future__ import annotations

from hashlib import sha256
import json
from time import monotonic
from typing import Any

from authority_agent.commercegov_read import EffectivePolicySnapshot, GovernanceSnapshot
from authority_agent.contracts import AuthorityEvent
from authority_agent.semantic_context import SemanticContext

CONTEXT_SOURCE_SYNTHETIC = "synthetic_proof"
CONTEXT_SOURCE_LIVE = "live_commercegov"


def product_context_hash(governance: GovernanceSnapshot) -> str:
    payload = {
        "agency_id": governance.agency_id,
        "shop_id": governance.shop_id,
        "target_type": governance.target_type,
        "target_id": governance.target_id,
        "mutation_class": governance.mutation_class,
        "workflow_stage": governance.workflow_stage,
        "audit_id": governance.audit_id,
        "updated_at": governance.updated_at,
        "observed_field_value": governance.observed_field_value,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + sha256(encoded.encode("utf-8")).hexdigest()


class RecordingContextBuilder:
    """Wraps a context builder and records bounded hashes, never secrets or bodies."""

    def __init__(self, inner: Any, context_source: str) -> None:
        self._inner = inner
        self._context_source = context_source
        self.last_evidence: dict[str, Any] = {
            "context_source": context_source,
            "read_status": "not_started",
        }

    def build(
        self, event: AuthorityEvent
    ) -> tuple[SemanticContext, GovernanceSnapshot, EffectivePolicySnapshot]:
        started = monotonic()
        self.last_evidence = {
            "context_source": self._context_source,
            "read_status": "started",
            "read_endpoints": "product_content,shop_policy",
        }
        try:
            context, governance, policy = self._inner.build(event)
        except Exception:
            self.last_evidence = {
                "context_source": self._context_source,
                "read_status": "failed",
                "read_endpoints": "product_content,shop_policy",
                "read_latency_ms": round((monotonic() - started) * 1000),
            }
            raise
        self.last_evidence = {
            "context_source": self._context_source,
            "read_status": "ok",
            "read_endpoints": "product_content,shop_policy",
            "read_latency_ms": round((monotonic() - started) * 1000),
            "product_context_hash": product_context_hash(governance),
            "policy_hash": policy.effective_policy_hash,
            "read_identity_shop_id": governance.shop_id,
            "read_identity_target_id": governance.target_id,
        }
        return context, governance, policy
