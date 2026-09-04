from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from authority_agent.commercegov_read import CommerceGovReadClient
from authority_agent.normalization import normalize_commercegov_event
from authority_agent.semantic_context import SemanticContextBuilder


PRODUCT_RESPONSE = {
    "shop_id": "demo-shop.myshopify.com",
    "product_id": "7001",
    "field_registry": "product_content",
    "stage": "APPROVED",
    "content": {
        "title": "Externally changed demo title",
        "description": "A governed description",
        "meta_title": "A governed meta title",
        "meta_description": "A governed meta description",
    },
    "audit_id": "42",
    "updated_at": "2026-09-05T12:34:56Z",
}

POLICY_RESPONSE = {
    "shop_id": "demo-shop.myshopify.com",
    "schema_version": "commercegov.policy.v1",
    "effective_policy_hash": "sha256:demo-policy",
    "controlled_fields": ["title", "description", "meta_title", "meta_description"],
    "rules": {
        "brand_tone": "clear and factual",
        "forbidden_terms": ["guaranteed"],
        "max_length": {
            "title": 80,
            "description": 5000,
            "meta_title": 70,
            "meta_description": 160,
        },
        "seo_constraints": {"keyword_coverage": "natural"},
        "proposal_instructions": "Return changes for human review.",
    },
}


class FakeReadTransport:
    def __init__(self, *, product=None, policy=None, error: Exception | None = None):
        self.product = deepcopy(PRODUCT_RESPONSE if product is None else product)
        self.policy = deepcopy(POLICY_RESPONSE if policy is None else policy)
        self.error = error
        self.paths: list[str] = []

    def get_json(self, path: str) -> Mapping[str, Any]:
        self.paths.append(path)
        if self.error is not None:
            raise self.error
        return deepcopy(self.policy if path.endswith("/policy") else self.product)


def p1_parts(payload: Mapping[str, Any], **transport_kwargs):
    event = normalize_commercegov_event(payload)
    transport = FakeReadTransport(**transport_kwargs)
    builder = SemanticContextBuilder(CommerceGovReadClient(transport))
    return event, transport, builder
