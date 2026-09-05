"""Optional HTTPS transport that loads the outbound CommerceGov read bearer lazily."""

from __future__ import annotations

from typing import Any, Callable, Mapping

from authority_agent.commercegov_read import CommerceGovReadError, HttpxCommerceGovReadTransport


class LazyHttpsCommerceGovReadTransport:
    def __init__(
        self,
        *,
        base_url: str,
        token_loader: Callable[[], str],
        timeout_seconds: float = 5.0,
    ) -> None:
        self._base_url = base_url
        self._token_loader = token_loader
        self._timeout_seconds = timeout_seconds
        self._inner: HttpxCommerceGovReadTransport | None = None

    def get_json(self, path: str) -> Mapping[str, Any]:
        if self._inner is None:
            try:
                token = self._token_loader()
            except CommerceGovReadError:
                raise
            except Exception as exc:
                raise CommerceGovReadError("commercegov_read_failed") from exc
            self._inner = HttpxCommerceGovReadTransport(
                base_url=self._base_url,
                bearer_token=token,
                timeout_seconds=self._timeout_seconds,
            )
        return self._inner.get_json(path)
