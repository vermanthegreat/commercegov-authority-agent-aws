"""Optional HTTPS transport that loads the outbound CommerceGov read bearer lazily."""

from __future__ import annotations

from typing import Any, Callable, Mapping, Protocol

from authority_agent.commercegov_read import (
    CommerceGovReadError,
    CommerceGovTokenExpiredError,
    HttpxCommerceGovReadTransport,
)


class OAuthCredentialProvider(Protocol):
    def access_token(self) -> str: ...
    def refresh_after_token_expired(self, rejected_access_token: str) -> str: ...


class LazyHttpsCommerceGovReadTransport:
    def __init__(
        self,
        *,
        base_url: str,
        token_loader: Callable[[], str] | None = None,
        credential_manager: OAuthCredentialProvider | None = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        if (token_loader is None) == (credential_manager is None):
            raise ValueError("exactly_one_commercegov_credential_source_required")
        self._base_url = base_url
        self._token_loader = token_loader
        self._credential_manager = credential_manager
        self._timeout_seconds = timeout_seconds
        self._inner: HttpxCommerceGovReadTransport | None = None

    def _transport_for(self, token: str) -> HttpxCommerceGovReadTransport:
        return HttpxCommerceGovReadTransport(
            base_url=self._base_url,
            bearer_token=token,
            timeout_seconds=self._timeout_seconds,
        )

    def get_json(self, path: str) -> Mapping[str, Any]:
        if self._credential_manager is not None:
            try:
                token = self._credential_manager.access_token()
                return self._transport_for(token).get_json(path)
            except CommerceGovTokenExpiredError:
                try:
                    refreshed = self._credential_manager.refresh_after_token_expired(token)
                except Exception:
                    raise CommerceGovReadError("commercegov_read_failed") from None
                # This retry is intentionally not recursive. A second 401/token_expired
                # propagates and the existing authority processor fails closed.
                return self._transport_for(refreshed).get_json(path)
            except CommerceGovReadError:
                raise
            except Exception:
                raise CommerceGovReadError("commercegov_read_failed") from None

        if self._inner is None:
            try:
                assert self._token_loader is not None
                token = self._token_loader()
            except CommerceGovReadError:
                raise
            except Exception:
                raise CommerceGovReadError("commercegov_read_failed") from None
            self._inner = self._transport_for(token)
        return self._inner.get_json(path)
