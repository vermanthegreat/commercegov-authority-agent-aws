from __future__ import annotations

import json

import pytest

from authority_agent.prompt_intent import (
    PROMPT_SYSTEM_INSTRUCTION,
    PromptIntent,
    prompt_intent_tool_spec,
)
from authority_agent.prompt_presets import ALLOWED_PROPOSAL
from authority_agent.prompt_runtime import PromptRuntime
from tests.unit.test_prompt_demo_surface import (
    RecordingHost,
    RecordingInterpreter,
    finish_prompt,
    run_event,
)

SHOP = "controlled-demo.myshopify.com"


def _properties(spec: dict) -> dict:
    found: list[dict] = []

    def walk(node) -> None:
        if isinstance(node, dict):
            properties = node.get("properties")
            if isinstance(properties, dict) and "proposed_value" in properties:
                found.append(properties)
            for value in node.values():
                walk(value)
            return
        if isinstance(node, list):
            for item in node:
                walk(item)

    walk(spec)
    assert found, spec
    return found[0]


def test_propose_fields_are_required_strings_with_extraction_descriptions() -> None:
    spec = prompt_intent_tool_spec()
    props = _properties(spec)
    for name in ("product_query", "mutation_class", "proposed_value", "proposal_id"):
        assert props[name]["type"] == "string"
        assert "default" not in props[name]
    encoded = json.dumps(spec)
    assert "proposed_value" in encoded
    description = str(props["proposed_value"].get("description") or "")
    assert "exact" in description.lower()
    assert "quoted" in description.lower()
    assert "AWS Governed" not in PROMPT_SYSTEM_INSTRUCTION
    assert "When action is PROPOSE you MUST populate" in PROMPT_SYSTEM_INSTRUCTION
    assert "copy the quoted text without surrounding quotation marks" in PROMPT_SYSTEM_INSTRUCTION
    product_description = str(props["product_query"].get("description") or "")
    assert "identifier or exact title" in product_description
    assert "Shopify product GID verbatim" in product_description
    assert "Do not invent IDs" in PROMPT_SYSTEM_INSTRUCTION


@pytest.mark.parametrize(
    "product_query",
    ["9253164613795", "gid://shopify/Product/9253164613795"],
)
def test_explicit_product_identifier_is_preserved_verbatim(product_query: str) -> None:
    intent = PromptIntent.model_validate(
        {
            "action": "PROPOSE",
            "summary": "Propose an exact product change.",
            "product_query": product_query,
            "mutation_class": "product.title",
            "proposed_value": "Governed title",
        }
    )
    assert intent.product_query == product_query


def test_exact_live_allowed_prompt_intent_fields() -> None:
    assert "AWS Authority Demo Snowboard — Governed" in ALLOWED_PROPOSAL
    intent = PromptIntent.model_validate(
        {
            "action": "PROPOSE",
            "summary": "Propose a governed title change.",
            "product_query": "AWS Authority Demo Snowboard",
            "mutation_class": "product.title",
            "proposed_value": '"AWS Authority Demo Snowboard — Governed"',
        }
    )
    assert intent.action == "PROPOSE"
    assert intent.product_query == "AWS Authority Demo Snowboard"
    assert intent.mutation_class == "product.title"
    assert intent.proposed_value == "AWS Authority Demo Snowboard — Governed"
    host = RecordingHost()
    runtime = PromptRuntime(
        interpreter=RecordingInterpreter(intent),
        shop_id=SHOP,
        host=host,
    )
    _posted, terminal, _store, _invoker = finish_prompt(run_event(ALLOWED_PROPOSAL), runtime)
    body = json.loads(terminal["body"])
    assert body["state"] == "SUCCESS"
    assert host.proposals


def test_different_title_value_is_not_demo_hardcoded() -> None:
    intent = PromptIntent.model_validate(
        {
            "action": "PROPOSE",
            "summary": "Propose a title change.",
            "product_query": "Product X",
            "mutation_class": "product.title",
            "proposed_value": "Summer Catalog Item",
        }
    )
    assert intent.product_query == "Product X"
    assert intent.mutation_class == "product.title"
    assert intent.proposed_value == "Summer Catalog Item"
    assert intent.proposed_value != "AWS Authority Demo Snowboard — Governed"


def test_description_mutation_extracts_description_fields() -> None:
    intent = PromptIntent.model_validate(
        {
            "action": "PROPOSE",
            "summary": "Propose a description change.",
            "product_query": "Product X",
            "mutation_class": "product.description",
            "proposed_value": "New product description",
        }
    )
    assert intent.action == "PROPOSE"
    assert intent.product_query == "Product X"
    assert intent.mutation_class == "product.description"
    assert intent.proposed_value == "New product description"


def test_missing_proposed_value_fails_closed_without_proposal_post() -> None:
    intent = PromptIntent.model_validate(
        {
            "action": "PROPOSE",
            "summary": "Propose a title change.",
            "product_query": "Product X",
            "mutation_class": "product.title",
            "proposed_value": "",
        }
    )
    host = RecordingHost()
    runtime = PromptRuntime(
        interpreter=RecordingInterpreter(intent),
        shop_id=SHOP,
        host=host,
    )
    _posted, terminal, _store, _invoker = finish_prompt(
        run_event("Find Product X and propose changing its title."), runtime
    )
    body = json.loads(terminal["body"])
    assert intent.action == "PROPOSE"
    assert body["state"] == "ERROR"
    assert body["evidence"]["denial_reason"] == "missing_proposed_value"
    assert host.proposals == []
    assert host.lookups == []


def test_approve_does_not_require_proposed_value() -> None:
    intent = PromptIntent.model_validate(
        {
            "action": "APPROVE",
            "summary": "Approve CommerceGov proposal 2933.",
            "proposal_id": "2933",
        }
    )
    assert intent.action == "APPROVE"
    assert intent.proposal_id == "2933"
    assert intent.proposed_value == ""
    host = RecordingHost()
    runtime = PromptRuntime(
        interpreter=RecordingInterpreter(intent),
        shop_id=SHOP,
        host=host,
    )
    _posted, terminal, _store, _invoker = finish_prompt(
        run_event("Approve CommerceGov proposal 2933."), runtime
    )
    body = json.loads(terminal["body"])
    assert body["state"] == "DENIED"
    assert body["evidence"]["required_authority"] == "HUMAN"
    assert host.proposals == []


def test_apply_does_not_require_proposed_value() -> None:
    intent = PromptIntent.model_validate(
        {
            "action": "APPLY",
            "summary": "Apply CommerceGov proposal 2933 to production.",
            "proposal_id": "2933",
        }
    )
    assert intent.action == "APPLY"
    assert intent.proposal_id == "2933"
    assert intent.proposed_value == ""
    host = RecordingHost()
    runtime = PromptRuntime(
        interpreter=RecordingInterpreter(intent),
        shop_id=SHOP,
        host=host,
    )
    _posted, terminal, _store, _invoker = finish_prompt(
        run_event("Apply CommerceGov proposal 2933 to production."), runtime
    )
    body = json.loads(terminal["body"])
    assert body["state"] == "DENIED"
    assert body["evidence"]["production_mutation"] == "NONE"
    assert host.proposals == []
