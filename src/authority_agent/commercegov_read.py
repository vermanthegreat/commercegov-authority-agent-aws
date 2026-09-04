"""Strictly read-only CommerceGov integration client for bounded P1 context."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from authority_agent.contracts import AuthorityEvent


class CommerceGovReadError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class CommerceGovReadTransport(Protocol):
    def get_json(self, path: str) -> Mapping[str, Any]:
        ...


class HttpxCommerceGovReadTransport:
    """Fixed-origin GET-only transport; it exposes no arbitrary method to the agent."""

    def __init__(self, *, base_url: str, bearer_token: str, timeout_seconds: float = 5.0) -> None:
        base = str(base_url or "").strip().rstrip("/")
        token = str(bearer_token or "").strip()
        if not base.startswith("https://") or not token:
            raise ValueError("invalid_commercegov_read_configuration")
        self._base_url = base
        self._token = token
        self._timeout = timeout_seconds

    def get_json(self, path: str) -> Mapping[str, Any]:
        if not path.startswith("/api/integration/v1/") or ".." in path:
            raise CommerceGovReadError("unapproved_commercegov_read_path")
        try:
            response = httpx.get(
                f"{self._base_url}{path}",
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=self._timeout,
                follow_redirects=False,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise CommerceGovReadError("commercegov_read_failed") from exc
        if not isinstance(payload, Mapping):
            raise CommerceGovReadError("commercegov_read_invalid_json")
        return payload


class _ProductContent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    title: str = Field(max_length=4096)
    description: str = Field(max_length=196_608)
    meta_title: str = Field(max_length=4096)
    meta_description: str = Field(max_length=4096)


class _ProductResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    shop_id: str
    product_id: str
    field_registry: str
    stage: str
    content: _ProductContent
    audit_id: str | None = None
    updated_at: str


class _MaxLength(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    title: int
    description: int
    meta_title: int
    meta_description: int


class _SeoConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    keyword_coverage: str


class _PolicyRules(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    brand_tone: str
    forbidden_terms: list[str]
    max_length: _MaxLength
    seo_constraints: _SeoConstraints
    proposal_instructions: str


class _PolicyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    shop_id: str
    schema_version: str
    effective_policy_hash: str
    controlled_fields: list[str]
    rules: _PolicyRules


@dataclass(frozen=True, slots=True)
class GovernanceSnapshot:
    agency_id: str
    shop_id: str
    target_type: str
    target_id: str
    mutation_class: str
    workflow_stage: str
    audit_id: str | None
    updated_at: str
    observed_field_value: str


@dataclass(frozen=True, slots=True)
class EffectivePolicySnapshot:
    agency_id: str
    shop_id: str
    mutation_class: str
    effective_policy_hash: str
    controlled: bool
    brand_tone: str
    forbidden_terms: tuple[str, ...]
    max_length: int
    keyword_coverage: str
    proposal_instructions: str


_MUTATION_TO_FIELD = {
    "product.title": "title",
    "product.description": "description",
    "product.meta_title": "meta_title",
    "product.meta_description": "meta_description",
}


class CommerceGovReadClient:
    """Calls only audited CommerceGov GET endpoints and validates response identity."""

    def __init__(self, transport: CommerceGovReadTransport) -> None:
        self._transport = transport

    def get_governance_snapshot(self, event: AuthorityEvent) -> GovernanceSnapshot:
        shop = quote(event.shop_id, safe="")
        product = quote(event.target_id, safe="")
        payload = self._transport.get_json(
            f"/api/integration/v1/shops/{shop}/products/{product}/content"
        )
        try:
            parsed = _ProductResponse.model_validate(payload)
        except ValidationError as exc:
            raise CommerceGovReadError("invalid_product_context_response") from exc
        if parsed.shop_id != event.shop_id or parsed.product_id != event.target_id:
            raise CommerceGovReadError("product_context_identity_mismatch")
        field = _MUTATION_TO_FIELD[event.mutation_class]
        return GovernanceSnapshot(
            agency_id=event.agency_id,
            shop_id=event.shop_id,
            target_type=event.target_type,
            target_id=event.target_id,
            mutation_class=event.mutation_class,
            workflow_stage=parsed.stage,
            audit_id=parsed.audit_id,
            updated_at=parsed.updated_at,
            observed_field_value=getattr(parsed.content, field),
        )

    def get_effective_policy(self, event: AuthorityEvent) -> EffectivePolicySnapshot:
        shop = quote(event.shop_id, safe="")
        payload = self._transport.get_json(
            f"/api/integration/v1/shops/{shop}/policy"
        )
        try:
            parsed = _PolicyResponse.model_validate(payload)
        except ValidationError as exc:
            raise CommerceGovReadError("invalid_policy_context_response") from exc
        if parsed.shop_id != event.shop_id:
            raise CommerceGovReadError("policy_context_identity_mismatch")
        field = _MUTATION_TO_FIELD[event.mutation_class]
        return EffectivePolicySnapshot(
            agency_id=event.agency_id,
            shop_id=event.shop_id,
            mutation_class=event.mutation_class,
            effective_policy_hash=parsed.effective_policy_hash,
            controlled=field in parsed.controlled_fields,
            brand_tone=parsed.rules.brand_tone,
            forbidden_terms=tuple(parsed.rules.forbidden_terms),
            max_length=getattr(parsed.rules.max_length, field),
            keyword_coverage=parsed.rules.seo_constraints.keyword_coverage,
            proposal_instructions=parsed.rules.proposal_instructions,
        )

