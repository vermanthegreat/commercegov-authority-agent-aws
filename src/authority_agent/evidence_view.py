"""Public-safe AuthorityAssessmentEvidenceV1 projector. Presentation only."""

from __future__ import annotations

from typing import Any, Mapping

EVIDENCE_SCHEMA = "AuthorityAssessmentEvidenceV1"
SUMMARY_MAX_CHARS = 280
_FORBIDDEN_FRAGMENTS = (
    "access_token",
    "refresh_token",
    "authorization",
    "bearer ",
    "secretstring",
    "arn:aws:secretsmanager",
    "cgint_",
    "cgrfr_",
)

_PUBLIC_CONTEXT_KEYS = frozenset(
    {"context_source", "read_status", "product_context_hash", "policy_hash"}
)
_PUBLIC_SEMANTIC_KEYS = frozenset(
    {
        "semantic_provider",
        "semantic_model",
        "semantic_status",
        "semantic_classification",
        "semantic_summary",
    }
)
_PUBLIC_AUTHORITY_KEYS = frozenset(
    {
        "deterministic_classification",
        "authority_mode",
        "human_authority_required",
        "autonomous_processing",
        "terminal_status",
    }
)


def bound_semantic_summary(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    if not text:
        return None
    lowered = text.lower()
    if any(fragment in lowered for fragment in _FORBIDDEN_FRAGMENTS):
        text = "[redacted]"
    truncated = False
    if len(text) > SUMMARY_MAX_CHARS:
        text = text[: SUMMARY_MAX_CHARS].rstrip()
        truncated = True
    if truncated:
        return f"{text} [truncated]"
    return text


def _abbrev_hash(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    prefix = ""
    if text.startswith("sha256:"):
        prefix = "sha256:"
        text = text[7:]
    if len(text) <= 12:
        return f"{prefix}{text}" if prefix else text
    return f"{prefix}{text[:12]}…"


def _omit_unknown(source: Mapping[str, Any], allowed: frozenset[str]) -> dict[str, Any]:
    return {key: source[key] for key in allowed if key in source and source[key] is not None}


def project_assessment_evidence(
    *,
    body: Mapping[str, Any],
    cached: bool,
    context_evidence: Mapping[str, Any] | None = None,
    ledger_evidence: Mapping[str, Any] | None = None,
    evidence_id: str | None = None,
    execution_id: str | None = None,
    event_source: str = "judge_demo_fixture",
    product_title: str | None = None,
) -> dict[str, Any]:
    extra = dict(ledger_evidence or {})
    if isinstance(context_evidence, Mapping):
        for key, value in context_evidence.items():
            extra.setdefault(key, value)
    event_id = str(body.get("event_id") or "")
    view: dict[str, Any] = {
        "schema_version": EVIDENCE_SCHEMA,
        "event": {
            "event_id": event_id,
            "event_type": "EXTERNAL_PRODUCTION_CHANGE_DETECTED",
            "source": event_source,
            "shop": body.get("shop_id"),
            "product_id": body.get("target_id"),
            "mutation_class": body.get("mutation_class"),
        },
        "execution": {
            "source": "cached_idempotent_replay" if cached else "live_assessment",
        },
        "authority": {
            "classification": body.get("intelligence_classification"),
            "human_authority_required": True,
            "autonomous_processing": "STOP",
            "terminal_status": body.get("status"),
        },
        "evidence": {
            "durable": True,
        },
    }
    if product_title:
        view["event"]["product"] = product_title
    recorded_at = extra.get("completed_at")
    if isinstance(recorded_at, str) and recorded_at:
        view["execution"]["recorded_at"] = recorded_at
    live: dict[str, Any] = {}
    ctx = _omit_unknown(extra, _PUBLIC_CONTEXT_KEYS)
    if ctx.get("context_source"):
        live["source"] = ctx["context_source"]
    read_status = ctx.get("read_status")
    if read_status:
        live["product_read"] = read_status
        live["policy_read"] = read_status
    product_hash = _abbrev_hash(ctx.get("product_context_hash"))
    policy_hash = _abbrev_hash(ctx.get("policy_hash"))
    if product_hash:
        live["product_context_hash"] = product_hash
    if policy_hash:
        live["policy_hash"] = policy_hash
    if live:
        view["live_context"] = live
    semantic: dict[str, Any] = {}
    provider = extra.get("semantic_provider")
    if isinstance(provider, str) and provider:
        semantic["provider"] = "Strands" if "Strands" in provider else provider
    model = extra.get("semantic_model")
    if isinstance(model, str) and model:
        semantic["model"] = model
    status = extra.get("semantic_status")
    if status in {"valid", "provider_error"}:
        semantic["status"] = status
    classification = extra.get("semantic_classification")
    if isinstance(classification, str) and classification:
        semantic["classification"] = classification
    summary = bound_semantic_summary(extra.get("semantic_summary"))
    if summary:
        semantic["summary"] = summary
    if semantic:
        view["semantic"] = semantic
    authority_extra = _omit_unknown(extra, _PUBLIC_AUTHORITY_KEYS)
    if "deterministic_classification" in authority_extra:
        view["authority"]["classification"] = authority_extra["deterministic_classification"]
    if "autonomous_processing" in authority_extra:
        view["authority"]["autonomous_processing"] = authority_extra["autonomous_processing"]
    if "terminal_status" in authority_extra:
        view["authority"]["terminal_status"] = authority_extra["terminal_status"]
    if evidence_id:
        view["evidence"]["evidence_id"] = evidence_id
    if execution_id:
        view["evidence"]["execution_id"] = execution_id
    return view
