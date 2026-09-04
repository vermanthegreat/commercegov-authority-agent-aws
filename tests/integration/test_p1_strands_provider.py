from __future__ import annotations

from dataclasses import dataclass
import time

import pytest

from authority_agent.commercegov_read import CommerceGovReadClient
from authority_agent.contracts import SemanticProvider
from authority_agent.orchestration import AuthorityProcessor, InMemoryIdempotencyLedger, TenantBindingRegistry
from authority_agent.strands_provider import SemanticProviderFailure, StrandsSemanticProvider
from tests.p1_helpers import FakeReadTransport, p1_parts


@dataclass
class FakeAgentResult:
    structured_output: object


class FakeAgent:
    def __init__(self, output=None, *, error=None, delay=0.0):
        self.output = output
        self.error = error
        self.delay = delay
        self.calls = []

    def __call__(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        if self.delay:
            time.sleep(self.delay)
        if self.error:
            raise self.error
        return FakeAgentResult(self.output)


def output(**changes):
    return {
        "classification": "REVIEW_REQUIRED",
        "summary": "Review the external product title change.",
        "recommended_operator_action": "REVIEW_EXTERNAL_CHANGE",
        "confidence": 0.8,
    } | changes


def provider_for(canonical_payload, agent, **kwargs):
    event, _transport, builder = p1_parts(canonical_payload)
    captured = {}

    def factory(tools):
        captured["tools"] = tools
        return agent

    provider = StrandsSemanticProvider(context_builder=builder, agent_factory=factory, **kwargs)
    return event, provider, captured


def test_real_adapter_protocol_and_current_structured_output_api(canonical_payload) -> None:
    agent = FakeAgent(output())
    event, provider, captured = provider_for(canonical_payload, agent)
    assert isinstance(provider, SemanticProvider)
    result = provider.assess(event)
    assert result.classification == "REVIEW_REQUIRED"
    assert agent.calls[0][1]["structured_output_model"].__name__ == "SemanticAssessmentSchema"
    assert {tool.tool_name for tool in captured["tools"]} == {"get_governance_context", "get_effective_policy"}


@pytest.mark.parametrize(
    "agent",
    [
        FakeAgent(None),
        FakeAgent(output(authority="AUTO_APPROVE")),
        FakeAgent(output(recommended_operator_action="APPLY")),
        FakeAgent(error=RuntimeError("model unavailable")),
    ],
)
def test_provider_rejects_malformed_unsafe_or_failed_model_output(canonical_payload, agent) -> None:
    event, provider, _captured = provider_for(canonical_payload, agent)
    with pytest.raises(SemanticProviderFailure):
        provider.assess(event)


def test_model_timeout_fails_closed(canonical_payload) -> None:
    event, provider, _captured = provider_for(
        canonical_payload, FakeAgent(output(), delay=0.03), timeout_seconds=0.001
    )
    with pytest.raises(SemanticProviderFailure, match="bedrock_semantic_timeout"):
        provider.assess(event)


def test_read_tool_timeout_becomes_safe_provider_failure(canonical_payload) -> None:
    event, _transport, _builder = p1_parts(canonical_payload)
    from authority_agent.semantic_context import SemanticContextBuilder

    builder = SemanticContextBuilder(CommerceGovReadClient(FakeReadTransport(error=TimeoutError("read timeout"))))
    provider = StrandsSemanticProvider(context_builder=builder, agent_factory=lambda _tools: FakeAgent(output()))
    with pytest.raises(SemanticProviderFailure, match="semantic_provider_failed"):
        provider.assess(event)


@pytest.mark.parametrize(
    "agent",
    [
        FakeAgent(output(classification="NO_ACTION_REQUIRED")),
        FakeAgent(None),
        FakeAgent(error=RuntimeError("bedrock unavailable")),
    ],
)
def test_p0_deterministic_boundary_survives_p1_output_and_failures(canonical_payload, agent) -> None:
    _event, provider, _captured = provider_for(canonical_payload, agent)
    processor = AuthorityProcessor(
        bindings=TenantBindingRegistry([("demo-agency", "demo-shop.myshopify.com")]),
        ledger=InMemoryIdempotencyLedger(),
        semantic_provider=provider,
    )
    response = processor.process(canonical_payload)
    assert response.status_code == 200
    assert response.body["intelligence_classification"] == "AUTHORITY_AT_RISK"
    assert response.body["status"] == "HUMAN_AUTHORITY_REQUIRED"
    assert response.body["recommended_operator_action"] != "APPLY"
