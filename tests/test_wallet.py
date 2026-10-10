"""WalletCache: caching and refresh behaviour."""

from typing import Any
from unittest import mock

from bp_tools.core.wallet import WalletCache, WalletRegistry


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


def test_registry_shares_balances_between_consumers() -> None:
    client = mock.Mock()
    client.get_me.side_effect = [
        {"data": {"wallets": {"credits": 100}}},
        {"data": {"wallets": {"credits": 40}}},
    ]
    registry = WalletRegistry({"Revolt": client})

    # Bot A reads, then spends and refreshes
    assert registry.get("Revolt") == {"credits": 100}
    registry.refresh("Revolt")

    # Bot B, reading later, sees the refreshed balance without its own API call
    assert registry.balances("Revolt") == {"credits": 40}
    assert registry.get("Revolt") == {"credits": 40}
    assert client.get_me.call_count == 2


def test_registry_unknown_account_is_empty() -> None:
    registry = WalletRegistry({})

    assert registry.get("Nobody") == {}
    assert registry.balances("Nobody") == {}


def test_runner_context_builds_a_registry_from_clients() -> None:
    from bp_tools.core.config import AppConfig
    from bp_tools.core.runner import RunnerContext

    client = mock.Mock()
    ctx = RunnerContext(config=AppConfig(users=[], tools={}), clients={"A": client})

    assert isinstance(ctx.wallets, WalletRegistry)
    client.get_me.assert_not_called()
