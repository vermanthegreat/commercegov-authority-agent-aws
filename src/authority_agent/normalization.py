"""Strict normalization of the audited CommerceGov operational wire contract."""

from __future__ import annotations

from datetime import datetime
import re
from typing import Any, Mapping

from authority_agent.contracts import (
    AuthorityEvent,
    ContractError,
    EXTERNAL_CHANGE_EVENT,
    INTERNAL_SCHEMA_VERSION,
    SUPPORTED_MUTATION_CLASSES,
    WIRE_SCHEMA_VERSION,
)

_SHOP_RE = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.myshopify\.com$"
)
_TOP_LEVEL_FIELDS = frozenset(
    {
        "schema_version",
        "event_id",
        "change_id",
        "agency_id",
        "shop_id",
        "target_type",
        "target_id",
        "mutation_class",
        "current_value",
        "proposed_value",
        "policy_context",
        "authority_context",
    }
)
_POLICY_FIELDS = frozenset(
    {
        "source",
        "event_type",
        "external_change_id",
        "scope_key",
        "shopify_webhook_id",
        "detected_at",
        "governed_field",
        "decision_version_id",
        "audit_id",
        "review_cycle_id",
        "expected_governed_value",
        "observed_shopify_value",
    }
)
_AUTHORITY_FIELDS = frozenset(
    {"requires_human_approval", "authority_mode", "origin"}
)


def _mapping(value: Any, code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError(code)
    return value


def _strict_fields(value: Mapping[str, Any], allowed: frozenset[str], code: str) -> None:
    if set(value) - allowed:
        raise ContractError(code)


def _required_token(value: Any, field: str, *, max_length: int = 512) -> str:
    if not isinstance(value, str):
        raise ContractError(f"invalid_{field}")
    if not value or value != value.strip() or len(value) > max_length:
        raise ContractError(f"invalid_{field}")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise ContractError(f"invalid_{field}")
    return value


def canonical_shop_domain(value: Any) -> str:
    raw = _required_token(value, "shop_id", max_length=253)
    canonical = raw.lower()
    if "://" in canonical or not _SHOP_RE.fullmatch(canonical):
        raise ContractError("invalid_shop_id")
    return canonical


def _optional_token(value: Any, field: str, *, max_length: int = 512) -> str | None:
    if value is None:
        return None
    return _required_token(value, field, max_length=max_length)


def _observed_at(value: Any) -> str | None:
    token = _optional_token(value, "observed_at", max_length=64)
    if token is None:
        return None
    try:
        parsed = datetime.fromisoformat(token.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError("invalid_observed_at") from exc
    if parsed.tzinfo is None:
        raise ContractError("invalid_observed_at")
    return token


def _audit_id(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ContractError("invalid_audit_id")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ContractError("invalid_audit_id") from exc
    if parsed <= 0 or str(parsed) != str(value):
        raise ContractError("invalid_audit_id")
    return parsed


def normalize_commercegov_event(payload: Mapping[str, Any]) -> AuthorityEvent:
    """Normalize only the current audited wire payload and its explicit v1 form."""

    wire = _mapping(payload, "malformed_event")
    _strict_fields(wire, _TOP_LEVEL_FIELDS, "unsupported_ingress_field")
    explicit_version = wire.get("schema_version")
    if explicit_version is not None and explicit_version != WIRE_SCHEMA_VERSION:
        raise ContractError("unsupported_schema_version")

    policy = _mapping(wire.get("policy_context"), "invalid_policy_context")
    authority = _mapping(wire.get("authority_context"), "invalid_authority_context")
    _strict_fields(policy, _POLICY_FIELDS, "unsupported_policy_context_field")
    _strict_fields(authority, _AUTHORITY_FIELDS, "unsupported_authority_context_field")

    event_id = _required_token(wire.get("event_id"), "event_id", max_length=128)
    change_id = _optional_token(wire.get("change_id"), "change_id", max_length=128)
    if change_id is None or change_id != event_id:
        raise ContractError("external_change_identity_mismatch")
    external_change_id = _required_token(
        policy.get("external_change_id"), "external_change_id", max_length=128
    )
    if external_change_id != event_id:
        raise ContractError("external_change_identity_mismatch")

    event_type = _required_token(policy.get("event_type"), "event_type", max_length=96)
    if event_type != EXTERNAL_CHANGE_EVENT:
        raise ContractError("unsupported_event_type")
    target_type = _required_token(wire.get("target_type"), "target_type", max_length=32)
    if target_type != "product":
        raise ContractError("unsupported_target_type")
    mutation_class = _required_token(
        wire.get("mutation_class"), "mutation_class", max_length=64
    )
    if mutation_class not in SUPPORTED_MUTATION_CLASSES:
        raise ContractError("unsupported_mutation_class")

    authority_mode = _required_token(
        authority.get("authority_mode"), "authority_mode", max_length=32
    )
    requires_human = authority.get("requires_human_approval")
    origin = _required_token(authority.get("origin"), "authority_origin", max_length=64)
    if (
        authority_mode != "PROPOSE_ONLY"
        or requires_human is not True
        or origin != "external_production_change"
    ):
        raise ContractError("contradictory_authority_metadata")

    current_value = wire.get("current_value")
    observed_value = policy.get("observed_shopify_value")
    if observed_value is not None and current_value is not None and observed_value != current_value:
        raise ContractError("observed_value_mismatch")
    proposed_value = wire.get("proposed_value")
    governed_value = policy.get("expected_governed_value")
    if governed_value is not None and proposed_value is not None and governed_value != proposed_value:
        raise ContractError("governed_value_mismatch")

    source = _required_token(policy.get("source"), "source", max_length=64)
    if source != "shopify_webhook":
        raise ContractError("unsupported_event_source")

    return AuthorityEvent(
        schema_version=INTERNAL_SCHEMA_VERSION,
        event_id=event_id,
        change_id=change_id,
        source=source,
        event_type=event_type,
        observed_at=_observed_at(policy.get("detected_at")),
        source_event_id=_optional_token(
            policy.get("shopify_webhook_id"), "source_event_id", max_length=256
        ),
        agency_id=_required_token(wire.get("agency_id"), "agency_id", max_length=128),
        shop_id=canonical_shop_domain(wire.get("shop_id")),
        target_type=target_type,
        target_id=_required_token(wire.get("target_id"), "target_id", max_length=256),
        mutation_class=mutation_class,
        scope_key=_required_token(policy.get("scope_key"), "scope_key", max_length=512),
        observed_value=observed_value if observed_value is not None else current_value,
        expected_governed_value=(
            governed_value if governed_value is not None else proposed_value
        ),
        decision_version_id=_optional_token(
            policy.get("decision_version_id"), "decision_version_id", max_length=256
        ),
        audit_id=_audit_id(policy.get("audit_id")),
        review_cycle_id=_optional_token(
            policy.get("review_cycle_id"), "review_cycle_id", max_length=256
        ),
        authority_mode=authority_mode,
        human_approval_required=True,
        authority_origin=origin,
    )

