"""Bedrock/Strands structured-intent extraction for the judge prompt page."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from threading import Event
from time import monotonic
from typing import Any, Callable, Literal, Protocol, get_args, cast
import json

from botocore.config import Config
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from strands import Agent
from strands._async import run_async
from strands.event_loop import streaming
from strands.models import BedrockModel
from strands.tools import convert_pydantic_to_tool_spec
from strands.types.exceptions import StructuredOutputException
from strands.types.tools import ToolChoice

from authority_agent.strands_observability import (
    SafeStrandsHooks,
    _log_structured_output_failure,
    _safe_log,
    bind_semantic_correlation,
    reset_semantic_correlation,
)
from authority_agent.strands_provider import (
    DEFAULT_BEDROCK_MODEL_ID,
    SemanticProviderFailure,
    SemanticProviderTimeout,
)

PROMPT_SYSTEM_INSTRUCTION = """You extract the operator's PRIMARY requested action as structured intent.
You do not approve, apply, mutate production, grant authority, call HTTP, or request credentials.

Choose exactly one action:
- PROPOSE: the user asks to create, prepare, or propose a commerce change. Use PROPOSE even if they also ask to find a product, inspect current values, or check policy first. Lookup and policy checks are execution steps, not the action.
- APPROVE: the user asks to approve an existing CommerceGov proposal.
- APPLY: the user asks to apply or execute an existing proposal to production.
- OTHER: only when the user did not request PROPOSE, APPROVE, or APPLY.

When action is PROPOSE you MUST populate these extraction fields:
- product_query: the exact product title the user named. If the user said "exact title" or quoted a title, copy that title verbatim. Do not substitute a similar or partial product name.
- mutation_class: product.title for title, product.description for description, product.meta_title or product.meta_description when those are requested
- proposed_value: the exact replacement value the user specified. If the user quoted the value, copy the quoted text without surrounding quotation marks. Do not paraphrase, shorten, or invent a different value. Do not leave proposed_value empty when the user named a replacement. Do not put the replacement only in summary.

When the user asked to PROPOSE but did not name a concrete replacement value, leave proposed_value empty so the host can fail closed.

When action is APPROVE or APPLY, populate proposal_id and leave product_query, mutation_class, and proposed_value empty.

Examples:
- "Find the product with the exact title X and propose changing its title to Y" → action=PROPOSE, product_query=X, mutation_class=product.title, proposed_value=Y
- "Find X and propose changing its title to Y" → action=PROPOSE, product_query=X, mutation_class=product.title, proposed_value=Y
- "Find X and propose changing its description to Y" → action=PROPOSE, product_query=X, mutation_class=product.description, proposed_value=Y
- "Propose a change that may violate policy" → action=PROPOSE, and still extract any named product, field, and replacement value
- "Approve CommerceGov proposal 123" → action=APPROVE, proposal_id=123
- "Apply CommerceGov proposal 123 to production" → action=APPLY, proposal_id=123
- "Summarize what CommerceGov does" → action=OTHER

Deterministic host code validates the extracted fields and decides whether a proposal may be created."""

PromptAction = Literal["PROPOSE", "APPROVE", "APPLY", "OTHER"]
ALLOWED_PROMPT_MUTATION_CLASSES = frozenset(
    {
        "product.title",
        "product.description",
        "product.meta_title",
        "product.meta_description",
    }
)
_CANONICAL_PROMPT_ACTIONS = frozenset(get_args(PromptAction))


class PromptIntent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    action: PromptAction = Field(
        description=(
            "PRIMARY requested authority action. PROPOSE when the user asks to create or "
            "propose a commerce change, even if lookup or policy checking is also requested. "
            "APPROVE when the user asks to approve an existing proposal. APPLY when the user "
            "asks to apply a proposal to production. OTHER only when none of those actions "
            "is requested. Lookup/read is not the action when it is only a step toward PROPOSE, "
            "APPROVE, or APPLY."
        )
    )
    summary: str = Field(min_length=1, max_length=1000)
    product_query: str = Field(
        default="",
        description=(
            "Required for PROPOSE: the exact product title named by the user. "
            "Copy quoted or exact-title text verbatim. Empty for APPROVE, APPLY, or OTHER."
        ),
    )
    mutation_class: str = Field(
        default="",
        description=(
            "Required for PROPOSE: the governed field being changed. Use product.title for title, "
            "product.description for description, product.meta_title or product.meta_description "
            "when those are requested. Empty for APPROVE, APPLY, or OTHER."
        ),
    )
    proposed_value: str = Field(
        default="",
        description=(
            "Required for PROPOSE when the user named a replacement: the exact new value. "
            "Copy quoted replacement text without surrounding quotation marks. Do not paraphrase. "
            "Empty when the user did not name a value, and empty for APPROVE, APPLY, or OTHER."
        ),
    )
    proposal_id: str = Field(
        default="",
        description="Required for APPROVE and APPLY: the existing proposal id. Empty otherwise.",
    )

    @field_validator("action", mode="before")
    @classmethod
    def _canonicalize_action(cls, value: Any) -> Any:
        if isinstance(value, str):
            token = value.strip().upper()
            if token in _CANONICAL_PROMPT_ACTIONS:
                return token
        return value

    @field_validator("mutation_class", "product_query", "proposal_id", mode="before")
    @classmethod
    def _normalize_optional_text(cls, value: Any) -> str:
        if value is None:
            return ""
        return value

    @field_validator("proposed_value", mode="before")
    @classmethod
    def _normalize_proposed_value(cls, value: Any) -> str:
        if value is None:
            return ""
        text = str(value).strip()
        if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
            return text[1:-1].strip()
        return text


_STRING_INTENT_FIELDS = (
    "product_query",
    "mutation_class",
    "proposed_value",
    "proposal_id",
)


def prompt_intent_tool_spec() -> dict[str, Any]:
    """Bedrock Converse tool spec. Optional strings are primitive required strings, not enum/null unions."""
    spec = convert_pydantic_to_tool_spec(PromptIntent)
    _force_string_intent_fields(spec)
    return spec


def _force_string_intent_fields(node: Any) -> None:
    if isinstance(node, dict):
        properties = node.get("properties")
        if isinstance(properties, dict):
            required = node.get("required")
            if not isinstance(required, list):
                required = []
                node["required"] = required
            for name in _STRING_INTENT_FIELDS:
                schema = properties.get(name)
                if isinstance(schema, dict):
                    schema.pop("enum", None)
                    schema.pop("anyOf", None)
                    schema.pop("oneOf", None)
                    schema.pop("default", None)
                    schema["type"] = "string"
                    if name not in required:
                        required.append(name)
        for value in node.values():
            _force_string_intent_fields(value)
        return
    if isinstance(node, list):
        for item in node:
            _force_string_intent_fields(item)


class PromptInterpreter(Protocol):
    def interpret(
        self,
        *,
        prompt: str,
        policy_context: dict[str, Any] | None,
        run_id: str,
    ) -> PromptIntent:
        ...


AgentFactory = Callable[[], Any]


def _default_prompt_agent_factory(
    *, model_id: str, region_name: str | None, timeout_seconds: float
) -> AgentFactory:
    read_timeout = max(1, int(timeout_seconds))

    def build() -> Any:
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
            tools=[],
            system_prompt=PROMPT_SYSTEM_INSTRUCTION,
            callback_handler=None,
            load_tools_from_directory=False,
            hooks=[SafeStrandsHooks()],
        )

    return build


def _bound_intent_text(value: Any, *, limit: int = 200) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit]


def _log_extracted_intent(
    intent: PromptIntent,
    *,
    extracted_keys: list[str] | None = None,
    proposed_value_present: bool | None = None,
) -> None:
    _safe_log(
        "intent_extracted",
        action=intent.action,
        mutation_class=intent.mutation_class,
        target_query=_bound_intent_text(intent.product_query),
        proposed_value=_bound_intent_text(intent.proposed_value),
        proposal_id=_bound_intent_text(intent.proposal_id, limit=64),
        extracted_keys=",".join(extracted_keys or []),
        proposed_value_present=proposed_value_present,
    )


def _intent_from_payload(payload: Any) -> PromptIntent:
    raw = dict(payload) if isinstance(payload, dict) else {}
    keys = sorted(str(key) for key in raw.keys())
    intent = PromptIntent.model_validate(payload)
    _log_extracted_intent(
        intent,
        extracted_keys=keys,
        proposed_value_present="proposed_value" in raw,
    )
    return intent


def _normalize_intent(agent_result: Any) -> PromptIntent:
    if isinstance(agent_result, PromptIntent):
        _log_extracted_intent(agent_result, proposed_value_present=bool(agent_result.proposed_value))
        return agent_result
    output = getattr(agent_result, "structured_output", None)
    return _intent_from_payload(output)


async def _one_shot_structured_intent_async(agent: Any, prompt: str) -> PromptIntent:
    model = getattr(agent, "model", None)
    stream = getattr(model, "stream", None)
    if model is None or not callable(stream):
        structured_output = getattr(agent, "structured_output", None)
        if callable(structured_output):
            result = structured_output(PromptIntent, prompt)
        else:
            result = agent(prompt, structured_output_model=PromptIntent)
        return _normalize_intent(result)

    tool_spec = prompt_intent_tool_spec()
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
                f"Model returned stop_reason: {stop_reason} without PromptIntent tool_use."
            )
        if not isinstance(output_response, dict):
            raise ValueError("structured_output_tool_input_not_object")
        payload = dict(output_response)
        summary = payload.get("summary")
        if isinstance(summary, str) and len(summary) > 1000:
            payload["summary"] = summary[:1000]
        schema_validation_reached = True
        return _intent_from_payload(payload)
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


def _invoke_structured_intent(agent: Any, prompt: str) -> PromptIntent:
    started = monotonic()
    _safe_log("agent_started")
    _safe_log("model_started")
    try:
        result = run_async(lambda: _one_shot_structured_intent_async(agent, prompt))
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


class StrandsPromptInterpreter:
    """Real Strands/Bedrock interpreter. No HTTP mutation tools."""

    def __init__(
        self,
        *,
        agent_factory: AgentFactory | None = None,
        model_id: str = DEFAULT_BEDROCK_MODEL_ID,
        region_name: str | None = None,
        timeout_seconds: float = 20.0,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("invalid_semantic_timeout")
        self.model_id = model_id
        self._agent_factory = agent_factory or _default_prompt_agent_factory(
            model_id=model_id,
            region_name=region_name,
            timeout_seconds=timeout_seconds,
        )
        self._timeout_seconds = timeout_seconds

    def interpret(
        self,
        *,
        prompt: str,
        policy_context: dict[str, Any] | None,
        run_id: str,
    ) -> PromptIntent:
        token = bind_semantic_correlation(event_id=run_id, model_id=self.model_id)
        try:
            agent = self._agent_factory()
            payload = json.dumps(
                {
                    "operator_prompt": prompt,
                    "effective_policy": policy_context or {},
                },
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            )
            abandoned = Event()
            executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="strands-prompt")
            future = executor.submit(_invoke_structured_intent, agent, payload)
            try:
                intent = future.result(timeout=self._timeout_seconds)
            except FutureTimeoutError as exc:
                abandoned.set()
                future.cancel()
                raise SemanticProviderTimeout("bedrock_semantic_timeout") from exc
            finally:
                executor.shutdown(wait=False, cancel_futures=True)
            if abandoned.is_set():
                raise SemanticProviderTimeout("bedrock_semantic_timeout")
            return intent
        except SemanticProviderFailure:
            raise
        except (StructuredOutputException, ValidationError) as exc:
            raise SemanticProviderFailure("invalid_structured_semantic_output") from exc
        except Exception as exc:
            raise SemanticProviderFailure("semantic_provider_failed") from exc
        finally:
            reset_semantic_correlation(token)
