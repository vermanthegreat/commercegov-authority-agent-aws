from authority_agent.lambda_runtime import handle_api_event
from authority_agent.prompt_demo_surface import review_workspace_url, render_prompt_page
from authority_agent.prompt_presets import (
    ALLOWED_PROPOSED_TITLE,
    ATTEMPT_APPLY,
    ATTEMPT_APPROVAL,
    FORBIDDEN_PROPOSED_TITLE,
    PRESET_ORDER,
    PRESETS,
    SCENARIO_FIXTURES,
)
from authority_agent.prompt_runtime import AGENT_AUTHORITY
from authority_agent.scenario_identity import (
    AUTHORITY_PRODUCT_ID,
    CANONICAL_AGENCY,
    CANONICAL_SHOP,
    TITLE_MAX_LENGTH,
    pinned_product_id,
)
from conftest import make_processor
from tests.unit.test_prompt_demo_surface import get_event
from authority_agent.demo_surface import DemoSettings


def test_allowed_proposal_resolves_aws_judge_authority_product() -> None:
    assert CANONICAL_SHOP == "commercegov-aws-judge.myshopify.com"
    assert AUTHORITY_PRODUCT_ID == "9253164613795"
    assert pinned_product_id("AWS Authority Demo Snowboard") == "9253164613795"
    assert "7972360355917" != AUTHORITY_PRODUCT_ID


def test_policy_preset_uses_aws_judge_product_id() -> None:
    from authority_agent.scenario_identity import POLICY_PRODUCT_ID

    assert POLICY_PRODUCT_ID == "9253164646563"
    assert POLICY_PRODUCT_ID in PRESETS["FORBIDDEN_PROPOSAL"]
    assert AUTHORITY_PRODUCT_ID in PRESETS["ALLOWED_PROPOSAL"]


def test_all_presets_share_canonical_shop_and_review_link() -> None:
    assert PRESET_ORDER == (
        "ALLOWED_PROPOSAL",
        "FORBIDDEN_PROPOSAL",
        "ATTEMPT_APPROVAL",
        "ATTEMPT_APPLY",
    )
    html = render_prompt_page(shop_id=CANONICAL_SHOP)
    review = review_workspace_url(CANONICAL_SHOP)
    assert review == (
        f"https://app.commercegov.io/control-plane"
        f"?shop={CANONICAL_SHOP}&shop_id={CANONICAL_SHOP}&tab=review&stage=review"
    )
    assert f"shop={CANONICAL_SHOP}" in html
    assert CANONICAL_SHOP == "commercegov-aws-judge.myshopify.com"
    assert "controlled-demo.myshopify.com" not in html
    for name in PRESET_ORDER:
        assert name in PRESETS
    assert SCENARIO_FIXTURES["ALLOWED_PROPOSAL"].target_title
    assert SCENARIO_FIXTURES["FORBIDDEN_PROPOSAL"].target_title
    assert AGENT_AUTHORITY == "PROPOSE_ONLY"
    assert "<proposal_id>" in ATTEMPT_APPROVAL
    assert "<proposal_id>" in ATTEMPT_APPLY
    assert len(FORBIDDEN_PROPOSED_TITLE) > TITLE_MAX_LENGTH
    assert len(ALLOWED_PROPOSED_TITLE) <= TITLE_MAX_LENGTH


def test_agent_page_does_not_follow_demo_settings_shop_fallback() -> None:
    settings = DemoSettings(
        enabled=True,
        agency_id=CANONICAL_AGENCY,
        shop_id="controlled-demo.myshopify.com",
        product_id="7887756099661",
    )
    result = handle_api_event(
        get_event(),
        None,
        make_processor(),
        demo_settings=settings,
    )
    body = result["body"]
    assert CANONICAL_SHOP in body
    assert "controlled-demo.myshopify.com" not in body
