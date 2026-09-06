"""Bounded CommerceGov OAuth credential refresh and rotation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import logging
from time import sleep
from typing import Any, Callable, Mapping, Protocol
from uuid import uuid4

import httpx
from botocore.exceptions import ClientError
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


OAUTH_SECRET_SCHEMA = "commercegov.oauth-read-secret.v1"
OAUTH_CLIENT_ID = "aws-authority-agent-p3b-read"
OAUTH_SCOPES = frozenset({"shops:read", "products:read", "policy:read"})
OAUTH_REFRESH_PATH = "/oauth/integration/token"


class OAuthCredentialError(RuntimeError):
    """Fail-closed error whose message never contains credential material."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class OAuthSecretEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: str
    access_token: str = Field(min_length=1)
    refresh_token: str = Field(min_length=1)
    expires_at: datetime
    token_type: str
    scopes: tuple[str, ...]
    subject: str = Field(min_length=1)
    client_id: str
    generation: int = Field(ge=0)

    @field_validator("schema_version")
    @classmethod
    def _schema_is_exact(cls, value: str) -> str:
        if value != OAUTH_SECRET_SCHEMA:
            raise ValueError("unsupported_oauth_secret_schema")
        return value

    @field_validator("token_type")
    @classmethod
    def _bearer_is_exact(cls, value: str) -> str:
        if value != "Bearer":
            raise ValueError("invalid_oauth_token_type")
        return value

    @field_validator("client_id")
    @classmethod
    def _client_is_exact(cls, value: str) -> str:
        if value != OAUTH_CLIENT_ID:
            raise ValueError("oauth_client_authority_mismatch")
        return value

    @field_validator("scopes")
    @classmethod
    def _scopes_are_exact(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(OAUTH_SCOPES) or frozenset(value) != OAUTH_SCOPES:
            raise ValueError("oauth_scope_authority_mismatch")
        return tuple(sorted(value))

    @field_validator("expires_at")
    @classmethod
    def _expiry_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("oauth_expiry_timezone_required")
        return value.astimezone(timezone.utc)

    @classmethod
    def from_secret_string(cls, secret_string: str) -> "OAuthSecretEnvelope":
        try:
            return cls.model_validate_json(secret_string)
        except (ValidationError, ValueError, TypeError):
            raise OAuthCredentialError("invalid_oauth_secret_envelope") from None

    def to_secret_string(self) -> str:
        return self.model_dump_json()


class _RefreshTokenResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    access_token: str = Field(min_length=1)
    token_type: str
    expires_in: int = Field(gt=0)
    refresh_token: str | None = None
    scope: str

    @field_validator("token_type")
    @classmethod
    def _bearer_is_exact(cls, value: str) -> str:
        if value != "Bearer":
            raise ValueError("invalid_oauth_token_type")
        return value

    @field_validator("scope")
    @classmethod
    def _scope_is_exact(cls, value: str) -> str:
        scopes = value.split()
        if len(scopes) != len(OAUTH_SCOPES) or frozenset(scopes) != OAUTH_SCOPES:
            raise ValueError("oauth_scope_authority_mismatch")
        return " ".join(sorted(scopes))


class SecretsClient(Protocol):
    def get_secret_value(self, **kwargs: Any) -> Mapping[str, Any]: ...
    def put_secret_value(self, **kwargs: Any) -> Mapping[str, Any]: ...


class LeaseTable(Protocol):
    def put_item(self, **kwargs: Any) -> Mapping[str, Any]: ...
    def get_item(self, **kwargs: Any) -> Mapping[str, Any]: ...
    def update_item(self, **kwargs: Any) -> Mapping[str, Any]: ...


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class CommerceGovOAuthCredentialManager:
    """Loads one strict envelope and coordinates refresh across warm Lambdas."""

    def __init__(
        self,
        *,
        base_url: str,
        secret_arn: str,
        secrets_client: SecretsClient,
        lease_table: LeaseTable,
        clock: Callable[[], datetime] = _utc_now,
        owner_factory: Callable[[], str] = lambda: str(uuid4()),
        http_post: Callable[..., Any] = httpx.post,
        sleeper: Callable[[float], None] = sleep,
        refresh_skew_seconds: int = 120,
        lease_seconds: int = 15,
        contention_attempts: int = 3,
        contention_sleep_seconds: float = 0.25,
        logger: logging.Logger | None = None,
    ) -> None:
        base = str(base_url or "").strip().rstrip("/")
        arn = str(secret_arn or "").strip()
        if not base.startswith("https://") or not arn:
            raise ValueError("invalid_oauth_refresh_configuration")
        if not 0 < refresh_skew_seconds <= 300 or not 5 <= lease_seconds <= 30:
            raise ValueError("invalid_oauth_refresh_bounds")
        if not 1 <= contention_attempts <= 5 or not 0 < contention_sleep_seconds <= 1:
            raise ValueError("invalid_oauth_contention_bounds")

        self._base_url = base
        self._secret_arn = arn
        self._secrets = secrets_client
        self._table = lease_table
        self._clock = clock
        self._owner_factory = owner_factory
        self._http_post = http_post
        self._sleeper = sleeper
        self._refresh_skew = timedelta(seconds=refresh_skew_seconds)
        self._lease_seconds = lease_seconds
        self._contention_attempts = contention_attempts
        self._contention_sleep_seconds = contention_sleep_seconds
        self._logger = logger or logging.getLogger(__name__)
        self._cached: OAuthSecretEnvelope | None = None

        stable_identity = sha256(arn.encode("utf-8")).hexdigest()
        self._lease_key = {"PK": f"SYSTEM#OAUTH#{stable_identity}", "SK": "REFRESH"}

    def access_token(self) -> str:
        envelope = self._cached or self._load_secret()
        if envelope.expires_at <= self._now() + self._refresh_skew:
            envelope = self._refresh_or_reconcile(envelope.generation)
        self._cached = envelope
        return envelope.access_token

    def refresh_after_token_expired(self, rejected_access_token: str) -> str:
        rejected = str(rejected_access_token or "")
        if not rejected:
            raise OAuthCredentialError("oauth_rejected_token_missing")

        envelope = self._cached or self._load_secret()
        if envelope.access_token != rejected:
            self._cached = envelope
            return envelope.access_token

        envelope = self._refresh_or_reconcile(envelope.generation)
        self._cached = envelope
        return envelope.access_token

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise OAuthCredentialError("oauth_clock_invalid")
        return value.astimezone(timezone.utc)

    def _load_secret(self) -> OAuthSecretEnvelope:
        try:
            response = self._secrets.get_secret_value(SecretId=self._secret_arn)
        except Exception:
            raise OAuthCredentialError("oauth_secret_unavailable") from None

        secret_string = response.get("SecretString")
        if not isinstance(secret_string, str):
            raise OAuthCredentialError("oauth_secret_unavailable")
        return OAuthSecretEnvelope.from_secret_string(secret_string)

    def _refresh_or_reconcile(self, observed_generation: int) -> OAuthSecretEnvelope:
        for attempt in range(self._contention_attempts):
            current = self._load_secret()
            if current.generation > observed_generation:
                return current
            if current.generation != observed_generation:
                raise OAuthCredentialError("oauth_generation_invalid")

            owner_id = self._owner_factory()
            if self._try_acquire_lease(owner_id, observed_generation):
                return self._refresh_under_lease(owner_id, observed_generation)

            if attempt + 1 < self._contention_attempts:
                self._sleeper(self._contention_sleep_seconds)

        raise OAuthCredentialError("oauth_refresh_concurrency_timeout")

    def _try_acquire_lease(self, owner_id: str, observed_generation: int) -> bool:
        now = self._now()
        lease_expires_at = int(now.timestamp()) + self._lease_seconds
        try:
            self._table.put_item(
                Item={
                    **self._lease_key,
                    "owner_id": owner_id,
                    "observed_generation": observed_generation,
                    "lease_expires_at": lease_expires_at,
                    "updated_at": now.isoformat().replace("+00:00", "Z"),
                },
                ConditionExpression=(
                    "attribute_not_exists(PK) OR "
                    "attribute_not_exists(lease_expires_at) OR "
                    "lease_expires_at < :now"
                ),
                ExpressionAttributeValues={":now": int(now.timestamp())},
            )
            self._safe_log(
                "commercegov_oauth_refresh_lease_acquired",
                generation=observed_generation,
            )
            return True
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                return False
            raise OAuthCredentialError("oauth_refresh_lease_failed") from None
        except Exception:
            raise OAuthCredentialError("oauth_refresh_lease_failed") from None

    def _refresh_under_lease(
        self, owner_id: str, observed_generation: int
    ) -> OAuthSecretEnvelope:
        current = self._load_secret()
        if current.generation > observed_generation:
            self._complete_lease(owner_id, current.generation)
            return current
        if current.generation != observed_generation:
            raise OAuthCredentialError("oauth_generation_invalid")

        self._safe_log(
            "commercegov_oauth_refresh_started",
            generation=current.generation,
        )
        try:
            refreshed = self._request_refresh(current)
            self._secrets.put_secret_value(
                SecretId=self._secret_arn,
                SecretString=refreshed.to_secret_string(),
                ClientRequestToken=owner_id,
            )
        except OAuthCredentialError:
            self._safe_log(
                "commercegov_oauth_refresh_failed",
                generation=current.generation,
            )
            raise
        except Exception:
            self._safe_log(
                "commercegov_oauth_refresh_failed",
                generation=current.generation,
            )
            raise OAuthCredentialError("oauth_refresh_secret_write_failed") from None

        self._complete_lease(owner_id, refreshed.generation)
        self._safe_log(
            "commercegov_oauth_refresh_succeeded",
            generation=refreshed.generation,
        )
        return refreshed

    def _request_refresh(self, current: OAuthSecretEnvelope) -> OAuthSecretEnvelope:
        try:
            response = self._http_post(
                f"{self._base_url}{OAUTH_REFRESH_PATH}",
                data={
                    "grant_type": "refresh_token",
                    "client_id": OAUTH_CLIENT_ID,
                    "refresh_token": current.refresh_token,
                },
                timeout=5.0,
                follow_redirects=False,
            )
        except Exception:
            raise OAuthCredentialError("oauth_refresh_unavailable") from None

        status_code = int(getattr(response, "status_code", 0) or 0)
        if status_code < 200 or status_code >= 300:
            raise OAuthCredentialError("oauth_refresh_rejected")

        try:
            payload = response.json()
            parsed = _RefreshTokenResponse.model_validate(payload)
        except (ValidationError, ValueError, TypeError):
            raise OAuthCredentialError("oauth_refresh_contract_invalid") from None

        refresh_token = parsed.refresh_token or current.refresh_token
        try:
            return OAuthSecretEnvelope(
                schema_version=OAUTH_SECRET_SCHEMA,
                access_token=parsed.access_token,
                refresh_token=refresh_token,
                expires_at=self._now() + timedelta(seconds=parsed.expires_in),
                token_type=parsed.token_type,
                scopes=tuple(parsed.scope.split()),
                subject=current.subject,
                client_id=current.client_id,
                generation=current.generation + 1,
            )
        except (ValidationError, ValueError):
            raise OAuthCredentialError("oauth_refresh_authority_mismatch") from None

    def _complete_lease(self, owner_id: str, generation: int) -> None:
        try:
            self._table.update_item(
                Key=self._lease_key,
                UpdateExpression=(
                    "SET observed_generation = :generation, updated_at = :updated_at "
                    "REMOVE owner_id, lease_expires_at"
                ),
                ConditionExpression="owner_id = :owner_id",
                ExpressionAttributeValues={
                    ":generation": generation,
                    ":updated_at": self._now().isoformat().replace("+00:00", "Z"),
                    ":owner_id": owner_id,
                },
            )
        except Exception:
            # The credential is already durable. A stale safe-only lease is recoverable.
            self._safe_log(
                "commercegov_oauth_refresh_lease_cleanup_failed",
                generation=generation,
            )

    def _safe_log(self, message: str, **fields: Any) -> None:
        self._logger.info(
            json.dumps(
                {"message": message, **fields},
                sort_keys=True,
                default=str,
            )
        )
