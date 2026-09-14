"""Deterministic host execution for the judge prompt page."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any, Literal, Protocol
from uuid import uuid4

from authority_agent.commercegov_read import CommerceGovReadError
from authority_agent.commercegov_proposal import (
    CommerceGovProposalError,
    ProductRef,
    ProductResolutionError,
    ProposalCreateResult,
    TARGET_NOT_FOUND,
    display_governance_state,
    domain_denial_reason,
    list_stage_blocks_new_proposal,
)
from authority_agent.prompt_intent import (
    ALLOWED_PROMPT_MUTATION_CLASSES,
    PromptIntent,
    PromptInterpreter,
)
from authority_agent.strands_provider import SemanticProviderFailure

RunState = Literal["SUCCESS", "DENIED", "ERROR"]
AGENT_AUTHORITY = "PROPOSE_ONLY"
PRODUCTION_MUTATION_NONE = "NONE"
LOGGER = logging.getLogger("authority_agent.prompt_runtime")


class PromptHost(Protocol):
    def shop_policy(self, shop_id: str) -> dict[str, Any]:
        ...

    def find_product(self, shop_id: str, query: str) -> ProductRef | None:
        ...

    def create_title_proposal(
        self,
        *,
        shop_id: str,
        product_id: str,
        title: str,
        idempotency_key: str,
    ) -> ProposalCreateResult:
        ...


@dataclass(frozen=True, slots=True)
class PromptRunResult:
    state: RunState
    agent_response: str
    evidence: dict[str, str]


class PromptRuntime:
    def __init__(
        self,
        *,
        interpreter: PromptInterpreter,
        shop_id: str,
        host: PromptHost | None = None,
    ) -> None:
        self._interpreter = interpreter
        self._shop_id = shop_id
        self._host = host

    def execute(self, *, prompt: str, run_id: str) -> PromptRunResult:
        evidence: dict[str, str] = {
            "aws_run_id": str(run_id or "").strip(),
            "agent_authority": AGENT_AUTHORITY,
            "production_mutation": PRODUCTION_MUTATION_NONE,
        }
        evidence = {key: value for key, value in evidence.items() if value}
        text = str(prompt or "").strip()
        if not text:
            return PromptRunResult("ERROR", "", {**evidence, "denial_reason": "empty_prompt"})

        policy_context: dict[str, Any] = {}
        if self._host is not None:
            try:
                policy_context = self._host.shop_policy(self._shop_id) or {}
            except Exception:
                policy_context = {}

        try:
            intent = self._interpreter.interpret(
                prompt=text,
                policy_context=policy_context or None,
                run_id=str(run_id or ""),
            )
        except SemanticProviderFailure as exc:
            return PromptRunResult(
                "ERROR",
                "",
                {**evidence, "denial_reason": str(exc) or "semantic_provider_failed"},
            )

        agent_response = intent.summary.strip()
        if intent.action in {"APPROVE", "APPLY"}:
            return PromptRunResult(
                "DENIED",
                agent_response,
                _with_evidence(
                    evidence,
                    action=intent.action,
                    decision="DENIED",
                    policy_result="DENIED",
                    required_authority="HUMAN",
                    denial_reason="agent_may_not_" + intent.action.lower(),
                    proposal_id=intent.proposal_id.strip() or None,
                ),
            )
        if intent.action != "PROPOSE":
            return PromptRunResult(
                "ERROR",
                agent_response,
                _with_evidence(evidence, denial_reason="unrecognized_agent_action"),
            )
        mutation = str(intent.mutation_class or "").strip() or "product.title"
        if mutation not in ALLOWED_PROMPT_MUTATION_CLASSES or mutation != "product.title":
            return PromptRunResult(
                "ERROR",
                agent_response,
                _with_evidence(
                    evidence,
                    requested_mutation=mutation,
                    denial_reason="unsupported_mutation_class",
                ),
            )
        if self._host is None:
            return PromptRunResult(
                "ERROR",
                agent_response,
                _with_evidence(evidence, denial_reason="proposal_adapter_unavailable"),
            )
        proposed = intent.proposed_value.strip()
        if not proposed:
            return PromptRunResult(
                "ERROR",
                agent_response,
                _with_evidence(
                    evidence,
                    requested_mutation=mutation,
                    denial_reason="missing_proposed_value",
                ),
            )
        try:
            product = self._host.find_product(self._shop_id, intent.product_query)
        except ProductResolutionError as exc:
            reason = str(exc.code or "").strip() or TARGET_NOT_FOUND
            return PromptRunResult(
                "DENIED",
                agent_response,
                _with_evidence(
                    evidence,
                    action="PROPOSE",
                    requested_mutation=mutation,
                    target_product=str(intent.product_query or "").strip() or None,
                    decision="DENIED",
                    denial_reason=reason,
                ),
            )
        except CommerceGovReadError as exc:
            reason = str(exc.code or "").strip() or "product_lookup_failed"
            LOGGER.warning("product_lookup_read_error code=%s", reason)
            return PromptRunResult(
                "ERROR",
                agent_response,
                _with_evidence(
                    evidence,
                    requested_mutation=mutation,
                    denial_reason=reason,
                ),
            )
        except Exception:
            LOGGER.exception("product_lookup_failed")
            return PromptRunResult(
                "ERROR",
                agent_response,
                _with_evidence(
                    evidence,
                    requested_mutation=mutation,
                    denial_reason="product_lookup_failed",
                ),
            )
        if product is None:
            return PromptRunResult(
                "DENIED",
                agent_response,
                _with_evidence(
                    evidence,
                    action="PROPOSE",
                    requested_mutation=mutation,
                    target_product=str(intent.product_query or "").strip() or None,
                    decision="DENIED",
                    denial_reason=TARGET_NOT_FOUND,
                ),
            )
        evidence = _with_evidence(
            evidence,
            action="PROPOSE",
            target_product=f"{product.title} ({product.product_id})",
            requested_mutation=mutation,
            current_state=display_governance_state(product.stage) or None,
        )
        if list_stage_blocks_new_proposal(product.stage):
            return PromptRunResult(
                "DENIED",
                agent_response,
                _with_evidence(
                    evidence,
                    decision="DENIED",
                    denial_reason=domain_denial_reason("product_not_governable"),
                ),
            )
        try:
            created = self._host.create_title_proposal(
                shop_id=self._shop_id,
                product_id=product.product_id,
                title=proposed,
                idempotency_key=_idempotency_key(run_id),
            )
        except CommerceGovProposalError as exc:
            reason = domain_denial_reason(exc.code)
            if reason is not None:
                return PromptRunResult(
                    "DENIED",
                    agent_response,
                    _with_evidence(
                        evidence,
                        decision="DENIED",
                        denial_reason=reason,
                    ),
                )
            return PromptRunResult(
                "ERROR",
                agent_response,
                _with_evidence(evidence, denial_reason=str(exc) or "commercegov_proposal_failed"),
            )
        policy_allowed = created.policy_status == "pass"
        denial = None if policy_allowed else (created.violations[0] if created.violations else "policy_denied")
        return PromptRunResult(
            "SUCCESS" if policy_allowed else "DENIED",
            agent_response,
            _with_evidence(
                evidence,
                policy_result="ALLOWED" if policy_allowed else "DENIED",
                proposal_id=created.proposal_id,
                denial_reason=denial,
            ),
        )


def _idempotency_key(run_id: str) -> str:
    token = str(run_id or "").strip() or str(uuid4())
    if len(token) < 8:
        token = (token + "-prompt")[:8].ljust(8, "x")
    return token[:128]


def _with_evidence(base: dict[str, str], **fields: str | None) -> dict[str, str]:
    out = dict(base)
    for key, value in fields.items():
        text = str(value).strip() if value is not None else ""
        if text:
            out[key] = text
    return out
