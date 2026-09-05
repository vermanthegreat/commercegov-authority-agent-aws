"""Local orchestration, explicit tenant binding, and replaceable idempotency."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from threading import RLock
from typing import Any, Iterable, Mapping, Protocol

from authority_agent.contracts import (
    AuthorityEvent,
    ConflictingDuplicateError,
    EventIdentityConflictError,
    EventInProgressError,
    HandlerResponse,
    SemanticProvider,
    TenantBindingError,
)
from authority_agent.deterministic_control import enforce_authority_boundary
from authority_agent.normalization import canonical_shop_domain, normalize_commercegov_event
from authority_agent.response_adapter import to_commercegov_response


class TenantBindingRegistry:
    """Explicit P0 allowlist of exact agency/shop pairs."""

    def __init__(self, bindings: Iterable[tuple[str, str]]) -> None:
        self._bindings = frozenset(
            (str(agency), canonical_shop_domain(shop)) for agency, shop in bindings
        )

    def require(self, event: AuthorityEvent) -> None:
        if (event.agency_id, event.shop_id) not in self._bindings:
            raise TenantBindingError()


@dataclass(slots=True)
class ClaimResult:
    cached_response: dict[str, Any] | None = None
    execution_id: str | None = None
    evidence_id: str | None = None


class IdempotencyLedger(Protocol):
    def claim(self, event: AuthorityEvent, request_hash: str) -> ClaimResult:
        ...

    def complete(
        self,
        event: AuthorityEvent,
        request_hash: str,
        response: Mapping[str, Any],
        evidence: Mapping[str, Any] | None = None,
    ) -> None:
        ...


@dataclass(slots=True)
class _LedgerEntry:
    identity: tuple[str, str, str]
    request_hash: str
    state: str
    response: dict[str, Any] | None = None


class InMemoryIdempotencyLedger:
    """Thread-safe P0 ledger keyed globally by event ID."""

    def __init__(self) -> None:
        self._entries: dict[str, _LedgerEntry] = {}
        self._lock = RLock()

    def claim(self, event: AuthorityEvent, request_hash: str) -> ClaimResult:
        identity = (event.agency_id, event.shop_id, event.event_id)
        with self._lock:
            existing = self._entries.get(event.event_id)
            if existing is None:
                self._entries[event.event_id] = _LedgerEntry(
                    identity=identity, request_hash=request_hash, state="PROCESSING"
                )
                return ClaimResult()
            if existing.identity != identity:
                raise EventIdentityConflictError("event_tenant_identity_conflict")
            if existing.request_hash != request_hash:
                raise ConflictingDuplicateError("conflicting_duplicate")
            if existing.state == "COMPLETE" and existing.response is not None:
                return ClaimResult(cached_response=dict(existing.response))
            raise EventInProgressError("event_processing_in_progress")

    def complete(
        self,
        event: AuthorityEvent,
        request_hash: str,
        response: Mapping[str, Any],
        evidence: Mapping[str, Any] | None = None,
    ) -> None:
        identity = (event.agency_id, event.shop_id, event.event_id)
        with self._lock:
            existing = self._entries.get(event.event_id)
            if (
                existing is None
                or existing.identity != identity
                or existing.request_hash != request_hash
            ):
                raise EventIdentityConflictError("idempotency_completion_conflict")
            existing.state = "COMPLETE"
            existing.response = dict(response)


def canonical_request_hash(event: AuthorityEvent) -> str:
    serialized = json.dumps(
        asdict(event), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return sha256(serialized).hexdigest()


class StaticSemanticProvider:
    """Configurable local provider used by the CLI and hostile-output tests."""

    def __init__(self, output: Any = None, *, error: Exception | None = None) -> None:
        self.output = output
        self.error = error
        self.calls = 0

    def assess(self, event: AuthorityEvent) -> Any:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.output


class AuthorityProcessor:
    def __init__(
        self,
        *,
        bindings: TenantBindingRegistry,
        ledger: IdempotencyLedger,
        semantic_provider: SemanticProvider,
    ) -> None:
        self.bindings = bindings
        self.ledger = ledger
        self.semantic_provider = semantic_provider

    def process(self, payload: Mapping[str, Any]) -> HandlerResponse:
        event = normalize_commercegov_event(payload)
        self.bindings.require(event)
        request_hash = canonical_request_hash(event)
        claim = self.ledger.claim(event, request_hash)
        if claim.cached_response is not None:
            return HandlerResponse(200, claim.cached_response, cached=True)

        try:
            semantic_output = self.semantic_provider.assess(event)
            semantic_status = "valid"
        except Exception:
            semantic_output = None
            semantic_status = "provider_error"

        result = enforce_authority_boundary(
            event, semantic_output, semantic_status=semantic_status
        )
        response = to_commercegov_response(result)
        if isinstance(semantic_output, Mapping):
            semantic_classification = semantic_output.get("classification")
            semantic_summary = semantic_output.get("summary")
        else:
            semantic_classification = getattr(semantic_output, "classification", None)
            semantic_summary = getattr(semantic_output, "summary", None)
        evidence = {
            "semantic_provider": getattr(
                self.semantic_provider,
                "provider_name",
                type(self.semantic_provider).__name__,
            ),
            "semantic_model": getattr(self.semantic_provider, "model_id", None),
            "semantic_status": semantic_status,
            "semantic_classification": semantic_classification,
            "semantic_summary": semantic_summary,
            "deterministic_classification": result.classification,
            "authority_mode": result.authority_mode,
            "human_authority_required": result.human_authority_required,
            "autonomous_processing": result.autonomous_processing,
            "terminal_status": result.terminal_status,
        }
        if semantic_status != "valid":
            evidence["error_category"] = "semantic_provider_error"
        extra = getattr(self.semantic_provider, "context_evidence", None)
        if isinstance(extra, Mapping):
            for key, value in extra.items():
                lowered = str(key).lower()
                if value is None or any(part in lowered for part in ("token", "secret", "authorization", "bearer", "password")):
                    continue
                evidence[key] = value
        self.ledger.complete(event, request_hash, response, evidence)
        return HandlerResponse(200, response)
