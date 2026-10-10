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


def test_missing_order_id_holds_side_instead_of_reposting(bot) -> None:
    b, client = bot
    client.place_order.return_value = {"data": {"message": "ok"}}

    order_id = b._place_order(TradeSide.BID, 30.0, 100)

    assert order_id is None
    assert b._sides[TradeSide.BID].held is True
    assert any("no id came back" in m for m in b._logs)


def test_held_side_is_not_retried(bot) -> None:
    b, client = bot
    b._sides[TradeSide.BID].held = True
    b._bid_levels = []

    b._retry(TradeSide.BID)

    client.place_order.assert_not_called()


def test_dry_run_missing_id_does_not_hold(bot) -> None:
    b, client = bot
    client.dry_run = True
    client.place_order.return_value = {"data": {"message": "dry-run"}}

    b._place_order(TradeSide.ASK, 75.0, 10)

    assert b._sides[TradeSide.ASK].held is False
    assert any("dry run" in m for m in b._logs)
