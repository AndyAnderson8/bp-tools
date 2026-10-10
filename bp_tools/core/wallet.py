"""Cached wallet balances for one account, read from ``GET /me``."""

import time
from typing import Any

from bp_tools.core.api import ApiClient

DEFAULT_REFRESH_SECONDS = 3600.0  # 1 hour


class WalletCache:
    """
    Wallet balances for one API client, refreshed on demand or when stale.

    :param client: API client for the account.
    :param refresh_seconds: Age after which :meth:`get` re-reads the wallet.
    """

    def __init__(
        self,
        client: ApiClient,
        refresh_seconds: float = DEFAULT_REFRESH_SECONDS,
    ) -> None:
        self._client = client
        self._refresh_seconds = refresh_seconds
        self._balances: dict[str, int] = {}
        self._refreshed_at: float = 0.0

    @property
    def balances(self) -> dict[str, int]:
        """Last known balances, without touching the API."""
        return self._balances

    def refresh(self) -> dict[str, int]:
        """
        Re-read the wallet from the API.

        :raises RuntimeError: If the API call fails (the cached balances are kept).
        """
        me = self._client.get_me()
        balances: dict[str, Any] = me.get("data", {}).get(
            "wallets", {}
        )
        self._balances = {k: int(v) for k, v in balances.items()}
        self._refreshed_at = time.time()
        return self._balances

    def get(self, force: bool = False) -> dict[str, int]:
        """Return cached balances, refreshing first if stale or *force* is set."""
        stale = time.time() - self._refreshed_at > self._refresh_seconds
        if force or stale or not self._balances:
            return self.refresh()
        return self._balances
