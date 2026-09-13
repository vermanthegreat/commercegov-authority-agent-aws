"""Bounded CommerceGov proposal write and product lookup. No generic HTTP."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping, Protocol
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from authority_agent.commercegov_read import (
    CommerceGovReadClient,
    CommerceGovReadError,
    CommerceGovTokenExpiredError,
    EffectivePolicySnapshot,
)
from authority_agent.scenario_identity import CANONICAL_SHOP, pinned_product_id

PROPOSAL_PATH_RE = re.compile(
    r"^/api/integration/v1/shops/[^/]+/products/[^/]+/proposals$"
)
PRODUCT_LIST_PATH_RE = re.compile(
    r"^/api/integration/v1/shops/[^/]+/products(?:\?.*)?$"
)


# Public integration list `stage` values. Early filter only — POST remains admission.
_PROPOSAL_CANDIDATE_STAGES = frozenset({"active", "review", "applied"})
_NON_GOVERNABLE_LIST_STAGES = frozenset(
    {"approved", "approve", "archived", "inactive", "rejected"}
)
_DOMAIN_ERROR_CODES = frozenset(
    {
        "product_not_governable",
        "invalid_proposal",
        "invalid_controlled_field",
        "validation_failed",
        "idempotency_conflict",
        "insufficient_scope",
        "authorization_denied",
        "product_not_found",
        "shop_not_found",
        "concurrent_modification",
        "invalid_shop_id",
        "invalid_product_id",
        "request_too_large",
        "authentication_required",
        "invalid_token",
    }
)
_SAFE_ERROR_MESSAGE_LIMIT = 200
PRODUCT_NOT_GOVERNABLE = "PRODUCT_NOT_GOVERNABLE"
TARGET_NOT_FOUND = "TARGET_NOT_FOUND"
TARGET_AMBIGUOUS = "TARGET_AMBIGUOUS"


class CommerceGovProposalError(RuntimeError):
    def __init__(
        self,
        code: str,
        *,
        http_status: int | None = None,
        message: str = "",
        retryable: bool = False,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.http_status = http_status
        self.safe_message = str(message or "").strip()[:_SAFE_ERROR_MESSAGE_LIMIT]
        self.retryable = bool(retryable)


class ProductResolutionError(Exception):
    """Exact-title discovery failed closed. No proposal may be created."""

    def __init__(self, code: str, *, query: str = "") -> None:
        super().__init__(code)
        self.code = code
        self.query = str(query or "").strip()


def list_stage_blocks_new_proposal(stage: str) -> bool:
    """True when list `stage` is a known non-governable public stage."""
    return str(stage or "").strip().lower() in _NON_GOVERNABLE_LIST_STAGES


def list_stage_is_proposal_candidate(stage: str) -> bool:
    """True when list `stage` matches CommerceGov-admissible public stages."""
    return str(stage or "").strip().lower() in _PROPOSAL_CANDIDATE_STAGES


def display_governance_state(stage: str) -> str:
    token = str(stage or "").strip().lower()
    if token == "approve":
        token = "approved"
    return token.upper() if token else ""


def domain_denial_reason(code: str) -> str | None:
    token = str(code or "").strip()
    if token == "product_not_governable":
        return PRODUCT_NOT_GOVERNABLE
    if token in _DOMAIN_ERROR_CODES:
        return token
    return None


class CommerceGovProposalTransport(Protocol):
    def post_json(self, path: str, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        ...


class _ProductSummary(BaseModel):
    model_config = ConfigDict(extra="ignore")

    product_id: str
    title: str
    stage: str = ""
    updated_at: str = ""


class _ProductListResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    shop_id: str
    products: list[_ProductSummary] = Field(default_factory=list)
    limit: int
    offset: int
    has_more: bool
    stage: str | None = None


class _PolicyResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    status: str
    violations: list[str] = Field(default_factory=list)


class _ProposalResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    shop_id: str
    product_id: str
    proposal_id: str
    policy_result: _PolicyResult


@dataclass(frozen=True, slots=True)
class ProductRef:
    product_id: str
    title: str
    stage: str = ""


@dataclass(frozen=True, slots=True)
class ProposalCreateResult:
    proposal_id: str
    policy_status: str
    violations: tuple[str, ...]
    product_id: str


class HttpxCommerceGovProposalTransport:
    """HTTPS POST locked to the CommerceGov proposal path only."""

    def __init__(self, *, base_url: str, bearer_token: str, timeout_seconds: float = 5.0) -> None:
        base = str(base_url or "").strip().rstrip("/")
        token = str(bearer_token or "").strip()
        if not base.startswith("https://") or not token:
            raise ValueError("invalid_commercegov_proposal_configuration")
        self._base_url = base
        self._token = token
        self._timeout = timeout_seconds

    def post_json(self, path: str, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        if ".." in path or not PROPOSAL_PATH_RE.fullmatch(path):
            raise CommerceGovProposalError("unapproved_commercegov_proposal_path")
        try:
            response = httpx.post(
                f"{self._base_url}{path}",
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "content-type": "application/json",
                },
                json=dict(payload),
                timeout=self._timeout,
                follow_redirects=False,
            )
            if response.status_code == 401:
                error_payload = _safe_json_mapping(response)
                error_detail = error_payload.get("error") if error_payload is not None else None
                if isinstance(error_detail, Mapping) and error_detail.get("code") == "token_expired":
                    raise CommerceGovTokenExpiredError()
            if response.status_code >= 400:
                raise _proposal_error_from_response(response)
            body = response.json()
        except CommerceGovTokenExpiredError:
            raise
        except CommerceGovProposalError:
            raise
        except (httpx.HTTPError, ValueError):
            raise CommerceGovProposalError("commercegov_proposal_failed") from None
        if not isinstance(body, Mapping):
            raise CommerceGovProposalError("commercegov_proposal_invalid_json")
        return body


class LazyHttpsCommerceGovProposalTransport:
    def __init__(
        self,
        *,
        base_url: str,
        credential_manager: Any,
        timeout_seconds: float = 5.0,
    ) -> None:
        self._base_url = base_url
        self._credential_manager = credential_manager
        self._timeout_seconds = timeout_seconds

    def _transport_for(self, token: str) -> HttpxCommerceGovProposalTransport:
        return HttpxCommerceGovProposalTransport(
            base_url=self._base_url,
            bearer_token=token,
            timeout_seconds=self._timeout_seconds,
        )

    def post_json(self, path: str, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        token = self._credential_manager.access_token()
        try:
            return self._transport_for(token).post_json(path, payload)
        except CommerceGovTokenExpiredError:
            try:
                refreshed = self._credential_manager.refresh_after_token_expired(token)
            except Exception:
                raise CommerceGovProposalError("commercegov_proposal_failed") from None
            return self._transport_for(refreshed).post_json(path, payload)


class CommerceGovHostAdapter:
    """Deterministic host adapter: lookup + proposal POST. Never approve/apply."""

    def __init__(
        self,
        *,
        read_client: CommerceGovReadClient,
        proposal_transport: CommerceGovProposalTransport,
        agency_id: str,
    ) -> None:
        self._read = read_client
        self._proposals = proposal_transport
        self._agency_id = agency_id

    def shop_policy(self, shop_id: str) -> dict[str, Any]:
        if str(shop_id or "").strip() != CANONICAL_SHOP:
            raise CommerceGovReadError("scenario_shop_mismatch")
        try:
            policy = self._read.get_title_policy(agency_id=self._agency_id, shop_id=shop_id)
        except CommerceGovReadError:
            return {}
        return _policy_context(policy)

    def find_product(self, shop_id: str, query: str) -> ProductRef | None:
        if str(shop_id or "").strip() != CANONICAL_SHOP:
            raise CommerceGovReadError("scenario_shop_mismatch")
        needle = str(query or "").strip()
        if not needle:
            raise ProductResolutionError(TARGET_NOT_FOUND, query=query)
        payload = self._read.list_products(shop_id)
        try:
            parsed = _ProductListResponse.model_validate(payload)
        except ValidationError as exc:
            raise CommerceGovReadError("invalid_product_list_response") from exc
        if parsed.shop_id != shop_id:
            raise CommerceGovReadError("product_list_identity_mismatch")
        exact_eligible = [
            item
            for item in parsed.products
            if item.title.casefold() == needle.casefold()
            and list_stage_is_proposal_candidate(item.stage)
        ]
        pinned = pinned_product_id(needle)
        if pinned:
            pinned_matches = [
                item
                for item in exact_eligible
                if str(item.product_id).rsplit("/", 1)[-1] == pinned
            ]
            if len(pinned_matches) == 1:
                return _product_ref(pinned_matches[0])
            raise ProductResolutionError(TARGET_NOT_FOUND, query=query)
        if len(exact_eligible) == 1:
            return _product_ref(exact_eligible[0])
        if len(exact_eligible) > 1:
            raise ProductResolutionError(TARGET_AMBIGUOUS, query=query)
        raise ProductResolutionError(TARGET_NOT_FOUND, query=query)

    def create_title_proposal(
        self,
        *,
        shop_id: str,
        product_id: str,
        title: str,
        idempotency_key: str,
    ) -> ProposalCreateResult:
        if str(shop_id or "").strip() != CANONICAL_SHOP:
            raise CommerceGovProposalError("scenario_shop_mismatch")
        shop = quote(shop_id, safe="")
        product = quote(product_id, safe="")
        path = f"/api/integration/v1/shops/{shop}/products/{product}/proposals"
        payload = {
            "changes": {"title": title},
            "idempotency_key": idempotency_key,
        }
        body = self._proposals.post_json(path, payload)
        try:
            parsed = _ProposalResponse.model_validate(body)
        except ValidationError as exc:
            raise CommerceGovProposalError("invalid_proposal_response") from exc
        if parsed.shop_id != shop_id or parsed.product_id != product_id:
            raise CommerceGovProposalError("proposal_identity_mismatch")
        status = str(parsed.policy_result.status or "").strip().lower()
        return ProposalCreateResult(
            proposal_id=str(parsed.proposal_id),
            policy_status=status,
            violations=tuple(parsed.policy_result.violations),
            product_id=parsed.product_id,
        )


def _product_ref(item: _ProductSummary) -> ProductRef:
    return ProductRef(
        product_id=item.product_id,
        title=item.title,
        stage=str(item.stage or "").strip().lower(),
    )


def _safe_json_mapping(response: httpx.Response) -> Mapping[str, Any] | None:
    try:
        payload = response.json()
    except ValueError:
        return None
    return payload if isinstance(payload, Mapping) else None


def _proposal_error_from_response(response: httpx.Response) -> CommerceGovProposalError:
    status = int(response.status_code)
    if status >= 500:
        return CommerceGovProposalError("commercegov_proposal_failed", http_status=status)
    payload = _safe_json_mapping(response)
    detail = payload.get("error") if payload is not None else None
    code = ""
    message = ""
    retryable = False
    if isinstance(detail, Mapping):
        code = str(detail.get("code") or "").strip()
        raw_message = detail.get("message")
        if isinstance(raw_message, str):
            message = raw_message.strip()[:_SAFE_ERROR_MESSAGE_LIMIT]
        retryable = bool(detail.get("retryable"))
    if code in _DOMAIN_ERROR_CODES:
        return CommerceGovProposalError(
            code,
            http_status=status,
            message=message,
            retryable=retryable,
        )
    return CommerceGovProposalError("commercegov_proposal_failed", http_status=status)


def _policy_context(policy: EffectivePolicySnapshot) -> dict[str, Any]:
    return {
        "effective_policy_hash": policy.effective_policy_hash,
        "forbidden_terms": list(policy.forbidden_terms),
        "max_length": policy.max_length,
        "brand_tone": policy.brand_tone,
        "controlled": policy.controlled,
        "proposal_instructions": policy.proposal_instructions,
    }
