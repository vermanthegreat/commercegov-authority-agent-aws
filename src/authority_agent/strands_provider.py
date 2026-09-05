"""Real Strands/Bedrock semantic provider behind the P0 advisory protocol."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
import json
from typing import Any, Callable, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from strands import Agent
from strands.models import BedrockModel
from strands.types.exceptions import StructuredOutputException

from authority_agent.contracts import AuthorityEvent, SemanticAssessment
from authority_agent.semantic_context import ReadOnlyToolRegistry, SemanticContextBuilder

STRANDS_VERSION = "1.54.0"
DEFAULT_BEDROCK_MODEL_ID = "global.anthropic.claude-sonnet-4-6"
SYSTEM_INSTRUCTION = """You interpret one bounded CommerceGov operational event.
Use only the provided tenant-bound read-only context. Identify apparent authority risk,
summarize why, and recommend what a human operator should inspect. You do not approve,
apply, mutate production, grant authority, or request credentials. Your output is advisory;
deterministic application code controls all authority."""


class SemanticProviderFailure(RuntimeError):
    pass


class SemanticProviderTimeout(SemanticProviderFailure):
    pass


class SemanticAssessmentSchema(BaseModel):
    """Strict model output; executable authority fields are forbidden as extras."""

    model_config = ConfigDict(extra="forbid", strict=True)

    classification: Literal[
        "NO_ACTION_REQUIRED",
        "INFORMATIONAL",
        "REVIEW_REQUIRED",
        "AUTHORITY_AT_RISK",
        "ACTION_REQUIRED",
    ]
    summary: str = Field(min_length=1, max_length=1000)
    recommended_operator_action: Literal[
        "INVESTIGATE_RISK",
        "REVIEW_EXTERNAL_CHANGE",
        "COMPARE_WITH_GOVERNED_VALUE",
        "RESTORE_GOVERNED_VALUE",
    ]
    confidence: float | None = None

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, value: float | None) -> float | None:
        # Bedrock tool schemas reject JSON Schema minimum/maximum keywords for
        # numbers. Keep the invariant in application validation instead.
        if value is not None and not 0.0 <= value <= 1.0:
            raise ValueError("confidence_out_of_range")
        return value


class AgentLike(Protocol):
    def __call__(self, prompt: str, **kwargs: Any) -> Any:
        ...


AgentFactory = Callable[[list[Any]], AgentLike]


def _default_agent_factory(
    *, model_id: str, region_name: str | None
) -> AgentFactory:
    def build(tools: list[Any]) -> AgentLike:
        model = BedrockModel(
            model_id=model_id,
            region_name=region_name,
            temperature=0.0,
            max_tokens=1600,
            streaming=False,
            strict_tools=True,
            additional_request_fields={"thinking": {"type": "disabled"}},
        )
        return Agent(
            model=model,
            tools=tools,
            system_prompt=SYSTEM_INSTRUCTION,
            callback_handler=None,
            load_tools_from_directory=False,
        )

    return build


class StrandsSemanticProvider:
    """Build minimized context, invoke Strands, and return validated advice."""

    def __init__(
        self,
        *,
        context_builder: SemanticContextBuilder,
        agent_factory: AgentFactory | None = None,
        model_id: str = DEFAULT_BEDROCK_MODEL_ID,
        region_name: str | None = None,
        timeout_seconds: float = 20.0,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("invalid_semantic_timeout")
        self._context_builder = context_builder
        self.model_id = model_id
        self._agent_factory = agent_factory or _default_agent_factory(
            model_id=model_id, region_name=region_name
        )
        self._timeout_seconds = timeout_seconds

    def assess(self, event: AuthorityEvent) -> SemanticAssessment:
        try:
            context, governance, policy = self._context_builder.build(event)
            tools = ReadOnlyToolRegistry(event, governance, policy).as_strands_tools()
            agent = self._agent_factory(tools)
            prompt = json.dumps(
                context.model_dump(mode="json"),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            )
            executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="strands-p1")
            future = executor.submit(
                agent,
                prompt,
                structured_output_model=SemanticAssessmentSchema,
            )
            try:
                agent_result = future.result(timeout=self._timeout_seconds)
            except FutureTimeoutError as exc:
                future.cancel()
                raise SemanticProviderTimeout("bedrock_semantic_timeout") from exc
            finally:
                executor.shutdown(wait=False, cancel_futures=True)
            output = getattr(agent_result, "structured_output", None)
            validated = SemanticAssessmentSchema.model_validate(output)
        except SemanticProviderFailure:
            raise
        except (StructuredOutputException, ValidationError) as exc:
            raise SemanticProviderFailure("invalid_structured_semantic_output") from exc
        except Exception as exc:
            raise SemanticProviderFailure("semantic_provider_failed") from exc
        return SemanticAssessment(
            classification=validated.classification,
            summary=validated.summary,
            recommended_operator_action=validated.recommended_operator_action,
            confidence=validated.confidence,
        )
