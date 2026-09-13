from __future__ import annotations

import json

from authority_agent.prompt_demo_surface import execute_stored_prompt_run
from authority_agent.prompt_runtime import PromptRuntime
from tests.unit.test_prompt_demo_surface import (
    RecordingHost,
    RecordingInterpreter,
    RecordingInvoker,
    invoke,
    propose_intent,
    run_event,
    status_event,
)
from authority_agent.prompt_run_store import MemoryPromptRunStore


SHOP = "controlled-demo.myshopify.com"


def test_post_returns_running_without_waiting_for_model() -> None:
    interpreter = RecordingInterpreter(propose_intent())
    host = RecordingHost()
    runtime = PromptRuntime(interpreter=interpreter, shop_id=SHOP, host=host)
    store = MemoryPromptRunStore()
    invoker = RecordingInvoker()
    posted = invoke(run_event("allowed", "run-async"), runtime, store=store, invoker=invoker)
    body = json.loads(posted["body"])
    assert posted["statusCode"] == 202
    assert body["state"] == "RUNNING"
    assert body["evidence"]["aws_run_id"] == "run-async"
    assert body["evidence"]["status"] == "RUNNING"
    assert body["evidence"]["agent_authority"] == "PROPOSE_ONLY"
    assert body["evidence"]["production_mutation"] == "NONE"
    assert interpreter.calls == []
    assert host.proposals == []
    assert invoker.calls == [{"run_id": "run-async", "prompt": "allowed"}]


def test_get_returns_running_while_execution_is_active() -> None:
    interpreter = RecordingInterpreter(propose_intent())
    runtime = PromptRuntime(interpreter=interpreter, shop_id=SHOP, host=RecordingHost())
    store = MemoryPromptRunStore()
    invoker = RecordingInvoker()
    invoke(run_event("allowed", "run-active"), runtime, store=store, invoker=invoker)
    status = invoke(status_event("run-active"), runtime, store=store, invoker=invoker)
    body = json.loads(status["body"])
    assert status["statusCode"] == 202
    assert body["state"] == "RUNNING"
    assert interpreter.calls == []


def test_terminal_success_propagates_proposal_evidence() -> None:
    interpreter = RecordingInterpreter(propose_intent())
    host = RecordingHost()
    runtime = PromptRuntime(interpreter=interpreter, shop_id=SHOP, host=host)
    store = MemoryPromptRunStore()
    invoker = RecordingInvoker()
    invoke(run_event("allowed", "run-ok"), runtime, store=store, invoker=invoker)
    execute_stored_prompt_run("run-ok", runtime, store)
    body = json.loads(invoke(status_event("run-ok"), runtime, store=store, invoker=invoker)["body"])
    assert body["state"] == "SUCCESS"
    assert body["evidence"]["proposal_id"] == "293x"
    assert body["evidence"]["policy_result"] == "ALLOWED"
    assert body["evidence"]["status"] == "SUCCESS"
    assert host.proposals


def test_terminal_denied_propagates_authority_evidence() -> None:
    interpreter = RecordingInterpreter(
        propose_intent(action="APPROVE", summary="Cannot approve.", proposal_id="293x", proposed_value="")
    )
    host = RecordingHost()
    runtime = PromptRuntime(interpreter=interpreter, shop_id=SHOP, host=host)
    store = MemoryPromptRunStore()
    invoker = RecordingInvoker()
    invoke(run_event("approve", "run-deny"), runtime, store=store, invoker=invoker)
    execute_stored_prompt_run("run-deny", runtime, store)
    body = json.loads(invoke(status_event("run-deny"), runtime, store=store, invoker=invoker)["body"])
    assert body["state"] == "DENIED"
    assert body["evidence"]["action"] == "APPROVE"
    assert body["evidence"]["required_authority"] == "HUMAN"
    assert body["evidence"]["status"] == "DENIED"
    assert host.proposals == []


def test_terminal_error_propagates_truthfully() -> None:
    interpreter = RecordingInterpreter(propose_intent(mutation_class="arbitrary_unknown_class"))
    host = RecordingHost()
    runtime = PromptRuntime(interpreter=interpreter, shop_id=SHOP, host=host)
    store = MemoryPromptRunStore()
    invoker = RecordingInvoker()
    invoke(run_event("bad", "run-err"), runtime, store=store, invoker=invoker)
    execute_stored_prompt_run("run-err", runtime, store)
    body = json.loads(invoke(status_event("run-err"), runtime, store=store, invoker=invoker)["body"])
    assert body["state"] == "ERROR"
    assert body["evidence"]["denial_reason"] == "unsupported_mutation_class"
    assert host.proposals == []


def test_duplicate_polling_does_not_rerun_bedrock() -> None:
    interpreter = RecordingInterpreter(propose_intent())
    runtime = PromptRuntime(interpreter=interpreter, shop_id=SHOP, host=RecordingHost())
    store = MemoryPromptRunStore()
    invoker = RecordingInvoker()
    invoke(run_event("allowed", "run-once"), runtime, store=store, invoker=invoker)
    execute_stored_prompt_run("run-once", runtime, store)
    execute_stored_prompt_run("run-once", runtime, store)
    first = json.loads(invoke(status_event("run-once"), runtime, store=store, invoker=invoker)["body"])
    second = json.loads(invoke(status_event("run-once"), runtime, store=store, invoker=invoker)["body"])
    assert first["state"] == "SUCCESS"
    assert second["state"] == "SUCCESS"
    assert len(interpreter.calls) == 1


def test_duplicate_send_starts_separate_runs() -> None:
    interpreter = RecordingInterpreter(propose_intent())
    runtime = PromptRuntime(interpreter=interpreter, shop_id=SHOP, host=RecordingHost())
    store = MemoryPromptRunStore()
    invoker = RecordingInvoker()
    first = json.loads(invoke(run_event("one", "run-a"), runtime, store=store, invoker=invoker)["body"])
    second = json.loads(invoke(run_event("two", "run-b"), runtime, store=store, invoker=invoker)["body"])
    assert first["evidence"]["aws_run_id"] == "run-a"
    assert second["evidence"]["aws_run_id"] == "run-b"
    assert [call["run_id"] for call in invoker.calls] == ["run-a", "run-b"]
    assert interpreter.calls == []
