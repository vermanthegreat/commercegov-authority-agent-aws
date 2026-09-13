from __future__ import annotations

import json
from types import SimpleNamespace

from authority_agent.commercegov_proposal import (
    HttpxCommerceGovProposalTransport,
    ProductRef,
    ProposalCreateResult,
    CommerceGovProposalError,
)
from authority_agent.demo_surface import DemoSettings
from authority_agent.lambda_runtime import handle_api_event
from authority_agent.prompt_demo_surface import (
    execute_stored_prompt_run,
    next_actionable_proposal_id,
    render_prompt_page,
    should_display_policy_decision,
)
from authority_agent.prompt_intent import PromptIntent
from authority_agent.prompt_presets import (
    ALLOWED_PROPOSAL,
    ALLOWED_TARGET_TITLE,
    ATTEMPT_APPLY,
    ATTEMPT_APPROVAL,
    FORBIDDEN_PROPOSAL,
    FORBIDDEN_PROPOSED_TITLE,
    SCENARIO_FIXTURES,
    apply_preset,
)
from authority_agent.prompt_runtime import PromptRuntime
from authority_agent.prompt_run_store import MemoryPromptRunStore
from conftest import make_processor

AGENCY = "shop_controlled-demo_myshopify_com"
SHOP = "controlled-demo.myshopify.com"
PRODUCT = ProductRef("gid-snowboard", "AWS Authority Demo Snowboard")


class RecordingInterpreter:
    def __init__(self, intent: PromptIntent) -> None:
        self.intent = intent
        self.calls: list[dict] = []

    def interpret(self, **kwargs):
        self.calls.append(kwargs)
        return self.intent


class RecordingHost:
    def __init__(self, result: ProposalCreateResult | None = None) -> None:
        self.result = result or ProposalCreateResult("293x", "pass", (), PRODUCT.product_id)
        self.policy_calls = 0
        self.lookups: list[str] = []
        self.proposals: list[dict] = []

    def shop_policy(self, shop_id: str) -> dict:
        self.policy_calls += 1
        return {"forbidden_terms": ["guaranteed"], "max_length": 80}

    def find_product(self, shop_id: str, query: str) -> ProductRef | None:
        self.lookups.append(query)
        if "snowboard" in query.casefold():
            return PRODUCT
        return None

    def create_title_proposal(self, **kwargs) -> ProposalCreateResult:
        self.proposals.append(kwargs)
        return self.result


def settings() -> DemoSettings:
    return DemoSettings(True, AGENCY, SHOP, "7887756099661")


class RecordingInvoker:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def start(self, *, run_id: str, prompt: str) -> None:
        self.calls.append({"run_id": run_id, "prompt": prompt})


def invoke(event, runtime=None, processor=None, store=None, invoker=None):
    proc, _provider = processor or make_processor({}, bindings=[(AGENCY, SHOP)])
    return handle_api_event(
        event,
        SimpleNamespace(aws_request_id="lambda-agent"),
        proc,
        demo_settings=settings(),
        prompt_runtime=runtime,
        prompt_run_store=store,
        prompt_run_invoker=invoker,
    )


def get_event():
    return {
        "version": "2.0",
        "routeKey": "GET /agent",
        "rawPath": "/agent",
        "rawQueryString": "",
        "headers": {},
        "requestContext": {"requestId": "agent-get", "http": {"method": "GET"}},
        "body": "",
        "isBase64Encoded": False,
    }


def run_event(prompt: str, request_id: str = "agent-run"):
    return {
        "version": "2.0",
        "routeKey": "POST /agent/run",
        "rawPath": "/agent/run",
        "rawQueryString": "",
        "headers": {"content-type": "application/json"},
        "requestContext": {"requestId": request_id, "http": {"method": "POST"}},
        "body": json.dumps({"prompt": prompt}),
        "isBase64Encoded": False,
    }


def status_event(run_id: str):
    return {
        "version": "2.0",
        "routeKey": "GET /agent/run/{runId}",
        "rawPath": f"/agent/run/{run_id}",
        "rawQueryString": "",
        "headers": {},
        "requestContext": {"requestId": f"status-{run_id}", "http": {"method": "GET"}},
        "pathParameters": {"runId": run_id},
        "body": "",
        "isBase64Encoded": False,
    }


def finish_prompt(event, runtime):
    store = MemoryPromptRunStore()
    invoker = RecordingInvoker()
    posted = invoke(event, runtime, store=store, invoker=invoker)
    body = json.loads(posted["body"])
    run_id = body["evidence"]["aws_run_id"]
    execute_stored_prompt_run(run_id, runtime, store)
    terminal = invoke(status_event(run_id), runtime, store=store, invoker=invoker)
    return posted, terminal, store, invoker


def propose_intent(**changes) -> PromptIntent:
    payload = {
        "action": "PROPOSE",
        "summary": "Propose a governed title change for human review.",
        "product_query": "AWS Authority Demo Snowboard",
        "mutation_class": "product.title",
        "proposed_value": "AWS Authority Demo Snowboard — Governed",
        "proposal_id": "",
    }
    payload.update(changes)
    return PromptIntent.model_validate(payload)


def test_presets_populate_textarea_but_do_not_execute() -> None:
    interpreter = RecordingInterpreter(propose_intent())
    runtime = PromptRuntime(interpreter=interpreter, shop_id=SHOP, host=RecordingHost())
    response = invoke(get_event(), runtime)
    html = response["body"]
    assert response["statusCode"] == 200
    assert "AWS Commerce Agent" in html
    assert "Amazon Bedrock" in html
    assert "AWS Authority Demo Snowboard" in html
    assert ">Allowed proposal<" in html
    assert ">Forbidden proposal<" in html
    assert ">Attempt approval<" in html
    assert ">Attempt apply<" in html
    assert 'data-preset="ALLOWED_PROPOSAL"' in html
    assert 'data-preset="FORBIDDEN_PROPOSAL"' in html
    assert 'data-preset="ATTEMPT_APPROVAL"' in html
    assert 'data-preset="ATTEMPT_APPLY"' in html
    assert "ALLOWED_PROPOSAL" in html
    assert "FORBIDDEN_PROPOSAL" in html
    assert "ATTEMPT_APPROVAL" in html
    assert "ATTEMPT_APPLY" in html
    assert "Send to agent" in html
    assert "promptEl.value=applyPreset" in html
    assert "button.scenario[data-preset]" in html
    assert "fetch('agent/run'" in html
    assert "fetch('agent/run/'+encodeURIComponent(runId))" in html
    assert interpreter.calls == []
    assert apply_preset("ALLOWED_PROPOSAL") == ALLOWED_PROPOSAL
    assert apply_preset("FORBIDDEN_PROPOSAL") == FORBIDDEN_PROPOSAL
    assert apply_preset("ALLOWED_PROPOSAL") != ""


def test_send_uses_real_agent_request_handler() -> None:
    interpreter = RecordingInterpreter(propose_intent())
    host = RecordingHost()
    runtime = PromptRuntime(interpreter=interpreter, shop_id=SHOP, host=host)
    posted, terminal, store, invoker = finish_prompt(run_event(ALLOWED_PROPOSAL), runtime)
    start_body = json.loads(posted["body"])
    body = json.loads(terminal["body"])
    assert posted["statusCode"] == 202
    assert start_body["state"] == "RUNNING"
    assert invoker.calls
    assert invoker.calls[0]["prompt"] == ALLOWED_PROPOSAL
    assert interpreter.calls
    assert interpreter.calls[0]["prompt"] == ALLOWED_PROPOSAL
    assert body["state"] == "SUCCESS"
    assert host.proposals


def test_allowed_proposal_result_displays_proposal_evidence() -> None:
    interpreter = RecordingInterpreter(propose_intent())
    runtime = PromptRuntime(interpreter=interpreter, shop_id=SHOP, host=RecordingHost())
    _posted, terminal, _store, _invoker = finish_prompt(
        run_event(ALLOWED_PROPOSAL, "run-42"), runtime
    )
    body = json.loads(terminal["body"])
    evidence = body["evidence"]
    assert body["state"] == "SUCCESS"
    assert evidence["proposal_id"] == "293x"
    assert evidence["policy_result"] == "ALLOWED"
    assert evidence["agent_authority"] == "PROPOSE_ONLY"
    assert evidence["production_mutation"] == "NONE"
    assert evidence["aws_run_id"] == "run-42"
    assert "AWS Authority Demo Snowboard" in evidence["target_product"]
    assert evidence["requested_mutation"] == "product.title"


def test_denied_approval_renders_as_denial_not_error() -> None:
    interpreter = RecordingInterpreter(
        propose_intent(action="APPROVE", summary="Cannot approve.", proposal_id="293x", proposed_value="")
    )
    host = RecordingHost()
    runtime = PromptRuntime(interpreter=interpreter, shop_id=SHOP, host=host)
    _posted, terminal, _store, _invoker = finish_prompt(
        run_event(ATTEMPT_APPROVAL.replace("<proposal_id>", "293x")), runtime
    )
    body = json.loads(terminal["body"])
    assert terminal["statusCode"] == 200
    assert body["state"] == "DENIED"
    assert body["state"] != "ERROR"
    assert body["evidence"]["action"] == "APPROVE"
    assert body["evidence"]["decision"] == "DENIED"
    assert body["evidence"]["required_authority"] == "HUMAN"
    assert body["evidence"]["production_mutation"] == "NONE"
    assert host.proposals == []


def test_denied_apply_renders_as_denial_not_error() -> None:
    interpreter = RecordingInterpreter(
        propose_intent(action="APPLY", summary="Cannot apply.", proposal_id="293x", proposed_value="")
    )
    host = RecordingHost()
    runtime = PromptRuntime(interpreter=interpreter, shop_id=SHOP, host=host)
    _posted, terminal, _store, _invoker = finish_prompt(
        run_event(ATTEMPT_APPLY.replace("<proposal_id>", "293x")), runtime
    )
    body = json.loads(terminal["body"])
    assert terminal["statusCode"] == 200
    assert body["state"] == "DENIED"
    assert body["evidence"]["action"] == "APPLY"
    assert body["evidence"]["decision"] == "DENIED"
    assert body["evidence"]["required_authority"] == "HUMAN"
    assert host.proposals == []


def test_no_page_route_exposes_direct_shopify_mutation() -> None:
    html = render_prompt_page(shop_id=SHOP)
    lowered = html.lower()
    assert "shopify" in lowered  # review copy may mention Shopify
    assert "/admin/api" not in lowered
    assert "graphql" not in lowered
    assert "mutate" not in lowered
    assert "button type=\"button\" id=\"send\"" in html
    assert ">Approve<" not in html
    assert ">Apply<" not in html
    from conftest import ROOT

    template = (ROOT / "template.yaml").read_text(encoding="utf-8")
    assert "Path: /agent" in template
    assert "shopify/write" not in template.lower()
    assert "admin/api" not in template.lower()
    assert "graphql" not in template.lower()
    transport = HttpxCommerceGovProposalTransport(
        base_url="https://app.commercegov.io", bearer_token="token"
    )
    try:
        transport.post_json("/api/integration/v1/shops/x/shopify/write", {"changes": {}})
        raise AssertionError("shopify write path must be rejected")
    except CommerceGovProposalError as exc:
        assert exc.code == "unapproved_commercegov_proposal_path"


def test_proposal_id_flows_into_later_approval_and_apply_presets() -> None:
    filled_approve = apply_preset("ATTEMPT_APPROVAL", "293x")
    filled_apply = apply_preset("ATTEMPT_APPLY", "293x")
    assert filled_approve == "Approve CommerceGov proposal 293x."
    assert filled_apply == "Apply CommerceGov proposal 293x to production."
    assert "<proposal_id>" not in filled_approve
    html = render_prompt_page(shop_id=SHOP)
    assert "latestActionableProposalId=nextActionableProposalId" in html
    assert "state==='SUCCESS'&&action==='PROPOSE'&&policy==='ALLOWED'" in html
    assert "lastProposalId=String(body.evidence.proposal_id)" not in html
    assert "text.replaceAll('<proposal_id>',proposalId)" in html
    assert "key==='policy_result'&&action!=='PROPOSE'" in html
    assert len(FORBIDDEN_PROPOSED_TITLE) > 70
    assert "guaranteed" not in FORBIDDEN_PROPOSED_TITLE.casefold()


def test_scenario_fixtures_bind_titles_not_shopify_ids() -> None:
    import re

    shopify_id = re.compile(r"(?:gid://shopify|\b\d{10,}\b)", re.IGNORECASE)
    allowed = SCENARIO_FIXTURES["ALLOWED_PROPOSAL"]
    forbidden = SCENARIO_FIXTURES["FORBIDDEN_PROPOSAL"]
    assert allowed.target_title == ALLOWED_TARGET_TITLE
    assert forbidden.target_title == "AWS Policy Demo Snowboard"
    assert allowed.prompt == ALLOWED_PROPOSAL
    assert forbidden.prompt == FORBIDDEN_PROPOSAL
    assert not hasattr(allowed, "product_id")
    assert not hasattr(forbidden, "product_id")
    for fixture in (allowed, forbidden):
        blob = f"{fixture.target_title}\n{fixture.prompt}"
        assert shopify_id.search(blob) is None
    html = render_prompt_page(shop_id=SHOP)
    assert apply_preset("ATTEMPT_APPROVAL", "501") == "Approve CommerceGov proposal 501."
    assert apply_preset("ATTEMPT_APPLY", "501") == (
        "Apply CommerceGov proposal 501 to production."
    )
    assert "latestActionableProposalId" in html
    assert "state==='SUCCESS'&&action==='PROPOSE'&&policy==='ALLOWED'" in html


def test_actionable_proposal_id_ignores_denied_error_and_authority_attempts() -> None:
    allowed_501 = {
        "state": "SUCCESS",
        "evidence": {"action": "PROPOSE", "policy_result": "ALLOWED", "proposal_id": "501"},
    }
    forbidden_502 = {
        "state": "DENIED",
        "evidence": {"action": "PROPOSE", "policy_result": "DENIED", "proposal_id": "502"},
    }
    allowed_503 = {
        "state": "SUCCESS",
        "evidence": {"action": "PROPOSE", "policy_result": "ALLOWED", "proposal_id": "503"},
    }
    current = next_actionable_proposal_id("", allowed_501)
    assert current == "501"
    current = next_actionable_proposal_id(current, forbidden_502)
    assert current == "501"
    assert apply_preset("ATTEMPT_APPROVAL", current) == "Approve CommerceGov proposal 501."
    assert apply_preset("ATTEMPT_APPLY", current) == (
        "Apply CommerceGov proposal 501 to production."
    )
    current = next_actionable_proposal_id(current, allowed_503)
    assert current == "503"
    current = next_actionable_proposal_id(
        current,
        {"state": "ERROR", "evidence": {"proposal_id": "999", "action": "PROPOSE"}},
    )
    assert current == "503"
    current = next_actionable_proposal_id(
        current,
        {
            "state": "DENIED",
            "evidence": {
                "action": "APPROVE",
                "decision": "DENIED",
                "proposal_id": "503",
                "policy_result": "DENIED",
            },
        },
    )
    assert current == "503"
    current = next_actionable_proposal_id(
        current,
        {
            "state": "DENIED",
            "evidence": {
                "action": "PROPOSE",
                "denial_reason": "product_not_governable",
                "proposal_id": "504",
            },
        },
    )
    assert current == "503"


def test_approve_apply_results_hide_unevaluated_policy_decision() -> None:
    assert should_display_policy_decision({"action": "PROPOSE", "policy_result": "ALLOWED"})
    assert should_display_policy_decision({"action": "PROPOSE", "policy_result": "DENIED"})
    assert not should_display_policy_decision(
        {"action": "APPROVE", "decision": "DENIED", "policy_result": "DENIED"}
    )
    assert not should_display_policy_decision(
        {"action": "APPLY", "decision": "DENIED", "policy_result": "DENIED"}
    )
    html = render_prompt_page(shop_id=SHOP)
    for label in (
        "Action",
        "Decision",
        "Proposal",
        "Agent authority",
        "Required authority",
        "Production write",
        "Denial reason",
    ):
        assert label in html


def test_policy_denied_proposal_is_denied_not_error() -> None:
    interpreter = RecordingInterpreter(propose_intent(proposed_value=FORBIDDEN_PROPOSED_TITLE))
    host = RecordingHost(ProposalCreateResult("294x", "fail", ("title_too_long",), PRODUCT.product_id))
    runtime = PromptRuntime(interpreter=interpreter, shop_id=SHOP, host=host)
    _posted, terminal, _store, _invoker = finish_prompt(run_event("forbidden"), runtime)
    body = json.loads(terminal["body"])
    assert terminal["statusCode"] == 200
    assert body["state"] == "DENIED"
    assert body["evidence"]["policy_result"] == "DENIED"
    assert body["evidence"]["proposal_id"] == "294x"
    assert body["evidence"]["denial_reason"] == "title_too_long"
    assert body["evidence"]["production_mutation"] == "NONE"
