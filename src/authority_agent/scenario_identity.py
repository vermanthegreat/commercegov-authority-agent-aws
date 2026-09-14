"""Single canonical AWS judge scenario shop/product identity.

The registered AWS judge shop is the only shop the /agent presets, proposal
host, policy lookup, and Review URL may use.
"""

from __future__ import annotations

CANONICAL_SHOP = "commercegov-aws-judge.myshopify.com"
CANONICAL_AGENCY = "shop_commercegov-aws-judge_myshopify_com"
AUTHORITY_PRODUCT_ID = "9253164613795"
POLICY_PRODUCT_ID = "7972360421453"
AUTHORITY_TITLE = "AWS Authority Demo Snowboard"
POLICY_TITLE = "AWS Policy Demo Snowboard"
ALLOWED_PROPOSED_TITLE = "AWS Authority Demo Snowboard — Governed"
FORBIDDEN_PROPOSED_TITLE = (
    "AWS Policy Demo Snowboard — This title intentionally exceeds "
    "the governed seventy character limit"
)
TITLE_MAX_LENGTH = 70

SCENARIO_PRODUCT_IDS: dict[str, str] = {
    AUTHORITY_TITLE: AUTHORITY_PRODUCT_ID,
    POLICY_TITLE: POLICY_PRODUCT_ID,
}


def review_workspace_url(shop_id: str | None = None) -> str:
    shop = str(shop_id or CANONICAL_SHOP).strip() or CANONICAL_SHOP
    if shop != CANONICAL_SHOP:
        raise ValueError("aws_judge_review_shop_mismatch")
    return (
        "https://app.commercegov.io/control-plane"
        f"?shop={CANONICAL_SHOP}&shop_id={CANONICAL_SHOP}&tab=review&stage=review"
    )


def pinned_product_id(title_query: str) -> str | None:
    needle = str(title_query or "").strip()
    return SCENARIO_PRODUCT_IDS.get(needle)
