from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from authority_agent.commercegov_proposal import ProposalCreateResult
from authority_agent.prompt_intent import (
    PROMPT_SYSTEM_INSTRUCTION,
    PromptIntent,
    prompt_intent_tool_spec,
)
from authority_agent.prompt_presets import ALLOWED_PROPOSAL, FORBIDDEN_PROPOSAL
from authority_agent.prompt_runtime import PromptRuntime
from tests.unit.test_prompt_demo_surface import (
    RecordingHost,
    RecordingInterpreter,
    finish_prompt,
    propose_intent,
    run_event,
)

SHOP = "controlled-demo.myshopify.com"


def _action_schema(spec: dict) -> dict:
    found: list[dict] = []

    def walk(node) -> None:
        if isinstance(node, dict):
            properties = node.get("properties")
            if isinstance(properties, dict):
                action = properties.get("action")
                if isinstance(action, dict):
                    found.append(action)
            for value in node.values():
                walk(value)
            return
        if isinstance(node, list):
            for item in node:
                walk(item)

    walk(spec)
    assert found, spec
    return found[0]


def test_action_schema_remains_bedrock_compatible_enum() -> None:
    spec = prompt_intent_tool_spec()
    action = _action_schema(spec)
    assert action.get("type") == "string"
    assert action.get("type") != ["string", "null"]
    assert set(action.get("enum") or []) == {"PROPOSE", "APPROVE", "APPLY", "OTHER"}
    description = str(action.get("description") or "")
    assert "PRIMARY" in description
    json.dumps(spec)


def test_interpreter_instruction_maps_primary_authority_actions() -> None:
    text = PROMPT_SYSTEM_INSTRUCTION
    assert "PRIMARY requested action" in text
    assert "Find X and propose changing its title to Y" in text
    assert "action=PROPOSE" in text
    assert "Approve CommerceGov proposal 123" in text
    assert "action=APPROVE" in text
    assert "Apply CommerceGov proposal 123 to production" in text
    assert "action=APPLY" in text
    assert "Summarize what CommerceGov does" in text
    assert "action=OTHER" in text
    assert "Lookup and policy checks are execution steps" in text


def test_allowed_proposal_prompt_contract_is_propose() -> None:
    assert 'exact title "AWS Authority Demo Snowboard"' in ALLOWED_PROPOSAL
    intent = PromptIntent.model_validate(
        {
            "action": "propose",
            "summary": "Propose a governed title change for human review.",
            "product_query": "AWS Authority Demo Snowboard",
            "mutation_class": "product.title",
            "proposed_value": "AWS Authority Demo Snowboard — Governed",
        }
    )
    assert intent.action == "PROPOSE"
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


def test_forbidden_proposal_semantic_action_is_still_propose() -> None:
    intent = propose_intent(
        proposed_value=(
            "AWS Policy Demo Snowboard — This title intentionally exceeds "
            "the governed seventy character limit"
        )
    )
    assert intent.action == "PROPOSE"
    host = RecordingHost(ProposalCreateResult("294x", "fail", ("title_too_long",), "gid-snowboard"))
    runtime = PromptRuntime(
        interpreter=RecordingInterpreter(intent),
        shop_id=SHOP,
        host=host,
    )
    _posted, terminal, _store, _invoker = finish_prompt(run_event(FORBIDDEN_PROPOSAL), runtime)
    body = json.loads(terminal["body"])
    assert intent.action == "PROPOSE"
    assert body["state"] == "DENIED"
    assert body["evidence"]["policy_result"] == "DENIED"
    assert body["evidence"]["denial_reason"] == "title_too_long"
    assert host.proposals


def test_approve_prompt_parses_as_approve_and_host_denies() -> None:
    intent = PromptIntent.model_validate(
        {
            "action": "APPROVE",
            "summary": "Approve CommerceGov proposal 2933.",
            "proposal_id": "2933",
        }
    )
    assert intent.action == "APPROVE"
    assert intent.proposal_id == "2933"
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
    assert body["evidence"]["action"] == "APPROVE"
    assert body["evidence"]["required_authority"] == "HUMAN"
    assert host.proposals == []


def test_apply_prompt_parses_as_apply_and_host_denies() -> None:
    intent = PromptIntent.model_validate(
        {
            "action": "APPLY",
            "summary": "Apply CommerceGov proposal 2933 to production.",
            "proposal_id": "2933",
        }
    )
    assert intent.action == "APPLY"
    assert intent.proposal_id == "2933"
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
    assert body["evidence"]["action"] == "APPLY"
    assert body["evidence"]["production_mutation"] == "NONE"
    assert host.proposals == []


def test_genuine_other_does_not_create_proposal() -> None:
    intent = PromptIntent.model_validate(
        {
            "action": "OTHER",
            "summary": "CommerceGov is a governed commerce control plane.",
        }
    )
    assert intent.action == "OTHER"
    host = RecordingHost()
    runtime = PromptRuntime(
        interpreter=RecordingInterpreter(intent),
        shop_id=SHOP,
        host=host,
    )
    _posted, terminal, _store, _invoker = finish_prompt(
        run_event("Summarize what CommerceGov does."), runtime
    )
    body = json.loads(terminal["body"])
    assert body["state"] == "ERROR"
    assert body["evidence"]["denial_reason"] == "unrecognized_agent_action"
    assert host.proposals == []
    assert host.lookups == []


def test_lookup_plus_propose_is_propose_not_other() -> None:
    intent = PromptIntent.model_validate(
        {
            "action": "PROPOSE",
            "summary": "Propose a title change after inspecting the current product.",
            "product_query": "The Complete Snowboard",
            "mutation_class": "product.title",
            "proposed_value": "Y",
        }
    )
    assert intent.action == "PROPOSE"
    host = RecordingHost()
    runtime = PromptRuntime(
        interpreter=RecordingInterpreter(intent),
        shop_id=SHOP,
        host=host,
    )
    _posted, terminal, _store, _invoker = finish_prompt(
        run_event("Find product X, inspect its current title, and propose changing the title to Y."),
        runtime,
    )
    body = json.loads(terminal["body"])
    assert body["state"] == "SUCCESS"
    assert host.proposals
    with pytest.raises(ValidationError):
        PromptIntent.model_validate(
            {
                "action": "lookup",
                "summary": "Look up the product before proposing.",
            }
        )
