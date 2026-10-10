"""Cached wallet balances per account, shared by every bot in a run."""

import time
from typing import Any

from bp_tools.core.api import ApiClient

DEFAULT_REFRESH_SECONDS = 3600.0  # 1 hour


class WalletCache:
    """
    Wallet balances for one API client, refreshed on demand or when stale.

    Balances are whatever currencies the API reports; this class does not
    assume any particular currency.

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
        wallets: dict[str, Any] = me.get("data", {}).get("wallets", {})
        self._balances = {k: int(v) for k, v in wallets.items()}
        self._refreshed_at = time.time()
        return self._balances

    def get(self, force: bool = False) -> dict[str, int]:
        """Return cached balances, refreshing first if stale or *force* is set."""
        stale = time.time() - self._refreshed_at > self._refresh_seconds
        if force or stale or not self._balances:
            return self.refresh()
        return self._balances


class WalletRegistry:
    """
    One :class:`WalletCache` per account, shared by all bots in a run.

    Because the cache is shared, a purchase that one bot refreshes is visible
    to every other bot spending from the same account.

    :param clients: API clients keyed by username.
    """

    def __init__(
        self,
        clients: dict[str, ApiClient],
        refresh_seconds: float = DEFAULT_REFRESH_SECONDS,
    ) -> None:
        self._clients = clients
        self._refresh_seconds = refresh_seconds
        self._caches: dict[str, WalletCache] = {}

    def _cache(self, username: str) -> WalletCache | None:
        if username not in self._caches:
            client = self._clients.get(username)
            if client is None:
                return None
            self._caches[username] = WalletCache(client, self._refresh_seconds)
        return self._caches[username]

    def get(self, username: str, force: bool = False) -> dict[str, int]:
        """Balances for *username*; ``{}`` if the account has no client."""
        cache = self._cache(username)
        return cache.get(force) if cache is not None else {}

    def refresh(self, username: str) -> dict[str, int]:
        """Re-read *username*'s wallet. Raises on API failure."""
        cache = self._cache(username)
        return cache.refresh() if cache is not None else {}

    def balances(self, username: str) -> dict[str, int]:
        """Last known balances for *username*, without an API call."""
        cache = self._caches.get(username)
        return cache.balances if cache is not None else {}
