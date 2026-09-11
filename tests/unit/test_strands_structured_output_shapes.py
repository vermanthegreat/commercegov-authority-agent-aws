from __future__ import annotations

import json
from dataclasses import dataclass, field

import pytest

from authority_agent.strands_provider import (
    SemanticAssessmentSchema,
    SemanticProviderFailure,
    _one_shot_structured_assessment,
)
from tests.integration.test_p1_strands_provider import FakeAgent, output


def _metadata_chunk() -> dict:
    return {
        "metadata": {
            "usage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2},
            "metrics": {"latencyMs": 1},
        }
    }


def _tool_use_stream_events(
    *,
    tool_name: str,
    tool_input: dict,
    stop_reason: str = "tool_use",
    tool_use_id: str = "tool-1",
) -> list[dict]:
    return [
        {"messageStart": {"role": "assistant"}},
        {
            "contentBlockStart": {
                "start": {"toolUse": {"toolUseId": tool_use_id, "name": tool_name}}
            }
        },
        {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(tool_input)}}}},
        {"contentBlockStop": {}},
        {"messageStop": {"stopReason": stop_reason}},
        _metadata_chunk(),
    ]


def _text_only_stream_events(*, text: str = "plain text", stop_reason: str = "end_turn") -> list[dict]:
    return [
        {"messageStart": {"role": "assistant"}},
        {"contentBlockDelta": {"delta": {"text": text}}},
        {"contentBlockStop": {}},
        {"messageStop": {"stopReason": stop_reason}},
        _metadata_chunk(),
    ]


@dataclass
class FakeStreamModel:
    events: list[dict]
    stream_calls: int = field(default=0, init=False)
    last_kwargs: dict | None = field(default=None, init=False)

    def stream(self, *, messages, tool_specs, system_prompt=None, tool_choice=None, **kwargs):
        self.stream_calls += 1
        self.last_kwargs = {
            "messages": messages,
            "tool_specs": tool_specs,
            "system_prompt": system_prompt,
            "tool_choice": tool_choice,
            **kwargs,
        }

        async def _events():
            for event in self.events:
                yield event

        return _events()


@dataclass
class FakeAgentWithModel:
    model: FakeStreamModel
    system_prompt: str = "test-system"


def test_tool_use_with_valid_schema_succeeds_in_one_call() -> None:
    payload = output()
    model = FakeStreamModel(_tool_use_stream_events(tool_name="SemanticAssessmentSchema", tool_input=payload))
    agent = FakeAgentWithModel(model)

    result = _one_shot_structured_assessment(agent, '{"event":"demo"}')

    assert isinstance(result, SemanticAssessmentSchema)
    assert result.classification == "REVIEW_REQUIRED"
    assert model.stream_calls == 1
    assert model.last_kwargs is not None
    assert model.last_kwargs["tool_choice"] == {"any": {}}
    assert len(model.last_kwargs["tool_specs"]) == 1
    assert model.last_kwargs["tool_specs"][0]["name"] == "SemanticAssessmentSchema"


def test_summary_over_max_length_is_clipped_and_accepted() -> None:
    payload = output(summary="S" * 1001)
    model = FakeStreamModel(_tool_use_stream_events(tool_name="SemanticAssessmentSchema", tool_input=payload))
    agent = FakeAgentWithModel(model)

    result = _one_shot_structured_assessment(agent, '{"event":"demo"}')

    assert len(result.summary) == 1000
    assert model.stream_calls == 1


def test_text_only_end_turn_raises_provider_error() -> None:
    model = FakeStreamModel(_text_only_stream_events())
    agent = FakeAgentWithModel(model)

    with pytest.raises(SemanticProviderFailure, match="invalid_structured_semantic_output"):
        _one_shot_structured_assessment(agent, '{"event":"demo"}')

    assert model.stream_calls == 1


def test_tool_use_with_forbidden_extra_raises_provider_error() -> None:
    payload = output(authority="AUTO_APPROVE")
    model = FakeStreamModel(_tool_use_stream_events(tool_name="SemanticAssessmentSchema", tool_input=payload))
    agent = FakeAgentWithModel(model)

    with pytest.raises(SemanticProviderFailure, match="invalid_structured_semantic_output"):
        _one_shot_structured_assessment(agent, '{"event":"demo"}')

    assert model.stream_calls == 1


def test_tool_use_name_mismatch_raises_provider_error() -> None:
    payload = output()
    model = FakeStreamModel(_tool_use_stream_events(tool_name="WrongSchema", tool_input=payload))
    agent = FakeAgentWithModel(model)

    with pytest.raises(SemanticProviderFailure, match="invalid_structured_semantic_output"):
        _one_shot_structured_assessment(agent, '{"event":"demo"}')

    assert model.stream_calls == 1


def test_max_tokens_with_tool_use_is_accepted() -> None:
    payload = output()
    model = FakeStreamModel(
        _tool_use_stream_events(
            tool_name="SemanticAssessmentSchema",
            tool_input=payload,
            stop_reason="max_tokens",
        )
    )
    agent = FakeAgentWithModel(model)

    result = _one_shot_structured_assessment(agent, '{"event":"demo"}')

    assert result.classification == "REVIEW_REQUIRED"
    assert model.stream_calls == 1


def test_end_turn_with_tool_use_is_accepted() -> None:
    payload = output()
    model = FakeStreamModel(
        _tool_use_stream_events(
            tool_name="SemanticAssessmentSchema",
            tool_input=payload,
            stop_reason="end_turn",
        )
    )
    agent = FakeAgentWithModel(model)

    result = _one_shot_structured_assessment(agent, '{"event":"demo"}')

    assert result.classification == "REVIEW_REQUIRED"
    assert model.stream_calls == 1


def test_fake_agent_fallback_keeps_structured_output_api() -> None:
    agent = FakeAgent(output())

    result = _one_shot_structured_assessment(agent, '{"event":"demo"}')

    assert result.classification == "REVIEW_REQUIRED"
    assert agent.calls[0][1]["structured_output_model"].__name__ == "SemanticAssessmentSchema"
    assert len(agent.calls) == 1
