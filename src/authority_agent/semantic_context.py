"""Minimized semantic input and tenant-bound, read-only Strands tools."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from pydantic import BaseModel, ConfigDict
from strands import tool

from authority_agent.commercegov_read import (
    CommerceGovReadClient,
    EffectivePolicySnapshot,
    GovernanceSnapshot,
)
from authority_agent.contracts import AuthorityEvent, TenantBindingError


class SemanticTarget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    target_type: str
    target_id: str


class SemanticPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    effective_policy_hash: str
    controlled: bool
    brand_tone: str
    forbidden_terms: tuple[str, ...]
    max_length: int
    keyword_coverage: str
    proposal_instructions: str


class SemanticHistory(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scope_key: str
    decision_version_id: str | None
    audit_id: int | None
    review_cycle_id: str | None


class SemanticContext(BaseModel):
    """The complete and only event/context object serialized for the model."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    event_type: str
    agency_id: str
    shop_id: str
    mutation_class: str
    target: SemanticTarget
    observed_value: Any
    expected_governed_value: Any
    workflow_stage: str
    policy: SemanticPolicy
    history: SemanticHistory
    authority_mode: str
    human_approval_required: bool


class SemanticContextBuilder:
    def __init__(self, read_client: CommerceGovReadClient) -> None:
        self._read_client = read_client

    def build(
        self, event: AuthorityEvent
    ) -> tuple[SemanticContext, GovernanceSnapshot, EffectivePolicySnapshot]:
        governance = self._read_client.get_governance_snapshot(event)
        policy = self._read_client.get_effective_policy(event)
        if governance.observed_field_value != event.observed_value:
            raise ValueError("commercegov_observed_value_mismatch")
        context = SemanticContext(
            event_id=event.event_id,
            event_type=event.event_type,
            agency_id=event.agency_id,
            shop_id=event.shop_id,
            mutation_class=event.mutation_class,
            target=SemanticTarget(
                target_type=event.target_type,
                target_id=event.target_id,
            ),
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


class ReadOnlyToolRegistry:
    """Cached tools bound to one validated event identity."""

    TOOL_NAMES = ("get_governance_context", "get_effective_policy")

    def __init__(
        self,
        event: AuthorityEvent,
        governance: GovernanceSnapshot,
        policy: EffectivePolicySnapshot,
    ) -> None:
        self._event = event
        self._governance = governance
        self._policy = policy

    def _require_identity(
        self,
        *,
        agency_id: str,
        shop_id: str,
        target_type: str,
        target_id: str,
    ) -> None:
        expected = self._event
        if (
            agency_id != expected.agency_id
            or shop_id != expected.shop_id
            or target_type != expected.target_type
            or target_id != expected.target_id
        ):
            raise TenantBindingError("tool_identity_mismatch")

    def governance_context(
        self, *, agency_id: str, shop_id: str, target_type: str, target_id: str
    ) -> dict[str, Any]:
        self._require_identity(
            agency_id=agency_id,
            shop_id=shop_id,
            target_type=target_type,
            target_id=target_id,
        )
        return asdict(self._governance)

    def effective_policy(
        self, *, agency_id: str, shop_id: str, target_type: str, target_id: str
    ) -> dict[str, Any]:
        self._require_identity(
            agency_id=agency_id,
            shop_id=shop_id,
            target_type=target_type,
            target_id=target_id,
        )
        return asdict(self._policy)

    def as_strands_tools(self) -> list[Any]:
        registry = self

        @tool(name="get_governance_context")
        def get_governance_context(
            agency_id: str, shop_id: str, target_type: str, target_id: str
        ) -> dict[str, Any]:
            """Read cached governance context for the exact bound event target."""

            return registry.governance_context(
                agency_id=agency_id,
                shop_id=shop_id,
                target_type=target_type,
                target_id=target_id,
            )

        @tool(name="get_effective_policy")
        def get_effective_policy(
            agency_id: str, shop_id: str, target_type: str, target_id: str
        ) -> dict[str, Any]:
            """Read cached effective policy for the exact bound event target."""

            return registry.effective_policy(
                agency_id=agency_id,
                shop_id=shop_id,
                target_type=target_type,
                target_id=target_id,
            )

        return [get_governance_context, get_effective_policy]

