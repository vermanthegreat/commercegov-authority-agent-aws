"""CommerceGov inbound bearer checks for POST /events/operational."""

from __future__ import annotations

import hmac
import json
from typing import Any, Mapping, Protocol


class BearerAuthError(Exception):
    def __init__(self, status_code: int, code: str) -> None:
        self.status_code = status_code
        self.code = code
        super().__init__(code)


class BearerAuthenticator(Protocol):
    def authenticate(self, headers: Mapping[str, Any] | None) -> None:
        ...


def _authorization_header(headers: Mapping[str, Any] | None) -> str | None:
    if not isinstance(headers, Mapping):
        return None
    for key, value in headers.items():
        if str(key).lower() == "authorization":
            if value is None:
                return None
            return str(value)
    return None


def presented_bearer_token(headers: Mapping[str, Any] | None) -> str | None:
    raw = _authorization_header(headers)
    if raw is None:
        return None
    scheme, separator, remainder = raw.partition(" ")
    if separator != " " or scheme.lower() != "bearer":
        return None
    token = remainder.strip()
    return token or None


def _parse_secret_string(secret_string: str) -> str:
    text = secret_string.strip()
    if text.startswith("{"):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise BearerAuthError(503, "inbound_bearer_unavailable") from exc
        if isinstance(parsed, Mapping) and parsed.get("token"):
            return str(parsed["token"])
        raise BearerAuthError(503, "inbound_bearer_unavailable")
    if not text:
        raise BearerAuthError(503, "inbound_bearer_unavailable")
    return text


def secret_token_from_string(secret_string: str) -> str:
    try:
        return _parse_secret_string(secret_string)
    except BearerAuthError as exc:
        raise ValueError(exc.code) from exc


class StaticBearerAuthenticator:
    def __init__(self, expected_token: str) -> None:
        if not expected_token:
            raise ValueError("empty_inbound_bearer_secret")
        self._expected = expected_token

    def authenticate(self, headers: Mapping[str, Any] | None) -> None:
        presented = presented_bearer_token(headers)
        if presented is None:
            raise BearerAuthError(401, "bearer_authorization_required")
        if not hmac.compare_digest(presented, self._expected):
            raise BearerAuthError(401, "bearer_authorization_invalid")


class SecretsManagerBearerAuthenticator:
    def __init__(self, client: Any, secret_arn: str) -> None:
        if not secret_arn:
            raise ValueError("missing_inbound_bearer_secret_arn")
        self._client = client
        self._secret_arn = secret_arn
        self._cached: str | None = None

    def _load_expected(self) -> str:
        if self._cached is not None:
            return self._cached
        response = self._client.get_secret_value(SecretId=self._secret_arn)
        secret_string = response.get("SecretString")
        if not isinstance(secret_string, str):
            raise BearerAuthError(503, "inbound_bearer_unavailable")
        expected = _parse_secret_string(secret_string)
        self._cached = expected
        return expected

    def authenticate(self, headers: Mapping[str, Any] | None) -> None:
        try:
            expected = self._load_expected()
        except BearerAuthError:
            raise
        except Exception as exc:
            raise BearerAuthError(503, "inbound_bearer_unavailable") from exc
        StaticBearerAuthenticator(expected).authenticate(headers)
