"""Typed contracts for the local P0 authority-processing spine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, runtime_checkable

INTERNAL_SCHEMA_VERSION = "commercegov.authority-event.v1"
WIRE_SCHEMA_VERSION = "commercegov.operational-event.v1"
EXTERNAL_CHANGE_EVENT = "EXTERNAL_PRODUCTION_CHANGE_DETECTED"
SUPPORTED_MUTATION_CLASSES = frozenset(
    {
        "product.title",
        "product.description",
        "product.meta_title",
        "product.meta_description",
    }
)


class ContractError(ValueError):
    """A request cannot be safely represented by the P0 contract."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class TenantBindingError(PermissionError):
    """The event tenant is not explicitly allowed."""

    def __init__(self, code: str = "tenant_binding_denied") -> None:
        super().__init__(code)
        self.code = code


class IdempotencyError(RuntimeError):
    """Base class for fail-closed idempotency errors."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ConflictingDuplicateError(IdempotencyError):
    pass


class EventIdentityConflictError(IdempotencyError):
    pass


class EventInProgressError(IdempotencyError):
    pass


@dataclass(frozen=True, slots=True)
class AuthorityEvent:
    schema_version: str
    event_id: str
    change_id: str | None
    source: str
    event_type: str
    observed_at: str | None
    source_event_id: str | None
    agency_id: str
    shop_id: str
    target_type: str
    target_id: str
    mutation_class: str
    scope_key: str
    observed_value: Any
    expected_governed_value: Any
    decision_version_id: str | None
    audit_id: int | None
    review_cycle_id: str | None
    authority_mode: str
    human_approval_required: bool
    authority_origin: str


@dataclass(frozen=True, slots=True)
class SemanticAssessment:
    classification: str
    summary: str
    recommended_operator_action: str
    confidence: float | None = None


@runtime_checkable
class SemanticProvider(Protocol):
    """Produces semantic advice only; it has no executable authority."""

    def assess(self, event: AuthorityEvent) -> Mapping[str, Any] | SemanticAssessment | None:
        ...


@dataclass(frozen=True, slots=True)
class AuthorityResult:
    event: AuthorityEvent
    classification: str
    summary: str
    reason: str
    recommended_operator_action: str
    authority_mode: str
    human_authority_required: bool
    autonomous_processing: str
    terminal_status: str
    semantic_status: str


@dataclass(frozen=True, slots=True)
class HandlerResponse:
    status_code: int
    body: dict[str, Any]
    cached: bool = False
