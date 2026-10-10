"""Trade-currency order handling: posting, startup cleanup, and failure paths."""

from unittest import mock

import pytest

from bp_tools.core.config import AppConfig, UserToken
from bp_tools.core.runner import RunnerContext
from bp_tools.tools.trade_currency import bot as tc_mod
from bp_tools.tools.trade_currency.bot import CurrencyExchangeBot
from bp_tools.tools.trade_currency.models import (
    CurrencyExchangeConfig,
    ExchangeSideConfig,
    TradeSide,
)


@pytest.fixture()
def bot(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(tc_mod.time, "sleep", lambda _s: None)
    client = mock.Mock()
    client.get_me.return_value = {"data": {"wallets": {"credits": 0, "bits": 0}}}
    cfg = CurrencyExchangeConfig(
        usernames=["Revolt"],
        offer_bits=ExchangeSideConfig(amount=100, max_rate=40.0),
    )
    ctx = RunnerContext(
        config=AppConfig(users=[UserToken("Revolt", "t")], tools={}),
        clients={"Revolt": client},
    )
    b = CurrencyExchangeBot(ctx=ctx, config=cfg, poll_interval=60)
    logs: list[str] = []
    b._log = lambda msg, *_: logs.append(msg)  # type: ignore[method-assign]
    b._logs = logs  # type: ignore[attr-defined]
    return b, client


def test_place_order_sends_limit_order_and_returns_id(bot) -> None:
    b, client = bot
    client.place_order.return_value = {"data": {"id": 77}}

    order_id = b._place_order(TradeSide.BID, 30.5, 100)

    client.place_order.assert_called_once_with(
        trade_type="bits-to-credits",
        order_type="limit",
        amount=100,
        limit_rate=30.5,
    )
    assert order_id == 77
    assert b._sides[TradeSide.BID].amount == 100


def test_place_order_with_zero_amount_makes_no_call(bot) -> None:
    b, client = bot

    assert b._place_order(TradeSide.BID, 30.0, 0) is None
    client.place_order.assert_not_called()


def test_place_order_failure_returns_none_and_logs(bot) -> None:
    b, client = bot
    client.place_order.side_effect = RuntimeError("insufficient funds")

    assert b._place_order(TradeSide.ASK, 75.0, 10) is None
    assert any("insufficient funds" in m for m in b._logs)


def test_startup_cancels_every_open_order(bot) -> None:
    b, client = bot
    client.get_my_orders.return_value = {"data": [{"id": 1}, {"id": 2}]}

    b._cancel_all_open_orders()

    assert client.cancel_order.call_args_list == [mock.call(1), mock.call(2)]


def test_startup_survives_failed_cancel(bot) -> None:
    b, client = bot
    client.get_my_orders.return_value = {"data": [{"id": 1}, {"id": 2}]}
    client.cancel_order.side_effect = [RuntimeError("gone"), None]

    b._cancel_all_open_orders()

    assert client.cancel_order.call_count == 2
    assert any("gone" in m for m in b._logs)


def test_startup_survives_failed_order_fetch(bot) -> None:
    b, client = bot
    client.get_my_orders.side_effect = RuntimeError("api down")

    b._cancel_all_open_orders()

    client.cancel_order.assert_not_called()
    assert any("api down" in m for m in b._logs)


@pytest.fixture()
def repost_bot(bot, monkeypatch: pytest.MonkeyPatch):
    b, client = bot
    monkeypatch.setattr(tc_mod.time, "sleep", lambda _s: None)
    b._sides[TradeSide.BID].order_id = 500
    b._sides[TradeSide.BID].rate = 35.0
    b._sides[TradeSide.BID].amount = 100
    return b, client


def test_repost_cancels_and_replaces_with_remaining_amount(repost_bot) -> None:
    b, client = repost_bot
    client.get_my_orders.return_value = {"data": [{"id": 500, "remaining_amount": 60}]}
    client.place_order.return_value = {"data": {"id": 501}}

    b._cancel_and_repost(TradeSide.BID, 36.0, "Overtaken")

    client.cancel_order.assert_called_once_with(500)
    client.place_order.assert_called_once_with(
        trade_type="bits-to-credits",
        order_type="limit",
        amount=60,
        limit_rate=36.0,
    )
    assert b._sides[TradeSide.BID].order_id == 501
    assert b._sides[TradeSide.BID].rate == 36.0


def test_failed_cancel_keeps_existing_order_state(repost_bot) -> None:
    b, client = repost_bot
    client.get_my_orders.return_value = {"data": [{"id": 500, "remaining_amount": 60}]}
    client.cancel_order.side_effect = RuntimeError("nope")

    b._cancel_and_repost(TradeSide.BID, 36.0, "Overtaken")

    client.place_order.assert_not_called()
    assert b._sides[TradeSide.BID].order_id == 500


def test_fully_filled_order_is_not_reposted(repost_bot) -> None:
    b, client = repost_bot
    client.get_my_orders.return_value = {"data": [{"id": 500, "remaining_amount": 0}]}

    b._cancel_and_repost(TradeSide.BID, 36.0, "Overtaken")

    client.place_order.assert_not_called()
    assert b._sides[TradeSide.BID].order_id is None
    assert any("filled" in m for m in b._logs)


def test_unreadable_remaining_amount_is_reported_accurately(repost_bot) -> None:
    b, client = repost_bot
    client.get_my_orders.side_effect = RuntimeError("down")

    b._cancel_and_repost(TradeSide.BID, 36.0, "Overtaken")

    assert b._sides[TradeSide.BID].order_id is None
    assert any("Could not read" in m for m in b._logs)
    assert not any("Outside limit" in m for m in b._logs)


def test_monitor_reposts_when_overtaken(repost_bot, monkeypatch) -> None:
    b, client = repost_bot
    b._bid_levels = [{"rate": 38.0, "amount": 1}]
    called: list[tuple] = []
    monkeypatch.setattr(b, "_cancel_and_repost", lambda *a: called.append(a))

    acted = b._monitor_side(TradeSide.BID)

    assert acted is True
    assert called and called[0][0] is TradeSide.BID


def test_monitor_leaves_order_alone_when_still_best(repost_bot, monkeypatch) -> None:
    b, _ = repost_bot
    # Our 35.00 is top; the next level 34.99 means the ideal rate is 35.00 again.
    b._bid_levels = [{"rate": 35.0, "amount": 1}, {"rate": 34.99, "amount": 1}]
    called: list[tuple] = []
    monkeypatch.setattr(b, "_cancel_and_repost", lambda *a: called.append(a))

    assert b._monitor_side(TradeSide.BID) is False
    assert called == []


def test_monitor_retries_when_side_has_no_order(bot, monkeypatch) -> None:
    b, _ = bot
    retried: list[TradeSide] = []
    monkeypatch.setattr(b, "_retry", lambda side: retried.append(side))

    b._monitor_side(TradeSide.BID)

    assert retried == [TradeSide.BID]
