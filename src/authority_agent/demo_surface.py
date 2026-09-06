"""Bounded public judge demo: assess, read, reason, explain, stop."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
import json
from typing import Any, Callable, Mapping
from urllib.parse import parse_qsl

from authority_agent.handler import handle_payload
from authority_agent.orchestration import AuthorityProcessor

DEMO_PRODUCT_ID = "7887756099661"
DEMO_MUTATION = "product.title"
DEMO_PRODUCT_TITLE = "Gift Card"
DEMO_EVENT_PREFIX = "judge-demo-v1"
BUCKET_MINUTES = 5
HTML_CONTENT_TYPE = "text/html; charset=utf-8"
CSP = (
    "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; "
    "base-uri 'none'; frame-ancestors 'none'; script-src 'none'"
)
_HTML_HEADERS = {
    "content-type": HTML_CONTENT_TYPE,
    "cache-control": "no-store",
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "content-security-policy": CSP,
}


@dataclass(frozen=True, slots=True)
class DemoSettings:
    enabled: bool
    agency_id: str
    shop_id: str
    product_id: str
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)


def demo_event_id(now: datetime) -> str:
    utc = now.astimezone(timezone.utc)
    bucket_minute = (utc.minute // BUCKET_MINUTES) * BUCKET_MINUTES
    bucket = utc.replace(minute=bucket_minute, second=0, microsecond=0)
    return f"{DEMO_EVENT_PREFIX}-{bucket:%Y%m%d}-{bucket:%H%M}"


def build_demo_payload(settings: DemoSettings, event_id: str) -> dict[str, Any]:
    title = DEMO_PRODUCT_TITLE
    product_id = settings.product_id
    return {
        "event_id": event_id,
        "change_id": event_id,
        "agency_id": settings.agency_id,
        "shop_id": settings.shop_id,
        "target_type": "product",
        "target_id": product_id,
        "mutation_class": DEMO_MUTATION,
        "current_value": title,
        "proposed_value": title,
        "policy_context": {
            "source": "shopify_webhook",
            "event_type": "EXTERNAL_PRODUCTION_CHANGE_DETECTED",
            "external_change_id": event_id,
            "scope_key": f"live-scope-product-{product_id}-title",
            "shopify_webhook_id": "judge-demo-webhook",
            "detected_at": "2026-09-06T00:00:00Z",
            "governed_field": "title",
            "decision_version_id": "judge-demo-decision",
            "audit_id": int(product_id),
            "review_cycle_id": "judge-demo-review",
            "expected_governed_value": title,
            "observed_shopify_value": title,
        },
        "authority_context": {
            "requires_human_approval": True,
            "authority_mode": "PROPOSE_ONLY",
            "origin": "external_production_change",
        },
    }


def _html_response(status_code: int, body: str) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": dict(_HTML_HEADERS),
        "body": body,
        "isBase64Encoded": False,
    }


def _page(title: str, inner: str) -> str:
    return (
        "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        f"<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{escape(title)}</title><style>"
        "html,body{margin:0;background:#0f1419;color:#e8eef4;font:16px/1.45 system-ui,sans-serif}"
        "main{max-width:42rem;margin:0 auto;padding:2.25rem 1.25rem 3rem}"
        "h1{font-size:1.55rem;margin:0 0 .35rem}"
        "p.lede{color:#9fb0c0;margin:0 0 1.5rem}"
        "section{background:#17202a;border:1px solid #2a3a4a;border-radius:10px;padding:1rem 1.1rem;margin:0 0 .9rem}"
        "h2{font-size:.72rem;letter-spacing:.08em;text-transform:uppercase;color:#7d93a8;margin:0 0 .65rem}"
        "dl{display:grid;grid-template-columns:9.5rem 1fr;gap:.35rem .75rem;margin:0}"
        "dt{color:#7d93a8}dd{margin:0;font-weight:600}"
        ".story{display:grid;gap:.45rem;margin:0 0 1.25rem}"
        ".story div{padding:.55rem .7rem;background:#1c2833;border-radius:8px;color:#c5d4e0;font-size:.95rem}"
        ".story b{color:#e8eef4}"
        "button{appearance:none;border:0;background:#3d8bfd;color:#061018;font-weight:700;padding:.7rem 1.1rem;"
        "border-radius:8px;font-size:1rem;cursor:pointer}"
        ".risk{color:#ffb020}.stop{color:#ff6b6b}.ok{color:#5bd39b}"
        ".note{color:#9fb0c0;font-size:.9rem;margin:.75rem 0 0}"
        "</style></head><body><main>"
        f"{inner}</main></body></html>"
    )


def render_landing() -> str:
    inner = (
        "<h1>CommerceGov Authority Agent</h1>"
        "<p class=\"lede\">AI can reason. Humans retain authority.</p>"
        "<div class=\"story\">"
        "<div>1. An operational commerce event exists.</div>"
        "<div>2. The agent <b>reads</b> live governed product and policy context.</div>"
        "<div>3. Strands / Bedrock <b>reasons</b> about the change.</div>"
        "<div>4. Deterministic controls <b>decide authority</b>.</div>"
        "<div>5. <b>Human authority is required.</b></div>"
        "<div>6. Autonomous processing <b>stops</b>.</div>"
        "</div>"
        "<section><h2>Operational Event</h2><dl>"
        "<dt>Shop</dt><dd>controlled-demo.myshopify.com</dd>"
        f"<dt>Product</dt><dd>{escape(DEMO_PRODUCT_TITLE)}</dd>"
        f"<dt>Product ID</dt><dd>{escape(DEMO_PRODUCT_ID)}</dd>"
        f"<dt>Mutation</dt><dd>{escape(DEMO_MUTATION)}</dd>"
        "</dl>"
        "<form method=\"post\" action=\"demo/run\">"
        "<p><button type=\"submit\">Run Authority Assessment</button></p>"
        "</form>"
        "<p class=\"note\">This page cannot approve, apply, write Shopify, or change policy. "
        "The target is fixed. You cannot submit an event or a prompt.</p>"
        "</section>"
    )
    return _page("CommerceGov Authority Agent", inner)


def _abbrev(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith("sha256:"):
        text = text[7:]
    return text[:12]


def _semantic_unavailable(processor: AuthorityProcessor, cached: bool) -> bool:
    if cached:
        return False
    provider = processor.semantic_provider
    if getattr(provider, "error", None) is not None:
        return True
    if getattr(provider, "last_semantic_ok", None) is False:
        return True
    return False


def render_result(
    *,
    body: Mapping[str, Any],
    cached: bool,
    processor: AuthorityProcessor,
) -> str:
    classification = str(body.get("intelligence_classification") or "")
    status = str(body.get("status") or "")
    shop = str(body.get("shop_id") or "")
    product_id = str(body.get("target_id") or "")
    mutation = str(body.get("mutation_class") or "")
    event_id = str(body.get("event_id") or "")
    extra = getattr(processor.semantic_provider, "context_evidence", None)
    context_source = ""
    read_status = ""
    product_hash = ""
    policy_hash = ""
    if not cached and isinstance(extra, Mapping):
        context_source = str(extra.get("context_source") or "")
        read_status = str(extra.get("read_status") or "")
        product_hash = _abbrev(extra.get("product_context_hash"))
        policy_hash = _abbrev(extra.get("policy_hash"))
    unavailable = _semantic_unavailable(processor, cached)
    semantic_label = "PROVIDER UNAVAILABLE" if unavailable else "PASS"
    context_rows = ""
    if context_source or read_status or product_hash or policy_hash:
        product_state = "PASS" if (read_status in {"ok", "success", ""} and context_source) or product_hash else ""
        policy_state = "PASS" if (read_status in {"ok", "success", ""} and context_source) or policy_hash else ""
        context_rows = (
            (f"<dt>Product</dt><dd class=\"ok\">{escape(product_state or read_status)}</dd>" if product_state or read_status else "")
            + (f"<dt>Policy</dt><dd class=\"ok\">{escape(policy_state or read_status)}</dd>" if policy_state or read_status else "")
            + (f"<dt>Source</dt><dd>{escape(context_source)}</dd>" if context_source else "")
            + (f"<dt>Read status</dt><dd>{escape(read_status)}</dd>" if read_status else "")
            + (f"<dt>Product hash</dt><dd>{escape(product_hash)}</dd>" if product_hash else "")
            + (f"<dt>Policy hash</dt><dd>{escape(policy_hash)}</dd>" if policy_hash else "")
        )
    else:
        context_rows = (
            "<dt>Source</dt><dd>server-owned live path</dd>"
            "<dt>Detail</dt><dd>Hashes are shown when this runtime records live read evidence.</dd>"
        )
    inner = (
        "<h1>CommerceGov Authority Agent</h1>"
        "<p class=\"lede\">AI can reason. Humans retain authority.</p>"
        "<section><h2>Operational Event</h2><dl>"
        f"<dt>Event</dt><dd>{escape(event_id)}</dd>"
        "<dt>Event type</dt><dd>EXTERNAL_PRODUCTION_CHANGE_DETECTED</dd>"
        f"<dt>Shop</dt><dd>{escape(shop)}</dd>"
        f"<dt>Product</dt><dd>{escape(DEMO_PRODUCT_TITLE)}</dd>"
        f"<dt>Product ID</dt><dd>{escape(product_id)}</dd>"
        f"<dt>Mutation</dt><dd>{escape(mutation)}</dd>"
        f"<dt>Result source</dt><dd>{escape('cached ledger' if cached else 'live assessment')}</dd>"
        "</dl></section>"
        "<section><h2>Live Context</h2><dl>"
        f"{context_rows}"
        "</dl></section>"
        "<section><h2>Strands / Bedrock</h2><dl>"
        "<dt>Provider</dt><dd>Strands</dd>"
        "<dt>Model</dt><dd>Claude Sonnet 4.6</dd>"
        f"<dt>Assessment</dt><dd>{escape(semantic_label)}</dd>"
        "</dl></section>"
        "<section><h2>Authority</h2><dl>"
        f"<dt>Classification</dt><dd class=\"risk\">{escape(classification)}</dd>"
        f"<dt>Human authority</dt><dd class=\"risk\">REQUIRED</dd>"
        f"<dt>Autonomous processing</dt><dd class=\"stop\">STOPPED</dd>"
        f"<dt>Terminal status</dt><dd>{escape(status)}</dd>"
        f"<dt>Summary</dt><dd>{escape(str(body.get('summary') or ''))}</dd>"
        "</dl></section>"
        "<section><h2>Evidence</h2><dl>"
        "<dt>Durable evidence</dt><dd>PERSISTED</dd>"
        "</dl>"
        "<form method=\"post\" action=\"\">"
        "<p><button type=\"submit\">Run Authority Assessment</button></p>"
        "</form>"
        "<p class=\"note\">No approval or Apply control is offered. Shopify is not written.</p>"
        "</section>"
    )
    return _page("CommerceGov Authority Agent — Result", inner)


def render_error(message: str) -> str:
    inner = (
        "<h1>CommerceGov Authority Agent</h1>"
        "<p class=\"lede\">AI can reason. Humans retain authority.</p>"
        "<section><h2>Assessment unavailable</h2>"
        f"<p>{escape(message)}</p>"
        "<dl>"
        "<dt>Authority</dt><dd class=\"risk\">HUMAN AUTHORITY REQUIRED</dd>"
        "<dt>Autonomous processing</dt><dd class=\"stop\">STOPPED</dd>"
        "</dl></section>"
    )
    return _page("CommerceGov Authority Agent", inner)


def caller_input_rejected(event: Mapping[str, Any]) -> str | None:
    raw_qs = str(event.get("rawQueryString") or "").strip()
    if raw_qs:
        return "demo_query_rejected"
    query = event.get("queryStringParameters")
    if isinstance(query, Mapping) and any(str(key).strip() for key in query):
        return "demo_query_rejected"
    multi = event.get("multiValueQueryStringParameters")
    if isinstance(multi, Mapping) and any(str(key).strip() for key in multi):
        return "demo_query_rejected"
    params = event.get("queryStringParameters")
    if isinstance(params, Mapping):
        for key in ("shop", "shop_id", "product", "product_id", "mutation", "agency_id"):
            if key in params:
                return "demo_query_rejected"
    raw_body = event.get("body")
    if raw_body in (None, ""):
        return None
    if not isinstance(raw_body, str):
        return "demo_body_rejected"
    text = raw_body.strip()
    if not text:
        return None
    headers = event.get("headers") if isinstance(event.get("headers"), Mapping) else {}
    content_type = ""
    if isinstance(headers, Mapping):
        content_type = str(headers.get("content-type") or headers.get("Content-Type") or "")
    media = content_type.split(";", 1)[0].strip().lower()
    if media == "application/json":
        return "demo_body_rejected"
    if text[:1] in "{[":
        return "demo_body_rejected"
    if media in ("application/x-www-form-urlencoded", "multipart/form-data") or "=" in text:
        fields = parse_qsl(text, keep_blank_values=True)
        if fields:
            return "demo_body_rejected"
    return "demo_body_rejected"


def handle_demo_request(
    event: Mapping[str, Any],
    processor: AuthorityProcessor,
    settings: DemoSettings,
) -> dict[str, Any]:
    if not settings.enabled:
        return _html_response(404, render_error("Demo is not enabled."))
    if settings.product_id != DEMO_PRODUCT_ID:
        return _html_response(500, render_error("Demo configuration is invalid."))
    route_key = str(event.get("routeKey") or "")
    request_context = event.get("requestContext") if isinstance(event.get("requestContext"), Mapping) else {}
    http = request_context.get("http") if isinstance(request_context, Mapping) else {}
    method = str(http.get("method") or "") if isinstance(http, Mapping) else ""
    if route_key == "GET /demo" or (method == "GET" and str(event.get("rawPath") or "").rstrip("/").endswith("/demo")):
        page = render_landing()
        return _html_response(200, page)
    if route_key != "POST /demo/run" and not (method == "POST" and str(event.get("rawPath") or "").endswith("/demo/run")):
        return _html_response(405, render_error("Unsupported demo route."))
    rejected = caller_input_rejected(event)
    if rejected:
        return _html_response(400, render_error("This demo does not accept caller input."))
    event_id = demo_event_id(settings.clock())
    payload = build_demo_payload(settings, event_id)
    try:
        result = handle_payload(processor, payload)
    except Exception:
        return _html_response(500, render_error("The authority runtime failed before a decision existed."))
    if result["status_code"] != 200:
        return _html_response(
            result["status_code"],
            render_error("The authority path returned a fail-closed decision."),
        )
    body = result["body"]
    if not isinstance(body, Mapping):
        return _html_response(500, render_error("The authority runtime failed before a decision existed."))
    page = render_result(body=body, cached=bool(result["cached"]), processor=processor)
    return _html_response(200, page)
