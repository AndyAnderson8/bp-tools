"""Rare bots: offerer and snagger decision logic, with a fake API client."""

from typing import Any
from unittest import mock

import pytest

from bp_tools.core.api import ApiError
from bp_tools.core.config import AppConfig, UserToken
from bp_tools.core.runner import RunnerContext
from bp_tools.tools.rare_offerer import bot as offerer_mod
from bp_tools.tools.rare_offerer.bot import OffererBot
from bp_tools.tools.rare_offerer.models import OffererConfig
from bp_tools.tools.rare_snagger.bot import SnaggerBot
from bp_tools.tools.rare_snagger.models import SnaggerConfig


def _ctx(client: mock.Mock) -> RunnerContext:
    return RunnerContext(
        config=AppConfig(users=[UserToken("Revolt", "t")], tools={}),
        clients={"Revolt": client},
    )


# ---- rare_offerer ----------------------------------------------------


@pytest.fixture()
def offerer(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(offerer_mod, "OFFER_COOLDOWN", 0)
    client = mock.Mock()
    bot = OffererBot(
        ctx=_ctx(client),
        config=OffererConfig(usernames=["Revolt"], base_offer=2),
        poll_interval=10,
    )
    bot._rare_ids = [11, 22]
    bot._rare_names = {11: "Visor", 22: "Potion"}
    return bot, client


def test_offerer_queues_offer_for_current_item_and_advances(offerer) -> None:
    bot, _ = offerer

    bot.update()

    assert bot._pending_offer == (11, "Visor", 2)
    assert bot._scan_index == 1


def test_offerer_executes_pending_offer(offerer) -> None:
    bot, client = offerer
    bot.update()

    bot.execute()

    client.make_offer.assert_called_once_with(11, 2)
    assert bot._pending_offer is None


def test_offerer_wraps_and_starts_new_cycle(offerer, monkeypatch) -> None:
    bot, _ = offerer
    monkeypatch.setattr(bot, "_refresh_items", lambda: None)
    bot._scan_index = 1

    bot.update()

    assert bot._scan_index == 0
    assert bot._cycle_count == 2


def test_offerer_respects_cooldown_without_advancing(offerer, monkeypatch) -> None:
    bot, _ = offerer
    monkeypatch.setattr(offerer_mod, "OFFER_COOLDOWN", 3600)
    bot._last_offer_time = offerer_mod.time.monotonic()

    bot.update()

    assert bot._pending_offer is None
    assert bot._scan_index == 0  # retried on the next cycle


def test_offerer_silently_skips_422(offerer) -> None:
    bot, client = offerer
    client.make_offer.side_effect = ApiError(422, "/items/11/offers", "duplicate")
    bot.update()

    bot.execute()

    assert bot._last_offer_time == 0.0  # not counted as a successful offer


def test_offerer_logs_other_errors(offerer) -> None:
    bot, client = offerer
    client.make_offer.side_effect = ApiError(500, "/items/11/offers", "boom")
    bot.update()
    logged: list[str] = []
    bot._log = lambda msg, *_: logged.append(msg)  # type: ignore[method-assign]

    bot.execute()

    assert any("boom" in m for m in logged)


# ---- rare_snagger ----------------------------------------------------


def _snagger(max_credits: int = 5, *, price: int = 3, credits: int = 100):
    client = mock.Mock()
    client.get_item.return_value = {
        "data": {"lowest_resale_price": price, "average_sales_price": 0}
    }
    client.get_resellers.return_value = {
        "data": [{"id": 9, "price": price, "seller": {"username": "Seller"}}]
    }
    client.get_me.return_value = {"data": {"wallets": {"credits": credits}}}
    client.buy_item.return_value = {"data": {"backpack_id": 5}}
    bot = SnaggerBot(
        ctx=_ctx(client),
        config=SnaggerConfig.from_dict(
            {"username": "Revolt", "max-credits": max_credits}
        ),
        poll_interval=5,
    )
    bot._rare_item_ids = [42]
    bot._refresh_items = lambda: None  # type: ignore[method-assign]
    bot._rare_names = {42: "Lion's Crate"}
    # A one-item list wraps every scan; stub the catalog refresh so tests stay offline
    bot._refresh_items = lambda: None  # type: ignore[method-assign]
    return bot, client


def test_snagger_queues_when_price_is_within_max() -> None:
    bot, _ = _snagger(max_credits=5, price=3)

    bot.update()

    assert bot._pending_buy is not None
    assert bot._pending_buy.item_id == 42
    assert bot._pending_buy.price == 3


def test_snagger_ignores_price_above_max() -> None:
    bot, _ = _snagger(max_credits=5, price=9)

    bot.update()

    assert bot._pending_buy is None


def test_snagger_override_zero_skips_without_api_call() -> None:
    client = mock.Mock()
    bot = SnaggerBot(
        ctx=_ctx(client),
        config=SnaggerConfig.from_dict(
            {"username": "Revolt", "overrides": [{"item-id": 42, "max-credits": 0}]}
        ),
        poll_interval=5,
    )
    bot._rare_item_ids = [42]
    bot._refresh_items = lambda: None  # type: ignore[method-assign]

    bot.update()

    client.get_item.assert_not_called()


def test_snagger_buys_cheapest_reseller_when_still_in_budget() -> None:
    bot, client = _snagger(max_credits=5, price=3)
    bot.update()

    bot.execute()

    client.buy_item.assert_called_once_with(
        item_id=42, currency="credits", reseller_id=9
    )


def test_snagger_skips_when_price_rose_since_scan() -> None:
    bot, client = _snagger(max_credits=5, price=3)
    bot.update()
    client.get_resellers.return_value = {
        "data": [{"id": 9, "price": 4, "seller": {"username": "Seller"}}]
    }

    bot.execute()

    client.buy_item.assert_not_called()


def test_snagger_does_not_buy_without_enough_credits() -> None:
    bot, client = _snagger(max_credits=5, price=3, credits=1)
    bot.update()

    bot.execute()

    client.buy_item.assert_not_called()


def test_snagger_scan_is_read_only() -> None:
    bot, client = _snagger(max_credits=5, price=3)

    bot.update()

    client.buy_item.assert_not_called()
    client.get_resellers.assert_not_called()


def test_snagger_does_not_queue_for_unknown_price() -> None:
    client = mock.Mock()
    client.get_item.return_value = {"data": {}}
    bot = SnaggerBot(
        ctx=_ctx(client),
        config=SnaggerConfig.from_dict({"username": "Revolt", "max-credits": 5}),
        poll_interval=5,
    )
    bot._rare_item_ids = [42]
    bot._refresh_items = lambda: None  # type: ignore[method-assign]

    bot.update()

    assert bot._pending_buy is None


_ = Any  # keep typing import used for helper annotations if extended
