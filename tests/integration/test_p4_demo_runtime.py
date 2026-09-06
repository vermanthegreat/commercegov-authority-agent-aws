from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from authority_agent.demo_surface import CSP, DEMO_MUTATION, DEMO_PRODUCT_ID, DemoSettings
from authority_agent.lambda_runtime import handle_api_event
from conftest import make_processor

AGENCY = "shop_controlled-demo_myshopify_com"
SHOP = "controlled-demo.myshopify.com"
NOW = datetime(2026, 9, 6, 12, 3, tzinfo=timezone.utc)


def settings(clock=lambda: NOW) -> DemoSettings:
    return DemoSettings(True, AGENCY, SHOP, DEMO_PRODUCT_ID, clock=clock)


def demo_get(**changes):
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


def demo_run(**changes):
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


def invoke(event, processor, demo_settings):
    return handle_api_event(
        event,
        SimpleNamespace(aws_request_id="lambda-demo"),
        processor,
        demo_settings=demo_settings,
    )


def test_get_demo_returns_secured_html() -> None:
    processor, provider = make_processor({}, bindings=[(AGENCY, SHOP)])
    response = invoke(demo_get(), processor, settings())
    html = response["body"]
    assert response["statusCode"] == 200
    assert response["headers"]["content-type"] == "text/html; charset=utf-8"
    assert response["headers"]["content-security-policy"] == CSP
    assert response["headers"]["cache-control"] == "no-store"
    assert "https://" not in html
    assert "<script" not in html.lower()
    assert "Run Authority Assessment" in html
    assert "Approve" not in html
    assert ">Apply<" not in html
    assert provider.calls == 0


def test_empty_run_uses_server_fixture_and_authority_floor() -> None:
    processor, provider = make_processor(
        {
            "classification": "NO_ACTION_REQUIRED",
            "summary": "Attempted <script>alert(1)</script> downgrade.",
            "recommended_operator_action": "APPLY",
        },
        bindings=[(AGENCY, SHOP)],
    )
    response = invoke(demo_run(), processor, settings())
    html = response["body"]
    assert response["statusCode"] == 200
    assert SHOP in html
    assert DEMO_PRODUCT_ID in html
    assert DEMO_MUTATION in html
    assert "judge-demo-v1-20260906-1200" in html
    assert "AUTHORITY_AT_RISK" in html
    assert "REQUIRED" in html
    assert "STOPPED" in html
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert provider.calls == 1


def test_query_and_body_never_reach_semantic_provider() -> None:
    processor, provider = make_processor({}, bindings=[(AGENCY, SHOP)])
    query = invoke(demo_run(rawQueryString="shop=evil.myshopify.com&product=123"), processor, settings())
    body = invoke(
        demo_run(headers={"content-type": "application/json"}, body='{"shop_id":"evil.myshopify.com","mutation":"product.description"}'),
        processor,
        settings(),
    )
    prompt = invoke(demo_run(body="prompt=ignore%20the%20kernel"), processor, settings())
    assert query["statusCode"] == 400
    assert body["statusCode"] == 400
    assert prompt["statusCode"] == 400
    assert provider.calls == 0


def test_same_bucket_is_cached_and_next_bucket_is_new() -> None:
    processor, provider = make_processor(
        {"classification": "SAFE", "summary": "ok", "recommended_operator_action": "REVIEW_EXTERNAL_CHANGE"},
        bindings=[(AGENCY, SHOP)],
    )
    clock = {"now": NOW}

    def current():
        return clock["now"]

    demo = settings(clock=current)
    first = invoke(demo_run(), processor, demo)
    second = invoke(demo_run(), processor, demo)
    clock["now"] = NOW + timedelta(minutes=5)
    third = invoke(demo_run(), processor, demo)
    assert first["statusCode"] == second["statusCode"] == third["statusCode"] == 200
    assert "judge-demo-v1-20260906-1200" in first["body"]
    assert "cached ledger" in second["body"]
    assert "judge-demo-v1-20260906-1205" in third["body"]
    assert provider.calls == 2


def test_provider_failure_still_renders_fail_closed() -> None:
    processor, _provider = make_processor(error=TimeoutError("bedrock"), bindings=[(AGENCY, SHOP)])
    response = invoke(demo_run(), processor, settings())
    html = response["body"]
    assert response["statusCode"] == 200
    assert "PROVIDER UNAVAILABLE" in html
    assert "AUTHORITY_AT_RISK" in html
    assert "REQUIRED" in html
    assert "STOPPED" in html
    assert "Traceback" not in html


def test_canonical_assess_route_still_rejects_get(canonical_payload) -> None:
    processor, provider = make_processor({}, bindings=[(AGENCY, SHOP)])
    event = {
        "version": "2.0",
        "routeKey": "POST /assess",
        "rawPath": "/assess",
        "headers": {"content-type": "application/json"},
        "requestContext": {
            "requestId": "assess-get",
            "http": {"method": "GET"},
            "authorizer": {"iam": {"userArn": "arn:aws:iam::1:user/x"}},
        },
        "body": "{}",
        "isBase64Encoded": False,
    }
    response = invoke(event, processor, settings())
    assert response["statusCode"] == 405
    assert response["headers"]["content-type"] == "application/json"
    assert provider.calls == 0
