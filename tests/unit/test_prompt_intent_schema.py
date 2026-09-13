from __future__ import annotations

import json

from authority_agent.prompt_intent import PromptIntent, prompt_intent_tool_spec
from authority_agent.prompt_runtime import PromptRuntime
from tests.unit.test_prompt_demo_surface import (
    RecordingHost,
    RecordingInterpreter,
    finish_prompt,
    propose_intent,
    run_event,
)


def _mutation_class_schema(spec: dict) -> dict:
    found: list[dict] = []

    def walk(node) -> None:
        if isinstance(node, dict):
            properties = node.get("properties")
            if isinstance(properties, dict):
                mutation = properties.get("mutation_class")
                if isinstance(mutation, dict):
                    found.append(mutation)
            for value in node.values():
                walk(value)
            return
        if isinstance(node, list):
            for item in node:
                walk(item)

    walk(spec)
    assert found, spec
    return found[0]


def test_prompt_intent_tool_schema_is_bedrock_compatible_string() -> None:
    spec = prompt_intent_tool_spec()
    serialized = json.dumps(spec)
    mutation = _mutation_class_schema(spec)
    assert mutation["type"] == "string"
    assert "enum" not in mutation
    assert "anyOf" not in mutation
    assert "oneOf" not in mutation
    assert mutation.get("type") != ["string", "null"]
    assert '"enum"' not in json.dumps(mutation)
    json.loads(serialized)
    spec = prompt_intent_tool_spec()
    props = None

    def walk(node) -> None:
        nonlocal props
        if isinstance(node, dict):
            properties = node.get("properties")
            if isinstance(properties, dict) and "proposed_value" in properties:
                props = properties
            for value in node.values():
                walk(value)
            return
        if isinstance(node, list):
            for item in node:
                walk(item)

    walk(spec)
    assert props is not None
    for name in ("product_query", "mutation_class", "proposed_value", "proposal_id"):
        field = props[name]
        assert field["type"] == "string"
        assert "enum" not in field
        assert "anyOf" not in field
        assert "oneOf" not in field
    required = []

    def walk_required(node) -> None:
        if isinstance(node, dict):
            if isinstance(node.get("required"), list) and "proposed_value" in node["required"]:
                required.extend(node["required"])
            for value in node.values():
                walk_required(value)
        elif isinstance(node, list):
            for item in node:
                walk_required(item)

    walk_required(spec)
    assert "proposed_value" in required
    assert "exact" in str(props["proposed_value"].get("description") or "").lower() or "quoted" in str(
        props["proposed_value"].get("description") or ""
    ).lower()


def test_valid_product_title_mutation_class_is_accepted_by_host() -> None:
    host = RecordingHost()
    runtime = PromptRuntime(
        interpreter=RecordingInterpreter(propose_intent(mutation_class="product.title")),
        shop_id="controlled-demo.myshopify.com",
        host=host,
    )
    _posted, terminal, _store, _invoker = finish_prompt(run_event("propose title"), runtime)
    body = json.loads(terminal["body"])
    assert body["state"] == "SUCCESS"
    assert host.proposals
    assert body["evidence"]["requested_mutation"] == "product.title"


def test_unknown_mutation_class_fails_closed_without_proposal_post() -> None:
    host = RecordingHost()
    runtime = PromptRuntime(
        interpreter=RecordingInterpreter(
            propose_intent(mutation_class="arbitrary_unknown_class")
        ),
        shop_id="controlled-demo.myshopify.com",
        host=host,
    )
    _posted, terminal, _store, _invoker = finish_prompt(run_event("propose unknown"), runtime)
    body = json.loads(terminal["body"])
    assert body["state"] == "ERROR"
    assert body["evidence"]["denial_reason"] == "unsupported_mutation_class"
    assert host.proposals == []
    assert host.lookups == []


def test_approve_intent_parses_without_mutation_class_and_host_denies() -> None:
    intent = PromptIntent.model_validate(
        {
            "action": "APPROVE",
            "summary": "Approve CommerceGov proposal 293x.",
            "mutation_class": None,
        }
    )
    assert intent.mutation_class == ""
    host = RecordingHost()
    runtime = PromptRuntime(
        interpreter=RecordingInterpreter(intent),
        shop_id="controlled-demo.myshopify.com",
        host=host,
    )
    _posted, terminal, _store, _invoker = finish_prompt(
        run_event("Approve CommerceGov proposal 293x."), runtime
    )
    body = json.loads(terminal["body"])
    assert body["state"] == "DENIED"
    assert body["state"] != "ERROR"
    assert body["evidence"]["action"] == "APPROVE"
    assert body["evidence"]["decision"] == "DENIED"
    assert body["evidence"]["required_authority"] == "HUMAN"
    assert body["evidence"]["agent_authority"] == "PROPOSE_ONLY"
    assert body["evidence"]["production_mutation"] == "NONE"
    assert host.proposals == []


def test_apply_intent_parses_without_mutation_class_and_host_denies() -> None:
    intent = PromptIntent.model_validate(
        {"action": "APPLY", "summary": "Apply CommerceGov proposal 293x to production."}
    )
    assert intent.mutation_class == ""
    host = RecordingHost()
    runtime = PromptRuntime(
        interpreter=RecordingInterpreter(intent),
        shop_id="controlled-demo.myshopify.com",
        host=host,
    )
    _posted, terminal, _store, _invoker = finish_prompt(
        run_event("Apply CommerceGov proposal 293x to production."), runtime
    )
    body = json.loads(terminal["body"])
    assert body["state"] == "DENIED"
    assert body["state"] != "ERROR"
    assert body["evidence"]["action"] == "APPLY"
    assert body["evidence"]["decision"] == "DENIED"
    assert body["evidence"]["required_authority"] == "HUMAN"
    assert body["evidence"]["production_mutation"] == "NONE"
    assert host.proposals == []
