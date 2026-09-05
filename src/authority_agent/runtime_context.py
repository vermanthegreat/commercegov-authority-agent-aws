"""Synthetic-only bounded context for the hosted P2 proof."""

from __future__ import annotations

from authority_agent.commercegov_read import EffectivePolicySnapshot, GovernanceSnapshot
from authority_agent.contracts import AuthorityEvent
from authority_agent.semantic_context import (
    SemanticContext,
    SemanticHistory,
    SemanticPolicy,
    SemanticTarget,
)


class SyntheticProofContextBuilder:
    """Builds no-network context from the already validated synthetic event."""

    POLICY_HASH = "sha256:p2-synthetic-proof-policy-v1"

    def build(
        self, event: AuthorityEvent
    ) -> tuple[SemanticContext, GovernanceSnapshot, EffectivePolicySnapshot]:
        governance = GovernanceSnapshot(
            agency_id=event.agency_id,
            shop_id=event.shop_id,
            target_type=event.target_type,
            target_id=event.target_id,
            mutation_class=event.mutation_class,
            workflow_stage="P2_SYNTHETIC_PROOF",
            audit_id=str(event.audit_id) if event.audit_id is not None else None,
            updated_at=event.observed_at or "synthetic",
            observed_field_value=event.observed_value,
        )
        policy = EffectivePolicySnapshot(
            agency_id=event.agency_id,
            shop_id=event.shop_id,
            mutation_class=event.mutation_class,
            effective_policy_hash=self.POLICY_HASH,
            controlled=True,
            brand_tone="clear and factual",
            forbidden_terms=("guaranteed",),
            max_length=4096,
            keyword_coverage="natural",
            proposal_instructions="Return advice for human review only.",
        )
        context = SemanticContext(
            event_id=event.event_id,
            event_type=event.event_type,
            agency_id=event.agency_id,
            shop_id=event.shop_id,
            mutation_class=event.mutation_class,
            target=SemanticTarget(target_type=event.target_type, target_id=event.target_id),
            observed_value=event.observed_value,
            expected_governed_value=event.expected_governed_value,
            workflow_stage=governance.workflow_stage,
            policy=SemanticPolicy(
                effective_policy_hash=policy.effective_policy_hash,
                controlled=policy.controlled,
                brand_tone=policy.brand_tone,
                forbidden_terms=policy.forbidden_terms,
                max_length=policy.max_length,
                keyword_coverage=policy.keyword_coverage,
                proposal_instructions=policy.proposal_instructions,
            ),
            history=SemanticHistory(
                scope_key=event.scope_key,
                decision_version_id=event.decision_version_id,
                audit_id=event.audit_id,
                review_cycle_id=event.review_cycle_id,
            ),
            authority_mode=event.authority_mode,
            human_approval_required=event.human_approval_required,
        )
        return context, governance, policy
