"""WalletCache: caching and refresh behaviour."""

from typing import Any
from unittest import mock

from bp_tools.core.wallet import WalletCache


def _client(credits: int = 10, bits: int = 20) -> mock.Mock:
    client = mock.Mock()
    client.get_me.return_value = {
        "data": {"wallets": {"credits": credits, "bits": bits}}
    }
    return client


def test_first_get_reads_the_wallet() -> None:
    client = _client(credits=5)

    balances: dict[str, Any] = WalletCache(client).get()

    assert balances == {"credits": 5, "bits": 20}
    client.get_me.assert_called_once()


def test_get_uses_cache_within_interval() -> None:
    client = _client()
    cache = WalletCache(client, refresh_seconds=3600)

    cache.get()
    cache.get()

    client.get_me.assert_called_once()


def test_get_refreshes_when_stale() -> None:
    client = _client()
    cache = WalletCache(client, refresh_seconds=0)

    cache.get()
    cache.get()

    assert client.get_me.call_count == 2


def test_force_refreshes_even_when_fresh() -> None:
    client = _client()
    cache = WalletCache(client, refresh_seconds=3600)

    cache.get()
    cache.get(force=True)

    assert client.get_me.call_count == 2


def test_balances_do_not_call_api() -> None:
    client = _client()
    cache = WalletCache(client)

    assert cache.balances == {}
    client.get_me.assert_not_called()


def test_missing_wallets_is_empty_not_currency_specific() -> None:
    client = mock.Mock()
    client.get_me.return_value = {"data": {}}

    assert WalletCache(client).refresh() == {}


def test_any_currency_key_is_passed_through() -> None:
    client = mock.Mock()
    client.get_me.return_value = {"data": {"wallets": {"gems": 4}}}

    assert WalletCache(client).refresh() == {"gems": 4}
