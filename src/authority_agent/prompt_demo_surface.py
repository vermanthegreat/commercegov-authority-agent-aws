"""Judge-facing AWS commerce agent prompt page. Capability surface only."""

from __future__ import annotations

from html import escape
import json
from typing import Any, Mapping
from urllib.parse import parse_qsl

from authority_agent.prompt_presets import PRESET_LABELS, PRESET_ORDER, PRESETS
from authority_agent.prompt_runtime import PromptRuntime
from authority_agent.scenario_identity import CANONICAL_SHOP
from authority_agent.scenario_identity import review_workspace_url as canonical_review_workspace_url
from authority_agent.prompt_run_store import (
    RUN_STATUS_RUNNING,
    PromptRunInvoker,
    PromptRunStore,
    running_evidence,
)

HTML_CONTENT_TYPE = "text/html; charset=utf-8"
JSON_CONTENT_TYPE = "application/json; charset=utf-8"
PROMPT_CSP = (
    "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
    "connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
)
MAX_PROMPT_CHARS = 8000
REVIEW_PATH = "/control-plane"
REVIEW_ORIGIN = "https://app.commercegov.io"

_HTML_HEADERS = {
    "content-type": HTML_CONTENT_TYPE,
    "cache-control": "no-store",
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "content-security-policy": PROMPT_CSP,
}
_JSON_HEADERS = {
    "content-type": JSON_CONTENT_TYPE,
    "cache-control": "no-store",
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
}


def review_workspace_url(shop_id: str) -> str:
    shop = str(shop_id or "").strip() or CANONICAL_SHOP
    if shop != CANONICAL_SHOP:
        raise ValueError("aws_judge_review_shop_mismatch")
    return canonical_review_workspace_url(CANONICAL_SHOP)


def next_actionable_proposal_id(current: str, payload: Mapping[str, Any] | None) -> str:
    """Keep the latest admitted PROPOSE success; ignore denied/error/approve/apply."""
    retained = str(current or "").strip()
    body = payload if isinstance(payload, Mapping) else {}
    evidence = body.get("evidence") if isinstance(body.get("evidence"), Mapping) else {}
    state = str(body.get("state") or "").strip().upper()
    action = str(evidence.get("action") or "").strip().upper()
    policy = str(evidence.get("policy_result") or "").strip().upper()
    proposal_id = str(evidence.get("proposal_id") or "").strip()
    if state == "SUCCESS" and action == "PROPOSE" and policy == "ALLOWED" and proposal_id:
        return proposal_id
    return retained


def should_display_policy_decision(evidence: Mapping[str, Any] | None) -> bool:
    action = str((evidence or {}).get("action") or "").strip().upper()
    return action == "PROPOSE"


def render_prompt_page(*, shop_id: str) -> str:
    options = "".join(
        f'<option value="{escape(name)}">{escape(PRESET_LABELS[name])}</option>'
        for name in PRESET_ORDER
    )
    buttons = "".join(
        f'<button type="button" class="scenario" data-preset="{escape(name)}" '
        f'data-testid="preset-{escape(name.lower().replace("_", "-"))}">'
        f"{escape(PRESET_LABELS[name])}</button>"
        for name in PRESET_ORDER
    )
    presets_json = json.dumps(PRESETS, ensure_ascii=True, separators=(",", ":"))
    review_url = review_workspace_url(shop_id)
    return (
        "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<title>AWS Commerce Agent</title><style>"
        "html,body{margin:0;background:#0f1419;color:#e8eef4;font:16px/1.45 system-ui,sans-serif}"
        "main{max-width:48rem;margin:0 auto;padding:2.25rem 1.25rem 3rem}"
        "h1{font-size:1.55rem;margin:0}"
        "p.sub{color:#9fb0c0;margin:.2rem 0 1.4rem;font-size:.95rem}"
        "label{display:block;font-size:.72rem;letter-spacing:.08em;text-transform:uppercase;"
        "color:#7d93a8;margin:0 0 .45rem}"
        "select,textarea{width:100%;box-sizing:border-box;background:#17202a;color:#e8eef4;"
        "border:1px solid #2a3a4a;border-radius:8px;padding:.7rem .8rem;font:inherit}"
        "textarea{min-height:12rem;resize:vertical;margin:0 0 1rem}"
        "button{appearance:none;border:0;background:#3d8bfd;color:#061018;font-weight:700;"
        "padding:.7rem 1.1rem;border-radius:8px;font-size:1rem;cursor:pointer}"
        "button:disabled{opacity:.55;cursor:wait}"
        "div.scenarios{display:flex;flex-wrap:wrap;gap:.5rem;margin:0 0 1rem}"
        "button.scenario{background:#243140;color:#e8eef4;border:1px solid #3d8bfd;font-weight:600}"
        "section.panel{background:#17202a;border:1px solid #2a3a4a;border-radius:10px;"
        "padding:1rem 1.1rem;margin:1.1rem 0 0}"
        "h2{font-size:.72rem;letter-spacing:.08em;text-transform:uppercase;color:#7d93a8;margin:0 0 .65rem}"
        "pre.response{white-space:pre-wrap;margin:0 0 1rem;color:#c5d4e0}"
        "dl{display:grid;grid-template-columns:11.5rem 1fr;gap:.35rem .75rem;margin:0}"
        "dt{color:#7d93a8}dd{margin:0;font-weight:600}"
        ".idle .wait,.success,.denied,.error{display:none}"
        "[data-state=idle] .idle{display:block}"
        "[data-state=running] .wait{display:block}[data-state=running] .idle{display:none}"
        "[data-state=success] .success{display:block}"
        "[data-state=denied] .denied{display:block}"
        "[data-state=error] .error{display:block}"
        ".denied h2,.denied dd.decision{color:#ffb020}"
        ".error h2{color:#ff6b6b}"
        ".success h2,dd.ok{color:#5bd39b}"
        "a{color:#8bb4ff}"
        ".note{color:#9fb0c0;font-size:.9rem;margin:.85rem 0 0}"
        "</style></head><body><main data-agent-page data-state=\"idle\">"
        "<h1>AWS Commerce Agent</h1>"
        "<p class=\"sub\">Amazon Bedrock</p>"
        "<label for=\"preset\">Scenario preset</label>"
        f"<div class=\"scenarios\">{buttons}</div>"
        f"<select id=\"preset\" data-testid=\"preset-select\"><option value=\"\">Select a preset</option>{options}</select>"
        "<p></p><label for=\"prompt\">Prompt</label>"
        "<textarea id=\"prompt\" data-testid=\"prompt-input\" maxlength=\"8000\" "
        "placeholder=\"Select a preset or enter a prompt\"></textarea>"
        "<p><button type=\"button\" id=\"send\" data-testid=\"send-to-agent\">Send to agent</button></p>"
        "<section class=\"panel\" data-testid=\"result-panel\" aria-live=\"polite\">"
        "<div class=\"idle\"><h2>Run</h2><p class=\"note\">Waiting for an explicit Send to agent.</p></div>"
        "<div class=\"wait\"><h2>Running</h2><p>Calling the AWS commerce agent.</p>"
        "<h2>System evidence</h2><dl data-evidence></dl></div>"
        "<div class=\"success\"><h2>Agent response</h2><pre class=\"response\" data-agent-response></pre>"
        "<h2>System evidence</h2><dl data-evidence></dl></div>"
        "<div class=\"denied\"><h2>Agent response</h2><pre class=\"response\" data-agent-response></pre>"
        "<h2>System evidence</h2><p class=\"note\">Authority decision. Production was not written.</p>"
        "<dl data-evidence></dl></div>"
        "<div class=\"error\"><h2>Error</h2><pre class=\"response\" data-agent-response></pre>"
        "<h2>System evidence</h2><dl data-evidence></dl></div>"
        "</section>"
        f"<p class=\"note\"><a data-testid=\"open-review\" href=\"{escape(review_url)}\">Open CommerceGov Review</a>"
        " — opens the CommerceGov Review workspace. This page does not approve, apply, or write Shopify.</p>"
        "<script>"
        f"const PRESETS={presets_json};"
        "const promptEl=document.getElementById('prompt');"
        "const presetEl=document.getElementById('preset');"
        "const sendEl=document.getElementById('send');"
        "const page=document.querySelector('[data-agent-page]');"
        "let latestActionableProposalId='';"
        "function applyPreset(id,proposalId){"
        "  let text=PRESETS[id]||'';"
        "  if(proposalId){text=text.replaceAll('<proposal_id>',proposalId);}"
        "  return text;"
        "}"
        "function nextActionableProposalId(current,body){"
        "  const ev=(body&&body.evidence)||{};"
        "  const state=String((body&&body.state)||'').toUpperCase();"
        "  const action=String(ev.action||'').toUpperCase();"
        "  const policy=String(ev.policy_result||'').toUpperCase();"
        "  const id=String(ev.proposal_id||'').trim();"
        "  if(state==='SUCCESS'&&action==='PROPOSE'&&policy==='ALLOWED'&&id){return id;}"
        "  return current||'';"
        "}"
        "presetEl.addEventListener('change',function(){"
        "  const id=presetEl.value;"
        "  if(!id){return;}"
        "  promptEl.value=applyPreset(id,latestActionableProposalId);"
        "});"
        "document.querySelectorAll('button.scenario[data-preset]').forEach(function(btn){"
        "  btn.addEventListener('click',function(){"
        "    const id=btn.getAttribute('data-preset')||'';"
        "    if(!id){return;}"
        "    presetEl.value=id;"
        "    promptEl.value=applyPreset(id,latestActionableProposalId);"
        "  });"
        "});"
        "function evidenceRows(ev){"
        "  const labels={aws_run_id:'AWS run id',target_product:'Target product',"
        "    requested_mutation:'Requested mutation',action:'Action',current_state:'Current state',"
        "    policy_result:'Policy decision',"
        "    decision:'Decision',proposal_id:'Proposal',agent_authority:'Agent authority',"
        "    required_authority:'Required authority',production_mutation:'Production write',"
        "    status:'Status',denial_reason:'Denial reason'};"
        "  const action=String((ev&&ev.action)||'').toUpperCase();"
        "  return Object.keys(labels).map(function(key){"
        "    if(key==='policy_result'&&action!=='PROPOSE'){return '';}"
        "    if(!ev||ev[key]==null||ev[key]===''){return '';}"
        "    const cls=key==='policy_result'||key==='decision'?\" class='decision'\":\"\";"
        "    return '<dt>'+labels[key]+'</dt><dd'+cls+'>'+String(ev[key]).replace(/[&<>]/g,function(ch){"
        "      return ch==='&'?'&amp;':ch==='<'?'&lt;':'&gt;';})+'</dd>';"
        "  }).join('');"
        "}"
        "function show(state,payload){"
        "  page.setAttribute('data-state',state);"
        "  const block=page.querySelector('.'+ (state==='running'?'wait':state));"
        "  if(!block||!payload){return;}"
        "  const response=block.querySelector('[data-agent-response]');"
        "  if(response){response.textContent=payload.agent_response||'';}"
        "  const dl=block.querySelector('[data-evidence]');"
        "  if(dl){dl.innerHTML=evidenceRows(payload.evidence||{});}"
        "}"
        "function showTerminal(body){"
        "  latestActionableProposalId=nextActionableProposalId(latestActionableProposalId,body||{});"
        "  const state=String(body.state||'ERROR').toLowerCase();"
        "  show(state==='success'||state==='denied'||state==='error'?state:'error',body);"
        "}"
        "function poll(runId,started){"
        "  if(Date.now()-started>120000){"
        "    show('error',{agent_response:'The agent request timed out.',"
        "      evidence:{aws_run_id:runId,agent_authority:'PROPOSE_ONLY',"
        "        production_mutation:'NONE',denial_reason:'prompt_run_poll_timeout'}});"
        "    return Promise.resolve();"
        "  }"
        "  return fetch('agent/run/'+encodeURIComponent(runId))"
        "  .then(function(res){return res.json();})"
        "  .then(function(body){"
        "    const state=String((body&&body.state)||'ERROR').toLowerCase();"
        "    if(state==='running'){"
        "      show('running',body||{});"
        "      return new Promise(function(resolve){setTimeout(resolve,1500);})"
        "        .then(function(){return poll(runId,started);});"
        "    }"
        "    showTerminal(body||{});"
        "  });"
        "}"
        "sendEl.addEventListener('click',function(){"
        "  const prompt=promptEl.value;"
        "  if(!prompt.trim()){return;}"
        "  sendEl.disabled=true;"
        "  show('running',null);"
        "  fetch('agent/run',{method:'POST',headers:{'content-type':'application/json'},"
        "    body:JSON.stringify({prompt:prompt})})"
        "  .then(function(res){return res.json();})"
        "  .then(function(body){"
        "    const state=String((body&&body.state)||'ERROR').toLowerCase();"
        "    const runId=body&&body.evidence&&body.evidence.aws_run_id;"
        "    if(state==='running'&&runId){"
        "      show('running',body);"
        "      return poll(String(runId),Date.now());"
        "    }"
        "    showTerminal(body||{});"
        "  })"
        "  .catch(function(){show('error',{agent_response:'The agent request failed.',evidence:{}});})"
        "  .finally(function(){sendEl.disabled=false;});"
        "});"
        "</script></main></body></html>"
    )


def _html_response(status_code: int, body: str) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": dict(_HTML_HEADERS),
        "body": body,
        "isBase64Encoded": False,
    }


def _json_response(status_code: int, body: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": dict(_JSON_HEADERS),
        "body": json.dumps(dict(body), sort_keys=True, separators=(",", ":")),
        "isBase64Encoded": False,
    }


def _route(event: Mapping[str, Any]) -> tuple[str, str]:
    request_context = event.get("requestContext") if isinstance(event.get("requestContext"), Mapping) else {}
    http = request_context.get("http") if isinstance(request_context, Mapping) else {}
    method = str(http.get("method") or "") if isinstance(http, Mapping) else ""
    route_key = str(event.get("routeKey") or "")
    path = str(event.get("rawPath") or "").rstrip("/")
    return method, route_key or f"{method} {path}"


def handle_prompt_demo_request(
    event: Mapping[str, Any],
    runtime: PromptRuntime | None,
    *,
    shop_id: str,
    enabled: bool,
    store: PromptRunStore | None = None,
    invoker: PromptRunInvoker | None = None,
) -> dict[str, Any]:
    if not enabled:
        return _html_response(404, "<!DOCTYPE html><html><body>Demo is not enabled.</body></html>")
    method, route_key = _route(event)
    path = str(event.get("rawPath") or "")
    is_get = route_key == "GET /agent" or (method == "GET" and path.rstrip("/").endswith("/agent"))
    is_status = _is_run_status_request(method, route_key, path)
    is_run = route_key == "POST /agent/run" or (method == "POST" and path.endswith("/agent/run"))
    if is_get:
        return _html_response(200, render_prompt_page(shop_id=shop_id))
    if is_status:
        return _status_response(event, store)
    if not is_run:
        return _json_response(405, {"state": "ERROR", "agent_response": "", "evidence": {}})
    if runtime is None:
        return _json_response(
            503,
            {
                "state": "ERROR",
                "agent_response": "",
                "evidence": {"denial_reason": "prompt_runtime_unavailable"},
            },
        )
    if store is None or invoker is None:
        return _json_response(
            503,
            {
                "state": "ERROR",
                "agent_response": "",
                "evidence": {"denial_reason": "prompt_run_store_unavailable"},
            },
        )
    prompt = _read_prompt(event)
    if prompt is None:
        return _json_response(
            400,
            {"state": "ERROR", "agent_response": "", "evidence": {"denial_reason": "invalid_prompt_body"}},
        )
    request_context = event.get("requestContext") if isinstance(event.get("requestContext"), Mapping) else {}
    run_id = str(request_context.get("requestId") or "") if isinstance(request_context, Mapping) else ""
    if not run_id.strip():
        return _json_response(
            500,
            {"state": "ERROR", "agent_response": "", "evidence": {"denial_reason": "missing_aws_run_id"}},
        )
    record = store.create_running(run_id, prompt)
    if str(record.get("status") or "") == RUN_STATUS_RUNNING:
        invoker.start(run_id=run_id, prompt=prompt)
    return _run_payload(202, record)


def execute_stored_prompt_run(
    run_id: str,
    runtime: PromptRuntime | None,
    store: PromptRunStore,
) -> dict[str, Any] | None:
    record = store.get(run_id)
    if record is None:
        return None
    if str(record.get("status") or "") != RUN_STATUS_RUNNING:
        return record
    if runtime is None:
        return store.complete(
            run_id,
            state="ERROR",
            agent_response="",
            evidence={**running_evidence(run_id), "denial_reason": "prompt_runtime_unavailable"},
        )
    result = runtime.execute(prompt=str(record.get("prompt") or ""), run_id=run_id)
    evidence = dict(result.evidence)
    evidence["status"] = result.state
    return store.complete(
        run_id,
        state=result.state,
        agent_response=result.agent_response,
        evidence=evidence,
    )


def _is_run_status_request(method: str, route_key: str, path: str) -> bool:
    if method != "GET":
        return False
    if "{runId}" in route_key or "{run_id}" in route_key:
        return True
    parts = path.rstrip("/").split("/")
    return len(parts) >= 2 and parts[-2] == "run" and "agent" in parts


def _status_run_id(event: Mapping[str, Any]) -> str:
    params = event.get("pathParameters") if isinstance(event.get("pathParameters"), Mapping) else {}
    if isinstance(params, Mapping):
        token = str(params.get("runId") or params.get("run_id") or "").strip()
        if token:
            return token
    path = str(event.get("rawPath") or "").rstrip("/")
    return path.rsplit("/", 1)[-1].strip()


def _status_response(event: Mapping[str, Any], store: PromptRunStore | None) -> dict[str, Any]:
    if store is None:
        return _json_response(
            503,
            {
                "state": "ERROR",
                "agent_response": "",
                "evidence": {"denial_reason": "prompt_run_store_unavailable"},
            },
        )
    run_id = _status_run_id(event)
    record = store.get(run_id)
    if record is None:
        return _json_response(
            404,
            {
                "state": "ERROR",
                "agent_response": "",
                "evidence": {**running_evidence(run_id), "denial_reason": "prompt_run_not_found"},
            },
        )
    status = 200
    if str(record.get("status") or "") == "ERROR":
        status = 500
    elif str(record.get("status") or "") == RUN_STATUS_RUNNING:
        status = 202
    return _run_payload(status, record)


def _run_payload(status_code: int, record: Mapping[str, Any]) -> dict[str, Any]:
    state = str(record.get("status") or "ERROR")
    evidence = dict(record.get("evidence") or {})
    evidence.setdefault("status", state)
    return _json_response(
        status_code,
        {
            "state": state,
            "agent_response": str(record.get("agent_response") or ""),
            "evidence": evidence,
        },
    )


def _read_prompt(event: Mapping[str, Any]) -> str | None:
    raw_body = event.get("body")
    if raw_body in (None, ""):
        return None
    if not isinstance(raw_body, str):
        return None
    text = raw_body
    if event.get("isBase64Encoded"):
        import base64

        try:
            text = base64.b64decode(raw_body, validate=True).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return None
    headers = event.get("headers") if isinstance(event.get("headers"), Mapping) else {}
    content_type = ""
    if isinstance(headers, Mapping):
        content_type = str(headers.get("content-type") or headers.get("Content-Type") or "")
    media = content_type.split(";", 1)[0].strip().lower()
    if media == "application/x-www-form-urlencoded":
        fields = dict(parse_qsl(text, keep_blank_values=True))
        prompt = fields.get("prompt")
        return _clip_prompt(prompt) if isinstance(prompt, str) else None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, Mapping):
        return None
    prompt = payload.get("prompt")
    if not isinstance(prompt, str):
        return None
    return _clip_prompt(prompt)


def _clip_prompt(prompt: str) -> str:
    return prompt[:MAX_PROMPT_CHARS]
