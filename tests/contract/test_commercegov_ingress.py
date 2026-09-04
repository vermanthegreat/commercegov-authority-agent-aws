from __future__ import annotations

import copy

import pytest

from authority_agent.contracts import ContractError, INTERNAL_SCHEMA_VERSION
from authority_agent.normalization import normalize_commercegov_event


def test_real_unversioned_commercegov_shape_normalizes(canonical_payload) -> None:
    assert "scope_key" not in canonical_payload
    assert canonical_payload["policy_context"]["scope_key"]
    event = normalize_commercegov_event(canonical_payload)
    assert event.schema_version == INTERNAL_SCHEMA_VERSION
    assert event.event_id == event.change_id == "42"
    assert event.agency_id == "demo-agency"
    assert event.shop_id == "demo-shop.myshopify.com"
    assert event.target_type == "product"
    assert event.target_id == "7001"
    assert event.mutation_class == "product.title"
    assert event.scope_key == "demo-scope-product-7001-title"
    assert event.observed_value == "Externally changed demo title"
    assert event.expected_governed_value == "Approved governed demo title"
    assert event.authority_mode == "PROPOSE_ONLY"
    assert event.human_approval_required is True


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        (lambda p: p.update(schema_version="unknown.v99"), "unsupported_schema_version"),
        (lambda p: p.update(target_type="variant"), "unsupported_target_type"),
        (lambda p: p.update(mutation_class="product.handle"), "unsupported_mutation_class"),
        (lambda p: p.update(change_id="other"), "external_change_identity_mismatch"),
        (
            lambda p: p["authority_context"].update(authority_mode="AUTO_APPROVE"),
            "contradictory_authority_metadata",
        ),
        (
            lambda p: p["authority_context"].update(requires_human_approval=False),
            "contradictory_authority_metadata",
        ),
    ],
)
def test_invalid_or_contradictory_ingress_fails_closed(
    canonical_payload, mutation, error
) -> None:
    payload = copy.deepcopy(canonical_payload)
    mutation(payload)
    with pytest.raises(ContractError, match=error):
        normalize_commercegov_event(payload)


def test_missing_scope_key_is_not_invented(canonical_payload) -> None:
    payload = copy.deepcopy(canonical_payload)
    del payload["policy_context"]["scope_key"]
    with pytest.raises(ContractError, match="invalid_scope_key"):
        normalize_commercegov_event(payload)

