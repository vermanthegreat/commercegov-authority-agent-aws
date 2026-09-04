from __future__ import annotations

import json

import pytest

from authority_agent.contracts import TenantBindingError
from authority_agent.semantic_context import ReadOnlyToolRegistry
from tests.p1_helpers import p1_parts


def test_context_is_minimized_and_contains_no_transport_credentials(canonical_payload) -> None:
    event, _transport, builder = p1_parts(canonical_payload)
    context, _governance, _policy = builder.build(event)
    rendered = context.model_dump(mode="json")
    assert set(rendered) == {
        "event_id", "event_type", "agency_id", "shop_id", "mutation_class",
        "target", "observed_value", "expected_governed_value", "workflow_stage",
        "policy", "history", "authority_mode", "human_approval_required",
    }
    serialized = json.dumps(rendered).lower()
    assert all(token not in serialized for token in ("bearer", "token", "secret", "oauth", "password"))


def test_tool_registry_is_exactly_two_cached_read_only_tools(canonical_payload) -> None:
    event, _transport, builder = p1_parts(canonical_payload)
    _context, governance, policy = builder.build(event)
    registry = ReadOnlyToolRegistry(event, governance, policy)
    tools = registry.as_strands_tools()
    assert ReadOnlyToolRegistry.TOOL_NAMES == ("get_governance_context", "get_effective_policy")
    assert {tool.tool_name for tool in tools} == set(ReadOnlyToolRegistry.TOOL_NAMES)
    assert not any(word in name for name in ReadOnlyToolRegistry.TOOL_NAMES for word in ("write", "apply", "approve", "mutate"))


@pytest.mark.parametrize(
    "change",
    [
        {"agency_id": "other-agency"},
        {"shop_id": "other.myshopify.com"},
        {"target_type": "order"},
        {"target_id": "9999"},
    ],
)
def test_tools_deny_cross_tenant_or_cross_target_queries(canonical_payload, change) -> None:
    event, _transport, builder = p1_parts(canonical_payload)
    _context, governance, policy = builder.build(event)
    registry = ReadOnlyToolRegistry(event, governance, policy)
    identity = {
        "agency_id": event.agency_id,
        "shop_id": event.shop_id,
        "target_type": event.target_type,
        "target_id": event.target_id,
    } | change
    with pytest.raises(TenantBindingError, match="tool_identity_mismatch"):
        registry.governance_context(**identity)


def test_tool_results_retain_bound_identity(canonical_payload) -> None:
    event, _transport, builder = p1_parts(canonical_payload)
    _context, governance, policy = builder.build(event)
    registry = ReadOnlyToolRegistry(event, governance, policy)
    identity = {
        "agency_id": event.agency_id,
        "shop_id": event.shop_id,
        "target_type": event.target_type,
        "target_id": event.target_id,
    }
    assert registry.governance_context(**identity)["target_id"] == event.target_id
    assert registry.effective_policy(**identity)["shop_id"] == event.shop_id
