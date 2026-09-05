"""Explicitly opt-in Bedrock smoke test; normal tests never call AWS."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

from authority_agent.commercegov_read import CommerceGovReadClient
from authority_agent.normalization import normalize_commercegov_event
from authority_agent.semantic_context import SemanticContextBuilder
from authority_agent.strands_provider import StrandsSemanticProvider


class _FixtureReadTransport:
    """Local context fixture used so the optional smoke tests Bedrock only."""

    def get_json(self, path: str) -> Mapping[str, Any]:
        if path.endswith("/policy"):
            return {
                "shop_id": "demo-shop.myshopify.com",
                "schema_version": "commercegov.policy.v1",
                "effective_policy_hash": "sha256:bedrock-smoke",
                "controlled_fields": ["title"],
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
        return {
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


def main() -> int:
    if os.getenv("RUN_BEDROCK_LIVE_SMOKE") != "1":
        print("BEDROCK_LIVE_SMOKE: BLOCKED (set RUN_BEDROCK_LIVE_SMOKE=1 explicitly)")
        return 2

    fixture = Path(__file__).resolve().parents[2] / "fixtures" / "external_product_title_change.json"
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    event = normalize_commercegov_event(payload)
    builder = SemanticContextBuilder(CommerceGovReadClient(_FixtureReadTransport()))
    provider = StrandsSemanticProvider(
        context_builder=builder,
        region_name=os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION"),
        # First-use Bedrock latency can exceed the hosted request budget. The
        # pre-deployment smoke measures that path before P2 chooses a runtime.
        timeout_seconds=60.0,
    )
    result = provider.assess(event)
    print(f"BEDROCK_LIVE_SMOKE: PASS ({result.classification})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
