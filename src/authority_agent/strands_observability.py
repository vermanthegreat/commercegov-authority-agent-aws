"""Allowlisted Strands lifecycle logs. No prompts, transcripts, or tool bodies."""

from __future__ import annotations

from contextvars import ContextVar
from time import monotonic
from typing import Any
import json
import logging
import re

from pydantic import ValidationError

from strands.hooks import HookProvider, HookRegistry
from strands.hooks.events import (
    AfterInvocationEvent,
    AfterModelCallEvent,
    AfterToolCallEvent,
    BeforeInvocationEvent,
    BeforeModelCallEvent,
    BeforeToolCallEvent,
)

LOGGER = logging.getLogger("authority_agent.strands")
LOGGER.setLevel(logging.INFO)
_CORRELATION: ContextVar[dict[str, str]] = ContextVar("strands_correlation", default={})


def bind_semantic_correlation(**fields: str) -> Any:
    current = dict(_CORRELATION.get())
    for key, value in fields.items():
        if value:
            current[str(key)] = str(value)
    return _CORRELATION.set(current)


def reset_semantic_correlation(token: Any) -> None:
    _CORRELATION.reset(token)


def _truncate_failure_message(message: object) -> str:
    text = str(message)
    text = re.sub(r"input_value=.*?(?=\s*input_type=)", "input_value=<redacted> ", text, flags=re.S)
    text = re.sub(r"input_value=('[^']*'|\"[^\"]*\")", "input_value=<redacted>", text)
    if text.count("{") + text.count("}") > 80:
        stripped = text.split("{", 1)[0].strip()
        text = stripped or "structured_output_failure"
    if len(text) > 300:
        return text[:300]
    return text


def _extract_stop_reason(exc: BaseException, explicit: str | None = None) -> str | None:
    if explicit:
        return explicit
    candidates = [exc, getattr(exc, "__cause__", None), getattr(exc, "__context__", None)]
    pattern = re.compile(r"stop_reason:\s*([A-Za-z_]+)")
    for candidate in candidates:
        if candidate is None:
            continue
        match = pattern.search(str(candidate))
        if match:
            return match.group(1)
        for arg in getattr(candidate, "args", ()):
            if isinstance(arg, str):
                match = pattern.search(arg)
                if match:
                    return match.group(1)
    return None


def _content_block_types(content: list[Any] | None) -> list[str]:
    if not content:
        return []
    block_types: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if "toolUse" in block:
            block_types.append("toolUse")
        elif "text" in block:
            block_types.append("text")
        elif "toolResult" in block:
            block_types.append("toolResult")
        elif "reasoningContent" in block:
            block_types.append("reasoningContent")
        elif "citationsContent" in block:
            block_types.append("citationsContent")
        else:
            block_types.append("unknown")
    return block_types


def _log_structured_output_failure(
    exc: BaseException,
    *,
    content: list[Any] | None = None,
    stop_reason: str | None = None,
    schema_validation_reached: bool = False,
    schema_error: ValidationError | None = None,
) -> None:
    block_types = _content_block_types(content)
    payload: dict[str, Any] = {
        "message": "strands_lifecycle",
        "stage": "structured_output_failed",
        "success": False,
        **_CORRELATION.get(),
        "exception_class": exc.__class__.__name__,
        "exception_message": _truncate_failure_message(exc),
        "stop_reason": _extract_stop_reason(exc, stop_reason),
        "content_block_types": block_types,
        "tool_use_present": "toolUse" in block_types,
        "text_present": "text" in block_types,
        "schema_validation_reached": schema_validation_reached,
    }
    cause = exc.__cause__
    if cause is not None:
        payload["cause_class"] = cause.__class__.__name__
        payload["cause_message"] = _truncate_failure_message(cause)
    context = exc.__context__
    if context is not None and context is not cause:
        payload["context_class"] = context.__class__.__name__
        payload["context_message"] = _truncate_failure_message(context)
    if schema_error is not None:
        payload["schema_error_class"] = schema_error.__class__.__name__
        payload["schema_error_path"] = [
            ".".join(str(part) for part in item.get("loc", ()))
            for item in schema_error.errors()
            if item.get("loc")
        ]
    LOGGER.info(json.dumps(payload, sort_keys=True, default=str))


def _safe_log(stage: str, *, success: bool | None = None, duration_ms: int | None = None, **fields: Any) -> None:
    payload: dict[str, Any] = {"message": "strands_lifecycle", "stage": stage, **_CORRELATION.get()}
    if success is not None:
        payload["success"] = success
    if duration_ms is not None:
        payload["duration_ms"] = duration_ms
    for key, value in fields.items():
        if value in (None, ""):
            continue
        lowered = str(key).lower()
        if any(part in lowered for part in ("prompt", "transcript", "argument", "output", "body", "token", "secret", "authorization")):
            continue
        payload[key] = value
    LOGGER.info(json.dumps(payload, sort_keys=True, default=str))


def _tool_name(event: Any) -> str | None:
    selected = getattr(event, "selected_tool", None)
    name = getattr(selected, "tool_name", None) or getattr(selected, "name", None)
    if isinstance(name, str) and name:
        return name
    tool_use = getattr(event, "tool_use", None)
    if isinstance(tool_use, dict):
        raw = tool_use.get("name")
        if isinstance(raw, str) and raw:
            return raw
    return None


class SafeStrandsHooks(HookProvider):
    """Records agent/model/tool start-complete-fail metadata only."""

    def __init__(self) -> None:
        self._started: dict[str, float] = {}

    def register_hooks(self, registry: HookRegistry) -> None:
        registry.add_callback(BeforeInvocationEvent, self._agent_started)
        registry.add_callback(AfterInvocationEvent, self._agent_completed)
        registry.add_callback(BeforeModelCallEvent, self._model_started)
        registry.add_callback(AfterModelCallEvent, self._model_completed)
        registry.add_callback(BeforeToolCallEvent, self._tool_started)
        registry.add_callback(AfterToolCallEvent, self._tool_completed)

    def _agent_started(self, event: BeforeInvocationEvent) -> None:
        self._started["agent"] = monotonic()
        _safe_log("agent_started")

    def _agent_completed(self, event: AfterInvocationEvent) -> None:
        started = self._started.pop("agent", None)
        duration = None if started is None else round((monotonic() - started) * 1000)
        failed = getattr(event, "exception", None) is not None or getattr(event, "error", None) is not None
        _safe_log("agent_failed" if failed else "agent_completed", success=not failed, duration_ms=duration)

    def _model_started(self, event: BeforeModelCallEvent) -> None:
        self._started["model"] = monotonic()
        _safe_log("model_started")

    def _model_completed(self, event: AfterModelCallEvent) -> None:
        started = self._started.pop("model", None)
        duration = None if started is None else round((monotonic() - started) * 1000)
        failed = getattr(event, "exception", None) is not None or getattr(event, "error", None) is not None
        _safe_log("model_failed" if failed else "model_completed", success=not failed, duration_ms=duration)

    def _tool_started(self, event: BeforeToolCallEvent) -> None:
        self._started["tool"] = monotonic()
        _safe_log("tool_started", tool_name=_tool_name(event))

    def _tool_completed(self, event: AfterToolCallEvent) -> None:
        started = self._started.pop("tool", None)
        duration = None if started is None else round((monotonic() - started) * 1000)
        failed = getattr(event, "exception", None) is not None or getattr(event, "error", None) is not None
        _safe_log(
            "tool_failed" if failed else "tool_completed",
            success=not failed,
            duration_ms=duration,
            tool_name=_tool_name(event),
        )
