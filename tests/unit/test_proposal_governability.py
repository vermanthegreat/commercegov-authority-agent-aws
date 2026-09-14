from __future__ import annotations

import json
from typing import Any, Mapping

import httpx
import pytest

from authority_agent.commercegov_proposal import (
    CommerceGovHostAdapter,
    CommerceGovProposalError,
    HttpxCommerceGovProposalTransport,
    ProductRef,
    ProductResolutionError,
    ProposalCreateResult,
    TARGET_NOT_FOUND,
    display_governance_state,
    domain_denial_reason,
    list_stage_blocks_new_proposal,
    list_stage_is_proposal_candidate,
)
from authority_agent.commercegov_read import CommerceGovReadError
from authority_agent.prompt_demo_surface import render_prompt_page
from authority_agent.prompt_runtime import PromptRuntime
from tests.unit.test_prompt_demo_surface import (
    RecordingInterpreter,
    finish_prompt,
    propose_intent,
    run_event,
)

from authority_agent.scenario_identity import AUTHORITY_PRODUCT_ID, CANONICAL_AGENCY, CANONICAL_SHOP

SHOP = CANONICAL_SHOP
AGENCY = CANONICAL_AGENCY
APPROVED = ProductRef("7887756656717", "The Complete Snowboard", "approved")
ACTIVE = ProductRef(AUTHORITY_PRODUCT_ID, "AWS Authority Demo Snowboard", "active")


class FakeReadClient:
    def __init__(self, products: list[dict[str, str]]) -> None:
        self._products = products

    def get_title_policy(self, **kwargs: Any) -> Any:
        raise RuntimeError("unused")

    def list_products(self, shop_id: str) -> dict[str, Any]:
        return {
            "shop_id": shop_id,
            "products": self._products,
            "limit": 100,
            "offset": 0,
            "has_more": False,
        }


class RecordingProposalTransport:
    def __init__(
        self,
        *,
        result: Mapping[str, Any] | None = None,
        error: CommerceGovProposalError | None = None,
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self._result = result
        self._error = error

    def post_json(self, path: str, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        self.calls.append({"path": path, "payload": dict(payload)})
        if self._error is not None:
            raise self._error
        return dict(self._result or {})


def _summary(product: ProductRef) -> dict[str, str]:
    return {
        "product_id": product.product_id,
        "title": product.title,
        "stage": product.stage,
        "updated_at": "2026-09-12T15:50:18Z",
    }


def _adapter(
    products: list[ProductRef],
    transport: RecordingProposalTransport,
) -> CommerceGovHostAdapter:
    return CommerceGovHostAdapter(
        read_client=FakeReadClient([_summary(item) for item in products]),
        proposal_transport=transport,
        agency_id=AGENCY,
    )


def _pass_body(product: ProductRef) -> dict[str, Any]:
    return {
        "shop_id": SHOP,
        "product_id": product.product_id,
        "proposal_id": "prop-1",
        "policy_result": {"status": "pass", "violations": []},
    }


def _http_error(status: int, payload: Mapping[str, Any] | None = None) -> httpx.Response:
    request = httpx.Request(
        "POST",
        "https://app.commercegov.io/api/integration/v1/shops/s/products/p/proposals",
    )
    if payload is None:
        return httpx.Response(status, text="upstream", request=request)
    return httpx.Response(status, json=dict(payload), request=request)


@pytest.mark.parametrize(
    ("stage", "candidate", "blocked"),
    [
        ("active", True, False),
        ("review", True, False),
        ("approved", False, True),
        ("approve", False, True),
        ("applied", True, False),
        ("archived", False, True),
        ("inactive", False, True),
    ],
)
def test_list_stage_matches_commercegov_admission_sets(
    stage: str, candidate: bool, blocked: bool
) -> None:
    assert list_stage_is_proposal_candidate(stage) is candidate
    assert list_stage_blocks_new_proposal(stage) is blocked
    if blocked:
        assert display_governance_state(stage) in {"APPROVED", "ARCHIVED", "INACTIVE"}


def test_approved_exact_match_is_denied_without_proposal_post() -> None:
    transport = RecordingProposalTransport(result=_pass_body(ACTIVE))
    host = _adapter([APPROVED, ACTIVE], transport)
    runtime = PromptRuntime(
        interpreter=RecordingInterpreter(
            propose_intent(product_query="The Complete Snowboard")
        ),
        shop_id=SHOP,
        host=host,
    )
    _posted, terminal, _store, _invoker = finish_prompt(run_event("propose approved"), runtime)
    body = json.loads(terminal["body"])
    evidence = body["evidence"]
    assert transport.calls == []
    assert terminal["statusCode"] == 200
    assert body["state"] == "DENIED"
    assert body["state"] != "ERROR"
    assert evidence["action"] == "PROPOSE"
    assert "7887756656717" not in str(evidence.get("target_product") or "")
    assert evidence["decision"] == "DENIED"
    assert evidence["denial_reason"] == TARGET_NOT_FOUND
    assert evidence["agent_authority"] == "PROPOSE_ONLY"
    assert evidence["production_mutation"] == "NONE"
    assert "policy_result" not in evidence


def test_active_exact_match_posts_for_commercegov_admission() -> None:
    transport = RecordingProposalTransport(result=_pass_body(ACTIVE))
    host = _adapter([APPROVED, ACTIVE], transport)
    runtime = PromptRuntime(
        interpreter=RecordingInterpreter(
            propose_intent(product_query="AWS Authority Demo Snowboard")
        ),
        shop_id=SHOP,
        host=host,
    )
    _posted, terminal, _store, _invoker = finish_prompt(run_event("propose active"), runtime)
    body = json.loads(terminal["body"])
    assert transport.calls
    assert AUTHORITY_PRODUCT_ID in transport.calls[0]["path"]
    assert AUTHORITY_PRODUCT_ID == "9253164613795"
    assert transport.calls[0]["payload"]["changes"] == {
        "title": "AWS Authority Demo Snowboard — Governed"
    }
    assert body["state"] == "SUCCESS"
    assert body["evidence"]["proposal_id"] == "prop-1"
    assert body["evidence"]["target_product"] == (
        f"AWS Authority Demo Snowboard ({AUTHORITY_PRODUCT_ID})"
    )


def test_approved_exact_match_does_not_substitute_active_product() -> None:
    transport = RecordingProposalTransport(result=_pass_body(ACTIVE))
    host = _adapter([APPROVED, ACTIVE], transport)
    with pytest.raises(ProductResolutionError) as exc:
        host.find_product(SHOP, "The Complete Snowboard")
    assert exc.value.code == TARGET_NOT_FOUND
    runtime = PromptRuntime(
        interpreter=RecordingInterpreter(
            propose_intent(product_query="The Complete Snowboard")
        ),
        shop_id=SHOP,
        host=host,
    )
    finish_prompt(run_event("propose approved"), runtime)
    assert transport.calls == []


def test_exact_title_resolves_one_runtime_product_id() -> None:
    transport = RecordingProposalTransport(result=_pass_body(ACTIVE))
    host = _adapter([APPROVED, ACTIVE], transport)
    found = host.find_product(SHOP, "AWS Authority Demo Snowboard")
    assert found is not None
    assert found.product_id == ACTIVE.product_id
    runtime = PromptRuntime(
        interpreter=RecordingInterpreter(
            propose_intent(product_query="AWS Authority Demo Snowboard")
        ),
        shop_id=SHOP,
        host=host,
    )
    _posted, terminal, _store, _invoker = finish_prompt(run_event("exact title"), runtime)
    body = json.loads(terminal["body"])
    assert body["state"] == "SUCCESS"
    assert body["evidence"]["target_product"] == (
        f"AWS Authority Demo Snowboard ({AUTHORITY_PRODUCT_ID})"
    )
    assert transport.calls


def test_no_exact_title_match_is_target_not_found() -> None:
    transport = RecordingProposalTransport(result=_pass_body(ACTIVE))
    host = _adapter([ACTIVE], transport)
    with pytest.raises(ProductResolutionError) as exc:
        host.find_product(SHOP, "Missing Demo Snowboard")
    assert exc.value.code == TARGET_NOT_FOUND
    runtime = PromptRuntime(
        interpreter=RecordingInterpreter(
            propose_intent(product_query="Missing Demo Snowboard")
        ),
        shop_id=SHOP,
        host=host,
    )
    _posted, terminal, _store, _invoker = finish_prompt(run_event("missing"), runtime)
    body = json.loads(terminal["body"])
    assert transport.calls == []
    assert body["state"] == "DENIED"
    assert body["evidence"]["denial_reason"] == TARGET_NOT_FOUND


def test_duplicate_exact_titles_resolve_pinned_scenario_product() -> None:
    duplicate = ProductRef("9000000000002", "AWS Authority Demo Snowboard", "active")
    transport = RecordingProposalTransport(result=_pass_body(ACTIVE))
    host = _adapter([ACTIVE, duplicate], transport)
    found = host.find_product(SHOP, "AWS Authority Demo Snowboard")
    assert found is not None
    assert found.product_id == AUTHORITY_PRODUCT_ID
    runtime = PromptRuntime(
        interpreter=RecordingInterpreter(
            propose_intent(product_query="AWS Authority Demo Snowboard")
        ),
        shop_id=SHOP,
        host=host,
    )
    _posted, terminal, _store, _invoker = finish_prompt(run_event("duplicate"), runtime)
    body = json.loads(terminal["body"])
    assert body["state"] == "SUCCESS"
    assert AUTHORITY_PRODUCT_ID in transport.calls[0]["path"]
    assert "9000000000002" not in transport.calls[0]["path"]


def test_find_product_rejects_non_canonical_shop() -> None:
    host = _adapter([ACTIVE], RecordingProposalTransport(result=_pass_body(ACTIVE)))
    with pytest.raises(CommerceGovReadError) as exc:
        host.find_product("controlled-demo.myshopify.com", "AWS Authority Demo Snowboard")
    assert str(exc.value) == "scenario_shop_mismatch"


def test_partial_title_does_not_select_contains_match() -> None:
    transport = RecordingProposalTransport(result=_pass_body(ACTIVE))
    host = _adapter([ACTIVE], transport)
    with pytest.raises(ProductResolutionError) as exc:
        host.find_product(SHOP, "Snowboard")
    assert exc.value.code == TARGET_NOT_FOUND
    assert transport.calls == []


def test_422_product_not_governable_is_domain_denial_not_generic_failure() -> None:
    host = RecordingHost(product=ACTIVE)
    host.error = CommerceGovProposalError(
        "product_not_governable",
        http_status=422,
        message="Product is not governable",
    )
    runtime = PromptRuntime(
        interpreter=RecordingInterpreter(
            propose_intent(product_query="AWS Authority Demo Snowboard")
        ),
        shop_id=SHOP,
        host=host,
    )
    _posted, terminal, _store, _invoker = finish_prompt(run_event("422"), runtime)
    body = json.loads(terminal["body"])
    assert host.proposals
    assert terminal["statusCode"] == 200
    assert body["state"] == "DENIED"
    assert body["evidence"]["denial_reason"] == "PRODUCT_NOT_GOVERNABLE"
    assert body["evidence"]["decision"] == "DENIED"
    assert "policy_result" not in body["evidence"]
    assert body["evidence"]["production_mutation"] == "NONE"


def test_unexpected_5xx_stays_commercegov_proposal_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    def post(*args: Any, **kwargs: Any) -> httpx.Response:
        return _http_error(503, {"error": {"code": "internal_error", "message": "boom"}})

    monkeypatch.setattr("authority_agent.commercegov_proposal.httpx.post", post)
    transport = HttpxCommerceGovProposalTransport(
        base_url="https://app.commercegov.io", bearer_token="token"
    )
    with pytest.raises(CommerceGovProposalError) as exc:
        transport.post_json(
            "/api/integration/v1/shops/s/products/p/proposals",
            {"changes": {"title": "x"}, "idempotency_key": "abcdefgh"},
        )
    assert exc.value.code == "commercegov_proposal_failed"
    assert exc.value.http_status == 503

    host = RecordingHost(product=ACTIVE)
    host.error = CommerceGovProposalError("commercegov_proposal_failed", http_status=503)
    runtime = PromptRuntime(
        interpreter=RecordingInterpreter(
            propose_intent(product_query="AWS Authority Demo Snowboard")
        ),
        shop_id=SHOP,
        host=host,
    )
    _posted, terminal, _store, _invoker = finish_prompt(run_event("5xx"), runtime)
    body = json.loads(terminal["body"])
    assert terminal["statusCode"] == 500
    assert body["state"] == "ERROR"
    assert body["evidence"]["denial_reason"] == "commercegov_proposal_failed"


@pytest.mark.parametrize(
    ("status", "code", "message"),
    [
        (422, "product_not_governable", "Product is not governable"),
        (400, "invalid_proposal", "Invalid proposal"),
        (409, "idempotency_conflict", "Idempotency key conflict"),
        (403, "insufficient_scope", "Missing required scope"),
    ],
)
def test_transport_preserves_known_domain_errors(
    monkeypatch: pytest.MonkeyPatch, status: int, code: str, message: str
) -> None:
    def post(*args: Any, **kwargs: Any) -> httpx.Response:
        return _http_error(
            status,
            {"error": {"code": code, "message": message, "retryable": False}},
        )

    monkeypatch.setattr("authority_agent.commercegov_proposal.httpx.post", post)
    transport = HttpxCommerceGovProposalTransport(
        base_url="https://app.commercegov.io", bearer_token="token"
    )
    with pytest.raises(CommerceGovProposalError) as exc:
        transport.post_json(
            "/api/integration/v1/shops/s/products/p/proposals",
            {"changes": {"title": "x"}, "idempotency_key": "abcdefgh"},
        )
    assert exc.value.code == code
    assert exc.value.http_status == status
    assert exc.value.safe_message == message
    assert exc.value.retryable is False
    assert domain_denial_reason(code) is not None


def test_prompt_page_labels_current_state() -> None:
    html = render_prompt_page(shop_id=SHOP)
    assert "current_state:'Current state'" in html


class RecordingHost:
    def __init__(
        self,
        result: ProposalCreateResult | None = None,
        *,
        product: ProductRef | None = None,
        error: CommerceGovProposalError | None = None,
    ) -> None:
        self.result = result or ProposalCreateResult("293x", "pass", (), (product or ACTIVE).product_id)
        self.product = product if product is not None else ProductRef("gid-snowboard", "The Complete Snowboard")
        self.error = error
        self.policy_calls = 0
        self.lookups: list[str] = []
        self.proposals: list[dict] = []

    def shop_policy(self, shop_id: str) -> dict:
        self.policy_calls += 1
        return {}

    def find_product(self, shop_id: str, query: str) -> ProductRef | None:
        self.lookups.append(query)
        needle = query.casefold()
        if self.product.title.casefold() == needle or needle in self.product.title.casefold():
            return self.product
        return None

    def create_title_proposal(self, **kwargs: Any) -> ProposalCreateResult:
        self.proposals.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.result
