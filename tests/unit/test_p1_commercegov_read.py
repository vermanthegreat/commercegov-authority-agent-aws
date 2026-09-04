from __future__ import annotations

from copy import deepcopy

import pytest

from authority_agent.commercegov_read import CommerceGovReadError, HttpxCommerceGovReadTransport
from tests.p1_helpers import POLICY_RESPONSE, PRODUCT_RESPONSE, p1_parts


def test_read_client_uses_only_fixed_tenant_bound_get_paths(canonical_payload) -> None:
    event, transport, builder = p1_parts(canonical_payload)
    context, governance, policy = builder.build(event)
    assert transport.paths == [
        "/api/integration/v1/shops/demo-shop.myshopify.com/products/7001/content",
        "/api/integration/v1/shops/demo-shop.myshopify.com/policy",
    ]
    assert context.agency_id == governance.agency_id == policy.agency_id == "demo-agency"
    assert context.shop_id == governance.shop_id == policy.shop_id


@pytest.mark.parametrize(
    ("kind", "mutate", "code"),
    [
        ("product", lambda value: value.update(shop_id="other.myshopify.com"), "product_context_identity_mismatch"),
        ("product", lambda value: value.update(product_id="9999"), "product_context_identity_mismatch"),
        ("policy", lambda value: value.update(shop_id="other.myshopify.com"), "policy_context_identity_mismatch"),
        ("product", lambda value: value.pop("content"), "invalid_product_context_response"),
        ("policy", lambda value: value["rules"].update(extra=True), "invalid_policy_context_response"),
    ],
)
def test_invalid_or_cross_tenant_context_is_denied(canonical_payload, kind, mutate, code) -> None:
    product = deepcopy(PRODUCT_RESPONSE)
    policy = deepcopy(POLICY_RESPONSE)
    mutate(product if kind == "product" else policy)
    event, _transport, builder = p1_parts(canonical_payload, product=product, policy=policy)
    with pytest.raises(CommerceGovReadError, match=code):
        builder.build(event)


def test_context_must_match_event_observed_value(canonical_payload) -> None:
    product = deepcopy(PRODUCT_RESPONSE)
    product["content"]["title"] = "different value"
    event, _transport, builder = p1_parts(canonical_payload, product=product)
    with pytest.raises(ValueError, match="commercegov_observed_value_mismatch"):
        builder.build(event)


def test_http_transport_rejects_non_https_and_arbitrary_paths_before_network() -> None:
    with pytest.raises(ValueError, match="invalid_commercegov_read_configuration"):
        HttpxCommerceGovReadTransport(base_url="http://commercegov.invalid", bearer_token="demo")
    transport = HttpxCommerceGovReadTransport(
        base_url="https://commercegov.invalid", bearer_token="synthetic-test-token"
    )
    with pytest.raises(CommerceGovReadError, match="unapproved_commercegov_read_path"):
        transport.get_json("/admin/apply")
