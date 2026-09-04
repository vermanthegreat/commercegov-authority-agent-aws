from __future__ import annotations

import copy

import pytest

from authority_agent.contracts import ContractError, TenantBindingError
from authority_agent.normalization import normalize_commercegov_event
from authority_agent.orchestration import TenantBindingRegistry


def test_exact_tenant_binding_is_allowed(canonical_payload) -> None:
    event = normalize_commercegov_event(canonical_payload)
    TenantBindingRegistry(
        [("demo-agency", "demo-shop.myshopify.com")]
    ).require(event)


@pytest.mark.parametrize(
    ("agency", "shop"),
    [
        ("unknown-agency", "demo-shop.myshopify.com"),
        ("demo-agency", "unknown-shop.myshopify.com"),
        ("wrong-agency", "demo-shop.myshopify.com"),
    ],
)
def test_unknown_or_cross_agency_binding_is_rejected(
    canonical_payload, agency, shop
) -> None:
    event = normalize_commercegov_event(canonical_payload)
    registry = TenantBindingRegistry([(agency, shop)])
    with pytest.raises(TenantBindingError):
        registry.require(event)


def test_shop_domain_is_canonicalized(canonical_payload) -> None:
    payload = copy.deepcopy(canonical_payload)
    payload["shop_id"] = "DEMO-SHOP.MYSHOPIFY.COM"
    assert normalize_commercegov_event(payload).shop_id == "demo-shop.myshopify.com"


@pytest.mark.parametrize(
    "shop",
    ["not-a-domain", "https://demo-shop.myshopify.com", "x/myshopify.com", ".myshopify.com"],
)
def test_malformed_shop_is_rejected(canonical_payload, shop) -> None:
    payload = copy.deepcopy(canonical_payload)
    payload["shop_id"] = shop
    with pytest.raises(ContractError, match="invalid_shop_id"):
        normalize_commercegov_event(payload)

