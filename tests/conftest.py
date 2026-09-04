from __future__ import annotations

import json
from pathlib import Path

import pytest

from authority_agent.orchestration import (
    AuthorityProcessor,
    InMemoryIdempotencyLedger,
    StaticSemanticProvider,
    TenantBindingRegistry,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def canonical_payload() -> dict:
    return json.loads(
        (ROOT / "fixtures" / "external_product_title_change.json").read_text(
            encoding="utf-8"
        )
    )


def make_processor(output=None, *, error=None, bindings=None):
    provider = StaticSemanticProvider(output, error=error)
    processor = AuthorityProcessor(
        bindings=TenantBindingRegistry(
            bindings or [("demo-agency", "demo-shop.myshopify.com")]
        ),
        ledger=InMemoryIdempotencyLedger(),
        semantic_provider=provider,
    )
    return processor, provider

