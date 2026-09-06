from __future__ import annotations

import json
import logging
from types import SimpleNamespace

from authority_agent.strands_observability import SafeStrandsHooks, bind_semantic_correlation, reset_semantic_correlation
from authority_agent.strands_provider import StrandsSemanticProvider
from tests.integration.test_p1_strands_provider import FakeAgent, output, provider_for


class _Registry:
    def __init__(self) -> None:
        self.callbacks: dict[type, list] = {}

    def add_callback(self, event_type, callback) -> None:
        self.callbacks.setdefault(event_type, []).append(callback)


def _callback(hooks_registry: _Registry, name: str):
    event_type = next(key for key in hooks_registry.callbacks if key.__name__ == name)
    return hooks_registry.callbacks[event_type][0]


def test_hooks_log_allowlisted_lifecycle_only(caplog) -> None:
    caplog.set_level(logging.INFO, logger="authority_agent.strands")
    hooks = SafeStrandsHooks()
    registry = _Registry()
    hooks.register_hooks(registry)
    token = bind_semantic_correlation(event_id="evt-1", api_request_id="api-1", lambda_request_id="lam-1")
    try:
        _callback(registry, "BeforeInvocationEvent")(SimpleNamespace())
        _callback(registry, "AfterInvocationEvent")(SimpleNamespace(exception=None, error=None))
        _callback(registry, "BeforeModelCallEvent")(SimpleNamespace())
        _callback(registry, "AfterModelCallEvent")(SimpleNamespace(exception=None, error=None))
        tool = SimpleNamespace(
            selected_tool=SimpleNamespace(tool_name="get_governance_context"),
            tool_use={"name": "get_governance_context", "input": {"secret": "nope"}},
            exception=None,
            error=None,
        )
        _callback(registry, "BeforeToolCallEvent")(tool)
        failed = SimpleNamespace(
            selected_tool=SimpleNamespace(tool_name="get_governance_context"),
            tool_use={"name": "get_governance_context", "output": "governed-body"},
            exception=RuntimeError("boom"),
            error=None,
        )
        _callback(registry, "AfterToolCallEvent")(failed)
    finally:
        reset_semantic_correlation(token)
    payloads = [json.loads(record.getMessage()) for record in caplog.records if record.name == "authority_agent.strands"]
    stages = [item["stage"] for item in payloads]
    assert stages == [
        "agent_started",
        "agent_completed",
        "model_started",
        "model_completed",
        "tool_started",
        "tool_failed",
    ]
    for payload in payloads:
        assert payload["message"] == "strands_lifecycle"
        assert payload.get("event_id") == "evt-1"
        assert "prompt" not in payload
        assert "transcript" not in payload
        assert "secret" not in str(payload).lower() or payload.get("event_id") == "evt-1"
        assert "nope" not in json.dumps(payload)
        assert "governed-body" not in json.dumps(payload)


def test_assess_does_not_log_prompt_or_tool_bodies(canonical_payload, caplog) -> None:
    caplog.set_level(logging.INFO, logger="authority_agent.strands")
    agent = FakeAgent(output())
    event, provider, _captured = provider_for(canonical_payload, agent)
    assert isinstance(provider, StrandsSemanticProvider)
    provider.assess(event)
    prompt = agent.calls[0][0]
    combined = "\n".join(record.getMessage() for record in caplog.records)
    assert prompt not in combined
    assert "chain-of-thought" not in combined.lower()


def test_strands_logger_emits_info() -> None:
    from authority_agent.strands_observability import LOGGER

    assert LOGGER.level == logging.INFO
