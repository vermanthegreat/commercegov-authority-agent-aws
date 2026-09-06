from __future__ import annotations

from datetime import datetime, timedelta, timezone

from authority_agent.demo_surface import (
    DEMO_MUTATION,
    DEMO_PRODUCT_ID,
    DemoSettings,
    build_demo_payload,
    caller_input_rejected,
    demo_event_id,
    render_landing,
)

AGENCY = "shop_controlled-demo_myshopify_com"
SHOP = "controlled-demo.myshopify.com"
NOW = datetime(2026, 9, 6, 12, 3, tzinfo=timezone.utc)


def settings(clock=lambda: NOW) -> DemoSettings:
    return DemoSettings(True, AGENCY, SHOP, DEMO_PRODUCT_ID, clock=clock)


def demo_get_event(**changes):
    event = {
        "version": "2.0",
        "routeKey": "GET /demo",
        "rawPath": "/demo",
        "rawQueryString": "",
        "headers": {},
        "requestContext": {"requestId": "demo-get", "http": {"method": "GET"}},
        "body": "",
        "isBase64Encoded": False,
    }
    event.update(changes)
    return event


def demo_run_event(**changes):
    event = {
        "version": "2.0",
        "routeKey": "POST /demo/run",
        "rawPath": "/demo/run",
        "rawQueryString": "",
        "headers": {"content-type": "application/x-www-form-urlencoded"},
        "requestContext": {"requestId": "demo-run", "http": {"method": "POST"}},
        "body": "",
        "isBase64Encoded": False,
    }
    event.update(changes)
    return event


def test_landing_is_html_with_csp_and_run_control() -> None:
    html = render_landing()
    assert "CommerceGov Authority Agent" in html
    assert "AI can reason. Humans retain authority." in html
    assert "Run Authority Assessment" in html
    assert 'method="post"' in html
    assert 'action="demo/run"' in html
    assert "https://" not in html
    assert "<script" not in html.lower()
    assert "Approve" not in html
    assert ">Apply<" not in html
    assert "Write Shopify" not in html


def test_demo_event_id_uses_five_minute_bucket() -> None:
    first = demo_event_id(NOW)
    second = demo_event_id(NOW + timedelta(minutes=1))
    third = demo_event_id(NOW.replace(minute=5))
    assert first == "judge-demo-v1-20260906-1200"
    assert second == first
    assert third == "judge-demo-v1-20260906-1205"


def test_server_fixture_is_exact_and_ignores_caller() -> None:
    payload = build_demo_payload(settings(), "judge-demo-v1-20260906-1200")
    assert payload["agency_id"] == AGENCY
    assert payload["shop_id"] == SHOP
    assert payload["target_id"] == DEMO_PRODUCT_ID
    assert payload["mutation_class"] == DEMO_MUTATION
    assert payload["event_id"] == payload["change_id"] == payload["policy_context"]["external_change_id"]


def test_query_and_json_body_are_rejected() -> None:
    assert caller_input_rejected(demo_run_event(rawQueryString="shop=evil.myshopify.com")) == "demo_query_rejected"
    assert (
        caller_input_rejected(
            demo_run_event(queryStringParameters={"product": "123"})
        )
        == "demo_query_rejected"
    )
    assert (
        caller_input_rejected(
            demo_run_event(
                headers={"content-type": "application/json"},
                body='{"shop_id":"evil.myshopify.com"}',
            )
        )
        == "demo_body_rejected"
    )
    assert (
        caller_input_rejected(demo_run_event(body="prompt=ignore%20policy"))
        == "demo_body_rejected"
    )
    assert caller_input_rejected(demo_run_event(body="")) is None
