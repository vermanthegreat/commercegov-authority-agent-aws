from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from typing import Any

import httpx
import pytest

from authority_agent.commercegov_read import (
    CommerceGovReadError,
    CommerceGovTokenExpiredError,
)
from authority_agent.live_read_transport import LazyHttpsCommerceGovReadTransport
from authority_agent.oauth_credentials import (
    CommerceGovOAuthCredentialManager,
    OAUTH_CLIENT_ID,
    OAUTH_SCOPES,
    OAUTH_SECRET_SCHEMA,
)


NOW = datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc)
SECRET_ARN = "arn:aws:secretsmanager:us-east-1:123456789012:secret:commercegov-read"


def secret_json(*, access_token: str, refresh_token: str, generation: int = 1) -> str:
    return json.dumps(
        {
            "schema_version": OAUTH_SECRET_SCHEMA,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": (NOW + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
            "token_type": "Bearer",
            "scopes": sorted(OAUTH_SCOPES),
            "subject": "subject-1",
            "client_id": OAUTH_CLIENT_ID,
            "generation": generation,
        }
    )


class Secrets:
    def __init__(self) -> None:
        self.secret_string = secret_json(access_token="access-old", refresh_token="refresh-old")
        self.put_calls = 0

    def get_secret_value(self, **kwargs: Any) -> dict[str, Any]:
        return {"SecretString": self.secret_string}

    def put_secret_value(self, **kwargs: Any) -> dict[str, Any]:
        self.put_calls += 1
        self.secret_string = kwargs["SecretString"]
        return {}


class Lease:
    def put_item(self, **kwargs: Any) -> dict[str, Any]:
        return {}

    def get_item(self, **kwargs: Any) -> dict[str, Any]:
        return {}

    def update_item(self, **kwargs: Any) -> dict[str, Any]:
        return {}


def response(status: int, payload: dict[str, Any]) -> httpx.Response:
    request = httpx.Request("GET", "https://app.commercegov.io/test")
    return httpx.Response(status, request=request, json=payload)


def build_manager(secrets: Secrets, refresh_calls: list[dict[str, Any]]) -> CommerceGovOAuthCredentialManager:
    def post(url: str, **kwargs: Any) -> httpx.Response:
        refresh_calls.append({"url": url, **kwargs})
        request = httpx.Request("POST", url)
        return httpx.Response(
            200,
            request=request,
            json={
                "access_token": "access-new",
                "refresh_token": "refresh-new",
                "token_type": "Bearer",
                "expires_in": 3600,
                "scope": " ".join(sorted(OAUTH_SCOPES)),
            },
        )

    return CommerceGovOAuthCredentialManager(
        base_url="https://app.commercegov.io",
        secret_arn=SECRET_ARN,
        secrets_client=secrets,
        lease_table=Lease(),
        clock=lambda: NOW,
        owner_factory=lambda: "11111111-1111-4111-8111-111111111111",
        http_post=post,
        sleeper=lambda _: None,
    )


def test_warm_transport_replaces_rejected_access_token(monkeypatch: pytest.MonkeyPatch) -> None:
    secrets = Secrets()
    refresh_calls: list[dict[str, Any]] = []
    manager = build_manager(secrets, refresh_calls)
    seen_authorization: list[str] = []

    def get(url: str, **kwargs: Any) -> httpx.Response:
        auth = kwargs["headers"]["Authorization"]
        seen_authorization.append(auth)
        if auth == "Bearer access-old":
            return response(401, {"error": {"code": "token_expired"}})
        return response(200, {"ok": True})

    monkeypatch.setattr("authority_agent.commercegov_read.httpx.get", get)
    transport = LazyHttpsCommerceGovReadTransport(
        base_url="https://app.commercegov.io",
        credential_manager=manager,
        timeout_seconds=5.0,
    )

    assert transport.get_json("/api/integration/v1/shops/demo/policy") == {"ok": True}
    assert seen_authorization == ["Bearer access-old", "Bearer access-new"]
    assert len(refresh_calls) == 1
    assert secrets.put_calls == 1

    # Same warm transport object must keep using the new generation.
    assert transport.get_json("/api/integration/v1/shops/demo/policy") == {"ok": True}
    assert seen_authorization[-1] == "Bearer access-new"
    assert seen_authorization.count("Bearer access-old") == 1


def test_token_expired_retry_is_exactly_once(monkeypatch: pytest.MonkeyPatch) -> None:
    secrets = Secrets()
    refresh_calls: list[dict[str, Any]] = []
    manager = build_manager(secrets, refresh_calls)
    get_calls = 0

    def get(url: str, **kwargs: Any) -> httpx.Response:
        nonlocal get_calls
        get_calls += 1
        return response(401, {"error": {"code": "token_expired"}})

    monkeypatch.setattr("authority_agent.commercegov_read.httpx.get", get)
    transport = LazyHttpsCommerceGovReadTransport(
        base_url="https://app.commercegov.io",
        credential_manager=manager,
    )

    with pytest.raises(CommerceGovTokenExpiredError):
        transport.get_json("/api/integration/v1/shops/demo/policy")

    assert get_calls == 2
    assert len(refresh_calls) == 1


def test_generic_401_does_not_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    secrets = Secrets()
    refresh_calls: list[dict[str, Any]] = []
    manager = build_manager(secrets, refresh_calls)

    monkeypatch.setattr(
        "authority_agent.commercegov_read.httpx.get",
        lambda *args, **kwargs: response(401, {"error": {"code": "invalid_token"}}),
    )
    transport = LazyHttpsCommerceGovReadTransport(
        base_url="https://app.commercegov.io",
        credential_manager=manager,
    )

    with pytest.raises(CommerceGovReadError) as exc:
        transport.get_json("/api/integration/v1/shops/demo/policy")

    assert exc.value.code == "commercegov_read_failed"
    assert refresh_calls == []


def test_403_does_not_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    secrets = Secrets()
    refresh_calls: list[dict[str, Any]] = []
    manager = build_manager(secrets, refresh_calls)

    monkeypatch.setattr(
        "authority_agent.commercegov_read.httpx.get",
        lambda *args, **kwargs: response(403, {"error": {"code": "insufficient_scope"}}),
    )
    transport = LazyHttpsCommerceGovReadTransport(
        base_url="https://app.commercegov.io",
        credential_manager=manager,
    )

    with pytest.raises(CommerceGovReadError) as exc:
        transport.get_json("/api/integration/v1/shops/demo/policy")

    assert exc.value.code == "commercegov_read_failed"
    assert refresh_calls == []
