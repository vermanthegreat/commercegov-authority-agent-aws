from __future__ import annotations

from types import SimpleNamespace

import pytest

from authority_agent.inbound_auth import (
    BearerAuthError,
    SecretsManagerBearerAuthenticator,
    StaticBearerAuthenticator,
)


def test_missing_and_malformed_authorization_are_rejected() -> None:
    auth = StaticBearerAuthenticator("expected-token")
    with pytest.raises(BearerAuthError, match="bearer_authorization_required") as missing:
        auth.authenticate({})
    assert missing.value.status_code == 401
    with pytest.raises(BearerAuthError, match="bearer_authorization_required"):
        auth.authenticate({"authorization": "Basic expected-token"})
    with pytest.raises(BearerAuthError, match="bearer_authorization_required"):
        auth.authenticate({"authorization": "Bearer"})


def test_wrong_bearer_is_rejected_without_leaking_secret() -> None:
    auth = StaticBearerAuthenticator("expected-token")
    with pytest.raises(BearerAuthError, match="bearer_authorization_invalid") as wrong:
        auth.authenticate({"Authorization": "Bearer other-token"})
    assert wrong.value.status_code == 401
    assert "expected-token" not in str(wrong.value)
    assert "other-token" not in str(wrong.value)


def test_matching_bearer_is_accepted_case_insensitive_header() -> None:
    StaticBearerAuthenticator("expected-token").authenticate(
        {"AUTHORIZATION": "Bearer expected-token"}
    )


def test_secrets_manager_loads_raw_secret_once() -> None:
    calls: list[str] = []

    class Client:
        def get_secret_value(self, SecretId: str) -> dict[str, str]:
            calls.append(SecretId)
            return {"SecretString": "hosted-token"}

    auth = SecretsManagerBearerAuthenticator(Client(), "arn:secret")
    auth.authenticate({"authorization": "Bearer hosted-token"})
    auth.authenticate({"authorization": "Bearer hosted-token"})
    assert calls == ["arn:secret"]


def test_secrets_manager_json_token_and_fetch_failure() -> None:
    class JsonClient:
        def get_secret_value(self, SecretId: str) -> dict[str, str]:
            return {"SecretString": '{"token":"json-token"}'}

    SecretsManagerBearerAuthenticator(JsonClient(), "arn:secret").authenticate(
        {"authorization": "Bearer json-token"}
    )

    class FailingClient:
        def get_secret_value(self, SecretId: str) -> dict[str, str]:
            raise RuntimeError("denied")

    with pytest.raises(BearerAuthError, match="inbound_bearer_unavailable") as failed:
        SecretsManagerBearerAuthenticator(FailingClient(), "arn:secret").authenticate(
            {"authorization": "Bearer json-token"}
        )
    assert failed.value.status_code == 503
    assert "json-token" not in str(failed.value)
