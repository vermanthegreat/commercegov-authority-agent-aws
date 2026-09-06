from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import logging
from typing import Any

import pytest
from botocore.exceptions import ClientError

from authority_agent.oauth_credentials import (
    CommerceGovOAuthCredentialManager,
    OAUTH_CLIENT_ID,
    OAUTH_SCOPES,
    OAUTH_SECRET_SCHEMA,
    OAuthCredentialError,
    OAuthSecretEnvelope,
)


NOW = datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc)
SECRET_ARN = "arn:aws:secretsmanager:us-east-1:123456789012:secret:commercegov-read"


def envelope_json(
    *,
    access_token: str = "access-old",
    refresh_token: str = "refresh-old",
    expires_at: datetime | None = None,
    scopes: list[str] | None = None,
    subject: str = "subject-1",
    client_id: str = OAUTH_CLIENT_ID,
    generation: int = 1,
    extra: dict[str, Any] | None = None,
) -> str:
    payload: dict[str, Any] = {
        "schema_version": OAUTH_SECRET_SCHEMA,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_at": (expires_at or NOW + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        "token_type": "Bearer",
        "scopes": scopes or sorted(OAUTH_SCOPES),
        "subject": subject,
        "client_id": client_id,
        "generation": generation,
    }
    if extra:
        payload.update(extra)
    return json.dumps(payload)


class FakeSecrets:
    def __init__(self, secret_string: str) -> None:
        self.secret_string = secret_string
        self.get_calls = 0
        self.put_calls: list[dict[str, Any]] = []

    def get_secret_value(self, **kwargs: Any) -> dict[str, Any]:
        assert kwargs["SecretId"] == SECRET_ARN
        self.get_calls += 1
        return {"SecretString": self.secret_string}

    def put_secret_value(self, **kwargs: Any) -> dict[str, Any]:
        assert kwargs["SecretId"] == SECRET_ARN
        assert kwargs["ClientRequestToken"]
        self.put_calls.append(dict(kwargs))
        self.secret_string = kwargs["SecretString"]
        return {"VersionId": kwargs["ClientRequestToken"]}


class FakeLeaseTable:
    def __init__(self, *, fail_puts: int = 0) -> None:
        self.fail_puts = fail_puts
        self.put_calls: list[dict[str, Any]] = []
        self.update_calls: list[dict[str, Any]] = []

    def put_item(self, **kwargs: Any) -> dict[str, Any]:
        self.put_calls.append(dict(kwargs))
        if self.fail_puts > 0:
            self.fail_puts -= 1
            raise ClientError(
                {"Error": {"Code": "ConditionalCheckFailedException", "Message": "busy"}},
                "PutItem",
            )
        return {}

    def get_item(self, **kwargs: Any) -> dict[str, Any]:
        return {}

    def update_item(self, **kwargs: Any) -> dict[str, Any]:
        self.update_calls.append(dict(kwargs))
        return {}


class FakeResponse:
    def __init__(self, status_code: int, payload: dict[str, Any]) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict[str, Any]:
        return dict(self._payload)


def refresh_payload(
    *,
    access_token: str = "access-new",
    refresh_token: str | None = "refresh-new",
    scope: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": 3600,
        "scope": scope or " ".join(sorted(OAUTH_SCOPES)),
    }
    if refresh_token is not None:
        payload["refresh_token"] = refresh_token
    return payload


def manager(
    secrets: FakeSecrets,
    table: FakeLeaseTable,
    *,
    http_post,
    sleeper=lambda _: None,
) -> CommerceGovOAuthCredentialManager:
    return CommerceGovOAuthCredentialManager(
        base_url="https://app.commercegov.io",
        secret_arn=SECRET_ARN,
        secrets_client=secrets,
        lease_table=table,
        clock=lambda: NOW,
        owner_factory=lambda: "11111111-1111-4111-8111-111111111111",
        http_post=http_post,
        sleeper=sleeper,
        refresh_skew_seconds=120,
        contention_attempts=3,
    )


def test_strict_secret_envelope_accepts_exact_authority() -> None:
    parsed = OAuthSecretEnvelope.from_secret_string(envelope_json())
    assert parsed.client_id == OAUTH_CLIENT_ID
    assert frozenset(parsed.scopes) == OAUTH_SCOPES
    assert parsed.subject == "subject-1"


@pytest.mark.parametrize(
    "secret",
    [
        envelope_json(extra={"unexpected": "field"}),
        envelope_json(scopes=["shops:read", "products:read"]),
        envelope_json(client_id="other-client"),
        envelope_json(subject=""),
    ],
)
def test_secret_envelope_rejects_authority_or_schema_drift(secret: str) -> None:
    with pytest.raises(OAuthCredentialError) as exc:
        OAuthSecretEnvelope.from_secret_string(secret)
    assert exc.value.code == "invalid_oauth_secret_envelope"


def test_fresh_token_does_not_refresh() -> None:
    secrets = FakeSecrets(envelope_json(expires_at=NOW + timedelta(minutes=10)))
    table = FakeLeaseTable()
    calls = []

    def post(*args: Any, **kwargs: Any) -> FakeResponse:
        calls.append((args, kwargs))
        return FakeResponse(200, refresh_payload())

    mgr = manager(secrets, table, http_post=post)
    assert mgr.access_token() == "access-old"
    assert calls == []
    assert secrets.put_calls == []


def test_near_expiry_refreshes_and_rotates_refresh_token() -> None:
    secrets = FakeSecrets(envelope_json(expires_at=NOW + timedelta(seconds=30)))
    table = FakeLeaseTable()
    calls: list[dict[str, Any]] = []

    def post(url: str, **kwargs: Any) -> FakeResponse:
        calls.append({"url": url, **kwargs})
        return FakeResponse(200, refresh_payload())

    mgr = manager(secrets, table, http_post=post)
    assert mgr.access_token() == "access-new"
    assert len(calls) == 1
    assert calls[0]["url"] == "https://app.commercegov.io/oauth/integration/token"
    assert calls[0]["data"] == {
        "grant_type": "refresh_token",
        "client_id": OAUTH_CLIENT_ID,
        "refresh_token": "refresh-old",
    }
    stored = OAuthSecretEnvelope.from_secret_string(secrets.secret_string)
    assert stored.access_token == "access-new"
    assert stored.refresh_token == "refresh-new"
    assert stored.generation == 2
    assert frozenset(stored.scopes) == OAUTH_SCOPES


def test_missing_rotated_refresh_token_preserves_current_refresh_token() -> None:
    secrets = FakeSecrets(envelope_json(expires_at=NOW + timedelta(seconds=30)))
    table = FakeLeaseTable()

    mgr = manager(
        secrets,
        table,
        http_post=lambda *args, **kwargs: FakeResponse(
            200, refresh_payload(refresh_token=None)
        ),
    )
    assert mgr.access_token() == "access-new"
    stored = OAuthSecretEnvelope.from_secret_string(secrets.secret_string)
    assert stored.refresh_token == "refresh-old"


@pytest.mark.parametrize(
    "scope",
    [
        "shops:read products:read",
        "shops:read products:read policy:read proposals:write",
    ],
)
def test_refresh_rejects_scope_change(scope: str) -> None:
    secrets = FakeSecrets(envelope_json(expires_at=NOW + timedelta(seconds=30)))
    table = FakeLeaseTable()
    mgr = manager(
        secrets,
        table,
        http_post=lambda *args, **kwargs: FakeResponse(
            200, refresh_payload(scope=scope)
        ),
    )
    with pytest.raises(OAuthCredentialError) as exc:
        mgr.access_token()
    assert exc.value.code == "oauth_refresh_contract_invalid"
    assert secrets.put_calls == []


def test_refresh_rejected_fails_closed_without_secret_write() -> None:
    secrets = FakeSecrets(envelope_json(expires_at=NOW + timedelta(seconds=30)))
    table = FakeLeaseTable()
    mgr = manager(
        secrets,
        table,
        http_post=lambda *args, **kwargs: FakeResponse(400, {"error": "invalid_grant"}),
    )
    with pytest.raises(OAuthCredentialError) as exc:
        mgr.access_token()
    assert exc.value.code == "oauth_refresh_rejected"
    assert secrets.put_calls == []


def test_contention_reconciles_when_another_generation_advances() -> None:
    secrets = FakeSecrets(envelope_json(expires_at=NOW + timedelta(seconds=30)))
    table = FakeLeaseTable(fail_puts=1)

    def sleeper(_: float) -> None:
        secrets.secret_string = envelope_json(
            access_token="access-from-other",
            refresh_token="refresh-from-other",
            expires_at=NOW + timedelta(hours=1),
            generation=2,
        )

    mgr = manager(
        secrets,
        table,
        http_post=lambda *args, **kwargs: pytest.fail("refresh provider should not be called"),
        sleeper=sleeper,
    )
    assert mgr.access_token() == "access-from-other"


def test_lease_contains_no_credential_material() -> None:
    secrets = FakeSecrets(envelope_json(expires_at=NOW + timedelta(seconds=30)))
    table = FakeLeaseTable()
    mgr = manager(
        secrets,
        table,
        http_post=lambda *args, **kwargs: FakeResponse(200, refresh_payload()),
    )
    assert mgr.access_token() == "access-new"
    serialized = json.dumps(table.put_calls + table.update_calls)
    assert "access-old" not in serialized
    assert "access-new" not in serialized
    assert "refresh-old" not in serialized
    assert "refresh-new" not in serialized


def test_refresh_logs_do_not_contain_credentials(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    secrets = FakeSecrets(envelope_json(expires_at=NOW + timedelta(seconds=30)))
    table = FakeLeaseTable()
    mgr = manager(
        secrets,
        table,
        http_post=lambda *args, **kwargs: FakeResponse(200, refresh_payload()),
    )
    assert mgr.access_token() == "access-new"
    log_text = "\n".join(record.getMessage() for record in caplog.records)
    for forbidden in ("access-old", "access-new", "refresh-old", "refresh-new"):
        assert forbidden not in log_text
