"""Real Strands/Bedrock semantic provider behind the P0 advisory protocol."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from threading import Event
from time import monotonic
import json
from typing import Any, Callable, Literal, Protocol, cast

from botocore.config import Config

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from strands import Agent
from strands._async import run_async
from strands.event_loop import streaming
from strands.models import BedrockModel
from strands.tools import convert_pydantic_to_tool_spec
from strands.types.exceptions import StructuredOutputException
from strands.types.tools import ToolChoice

from authority_agent.contracts import AuthorityEvent, SemanticAssessment
from authority_agent.semantic_context import ReadOnlyToolRegistry, SemanticContextBuilder
from authority_agent.strands_observability import (
    SafeStrandsHooks,
    _log_structured_output_failure,
    _safe_log,
    bind_semantic_correlation,
    reset_semantic_correlation,
)

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

    def structured_output(self, output_model: type[BaseModel], prompt: str | None = None) -> Any:
        ...


AgentFactory = Callable[[list[Any]], AgentLike]


def _default_agent_factory(
    *, model_id: str, region_name: str | None, timeout_seconds: float
) -> AgentFactory:
    read_timeout = max(1, int(timeout_seconds))

    def build(tools: list[Any]) -> AgentLike:
        model = BedrockModel(
            model_id=model_id,
            region_name=region_name,
            boto_client_config=Config(
                connect_timeout=5,
                read_timeout=read_timeout,
                retries={"max_attempts": 1},
            ),
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
            hooks=[SafeStrandsHooks()],
        )

    return build


def _normalize_structured_result(agent_result: Any) -> SemanticAssessmentSchema:
    if isinstance(agent_result, SemanticAssessmentSchema):
        return agent_result
    output = getattr(agent_result, "structured_output", None)
    return SemanticAssessmentSchema.model_validate(output)


async def _one_shot_structured_assessment_async(agent: AgentLike, prompt: str) -> SemanticAssessmentSchema:
    model = getattr(agent, "model", None)
    stream = getattr(model, "stream", None)
    if model is None or not callable(stream):
        structured_output = getattr(agent, "structured_output", None)
        if callable(structured_output):
            result = structured_output(SemanticAssessmentSchema, prompt)
        else:
            result = agent(prompt, structured_output_model=SemanticAssessmentSchema)
        return _normalize_structured_result(result)

    tool_spec = convert_pydantic_to_tool_spec(SemanticAssessmentSchema)
    system_prompt = getattr(agent, "system_prompt", None)
    messages = [{"role": "user", "content": [{"text": prompt}]}]
    content: list[Any] | None = None
    stop_reason: str | None = None
    schema_validation_reached = False
    try:
        response = stream(
            messages=messages,
            tool_specs=[tool_spec],
            system_prompt=system_prompt,
            tool_choice=cast(ToolChoice, {"any": {}}),
        )
        stop_event = None
        async for event in streaming.process_stream(response):
            if "stop" in event:
                stop_event = event
        if stop_event is None:
            raise ValueError("structured_output_missing_stop_event")
        stop_reason, message, _, _ = stop_event["stop"]
        content = message.get("content", [])
        output_response: dict[str, Any] | None = None
        for block in content:
            if block.get("toolUse") and block["toolUse"]["name"] == tool_spec["name"]:
                output_response = block["toolUse"]["input"]
                break
        if output_response is None:
            raise ValueError(
                f"Model returned stop_reason: {stop_reason} without SemanticAssessmentSchema tool_use."
            )
        if not isinstance(output_response, dict):
            raise ValueError("structured_output_tool_input_not_object")
        payload = dict(output_response)
        summary = payload.get("summary")
        if isinstance(summary, str) and len(summary) > 1000:
            payload["summary"] = summary[:1000]
        schema_validation_reached = True
        return SemanticAssessmentSchema.model_validate(payload)
    except ValidationError as exc:
        _log_structured_output_failure(
            exc,
            content=content,
            stop_reason=stop_reason,
            schema_validation_reached=schema_validation_reached,
            schema_error=exc,
        )
        raise SemanticProviderFailure("invalid_structured_semantic_output") from exc
    except SemanticProviderFailure:
        raise
    except Exception as exc:
        _log_structured_output_failure(
            exc,
            content=content,
            stop_reason=stop_reason,
            schema_validation_reached=schema_validation_reached,
        )
        raise SemanticProviderFailure("invalid_structured_semantic_output") from exc


def _one_shot_structured_assessment(agent: AgentLike, prompt: str) -> SemanticAssessmentSchema:
    return run_async(lambda: _one_shot_structured_assessment_async(agent, prompt))


def _invoke_structured_agent(agent: AgentLike, prompt: str) -> SemanticAssessmentSchema:
    started = monotonic()
    _safe_log("agent_started")
    _safe_log("model_started")
    try:
        result = _one_shot_structured_assessment(agent, prompt)
    except SemanticProviderFailure:
        duration_ms = round((monotonic() - started) * 1000)
        _safe_log("model_failed", success=False, duration_ms=duration_ms)
        _safe_log("agent_failed", success=False, duration_ms=duration_ms)
        raise
    except Exception:
        duration_ms = round((monotonic() - started) * 1000)
        _safe_log("model_failed", success=False, duration_ms=duration_ms)
        _safe_log("agent_failed", success=False, duration_ms=duration_ms)
        raise
    duration_ms = round((monotonic() - started) * 1000)
    _safe_log("model_completed", success=True, duration_ms=duration_ms)
    _safe_log("agent_completed", success=True, duration_ms=duration_ms)
    return result


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
            model_id=model_id,
            region_name=region_name,
            timeout_seconds=timeout_seconds,
        )
        self._timeout_seconds = timeout_seconds

    def assess(self, event: AuthorityEvent) -> SemanticAssessment:
        token = bind_semantic_correlation(event_id=event.event_id, model_id=self.model_id)
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
            abandoned = Event()
            executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="strands-p1")
            future = executor.submit(_invoke_structured_agent, agent, prompt)
            try:
                validated = future.result(timeout=self._timeout_seconds)
            except FutureTimeoutError as exc:
                abandoned.set()
                future.cancel()
                raise SemanticProviderTimeout("bedrock_semantic_timeout") from exc
            finally:
                # Python threads cannot be forcibly killed. A late Bedrock/Strands
                # worker may still finish; its result is never applied to this request.
                executor.shutdown(wait=False, cancel_futures=True)
            if abandoned.is_set():
                raise SemanticProviderTimeout("bedrock_semantic_timeout")
        except SemanticProviderFailure:
            raise
        except (StructuredOutputException, ValidationError) as exc:
            raise SemanticProviderFailure("invalid_structured_semantic_output") from exc
        except Exception as exc:
            raise SemanticProviderFailure("semantic_provider_failed") from exc
        finally:
            reset_semantic_correlation(token)
        return SemanticAssessment(
            classification=validated.classification,
            summary=validated.summary,
            recommended_operator_action=validated.recommended_operator_action,
            confidence=validated.confidence,
        )
