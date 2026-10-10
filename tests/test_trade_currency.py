"""Trade-currency pricing: where our order should sit in the book."""

from typing import Any
from unittest import mock

import pytest

from bp_tools.core.config import AppConfig, UserToken
from bp_tools.core.runner import RunnerContext
from bp_tools.tools.trade_currency.bot import CurrencyExchangeBot
from bp_tools.tools.trade_currency.constants import TICK
from bp_tools.tools.trade_currency.models import (
    CurrencyExchangeConfig,
    ExchangeSideConfig,
    TradeSide,
)

BID_CFG = ExchangeSideConfig(amount=100, max_rate=40.0)
ASK_CFG = ExchangeSideConfig(amount=10, max_rate=70.0)


def _bot() -> CurrencyExchangeBot:
    cfg = CurrencyExchangeConfig(usernames=["Revolt"], offer_bits=BID_CFG)
    ctx = RunnerContext(
        config=AppConfig(users=[UserToken("Revolt", "t")], tools={}),
        clients={"Revolt": mock.Mock()},
    )
    return CurrencyExchangeBot(ctx=ctx, config=cfg, poll_interval=60)


def _levels(*rates: float) -> list[dict[str, Any]]:
    return [{"rate": r, "amount": 1} for r in rates]


def test_empty_book_starts_just_inside_limit() -> None:
    bot = _bot()
    bot._bid_levels = []

    assert bot._compute_rate(TradeSide.BID, BID_CFG) == pytest.approx(40.0 - TICK)


def test_undercuts_best_bid_when_not_yet_posted() -> None:
    bot = _bot()
    bot._bid_levels = _levels(30.0, 29.0)

    assert bot._compute_rate(TradeSide.BID, BID_CFG) == pytest.approx(
        30.0 + TICK, abs=1e-9
    )


def test_never_exceeds_bid_ceiling() -> None:
    bot = _bot()
    bot._bid_levels = _levels(39.999)

    assert bot._compute_rate(TradeSide.BID, BID_CFG) <= 40.0


def test_levels_at_or_beyond_limit_are_ignored() -> None:
    bot = _bot()
    bot._bid_levels = _levels(45.0, 41.0, 35.0)  # first two exceed the ceiling

    assert bot._compute_rate(TradeSide.BID, BID_CFG) == pytest.approx(
        35.0 + TICK, abs=1e-9
    )


def test_regresses_when_we_hold_the_top_spot() -> None:
    bot = _bot()
    bot._sides[TradeSide.BID].rate = 35.0
    bot._bid_levels = _levels(35.0, 33.0)

    assert bot._compute_rate(TradeSide.BID, BID_CFG) == pytest.approx(
        33.0 + TICK, abs=1e-9
    )


def test_ask_side_undercuts_and_respects_floor() -> None:
    bot = _bot()
    bot._ask_levels = _levels(75.0, 80.0)

    rate = bot._compute_rate(TradeSide.ASK, ASK_CFG)

    assert rate == pytest.approx(75.0 - TICK, abs=1e-9)
    assert rate >= 70.0


def test_side_config_lookup() -> None:
    bot = _bot()

    assert bot._config_for(TradeSide.BID) is bot.config.offer_bits
    assert bot._config_for(TradeSide.ASK) is None
