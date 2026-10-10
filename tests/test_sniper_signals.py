"""ItemSniperBot buy signals: when an item should be queued for purchase."""

from typing import Any
from unittest import mock

import pytest

from bp_tools.core.config import AppConfig, UserToken
from bp_tools.core.runner import RunnerContext
from bp_tools.tools.item_sniper import bot as botmod
from bp_tools.tools.item_sniper.models import ItemSniperConfig, ShopItem


def _payload(item_id: int, **fields: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": item_id,
        "name": f"Item {item_id}",
        "slug": "s",
        "type": 1,
        "image": "",
        "credits": 10,
        "bits": 0,
        "rare": True,
        "on_sale": True,
        "stock": 5,
        "remaining_stock": 5,
        "creator": {"id": 1},
        "created_at": "",
    }
    base.update(fields)
    return base


@pytest.fixture()
def bot(monkeypatch: pytest.MonkeyPatch) -> botmod.ItemSniperBot:
    monkeypatch.setattr(botmod, "WebSession", mock.Mock())
    ctx = RunnerContext(
        config=AppConfig(users=[UserToken("Revolt", "t")], tools={}),
        clients={"Revolt": mock.Mock()},
    )
    sniper_cfg = ItemSniperConfig.from_dict({"users": ["Revolt"]})
    return botmod.ItemSniperBot(ctx=ctx, config=sniper_cfg, poll_interval=0)


def _queued(bot: botmod.ItemSniperBot) -> list[int]:
    return [i.item_id for i in bot._items_to_buy]


def test_brand_new_rare_item_on_sale_is_queued(bot) -> None:
    bot._detect_buyable(ShopItem.from_api(_payload(1)))

    assert _queued(bot) == [1]


def test_new_item_with_no_stock_is_not_queued(bot) -> None:
    bot._detect_buyable(ShopItem.from_api(_payload(1, remaining_stock=0)))

    assert _queued(bot) == []


def test_restock_from_zero_is_queued(bot) -> None:
    bot._stock_tracker[2] = 0
    bot._on_sale_tracker[2] = True

    bot._detect_buyable(ShopItem.from_api(_payload(2, remaining_stock=3)))

    assert _queued(bot) == [2]


def test_unchanged_item_is_not_requeued(bot) -> None:
    item = ShopItem.from_api(_payload(3))
    bot._detect_buyable(item)
    bot._items_to_buy.clear()

    bot._detect_buyable(item)

    assert _queued(bot) == []


def test_item_going_on_sale_is_queued(bot) -> None:
    bot._stock_tracker[4] = 5
    bot._on_sale_tracker[4] = False

    bot._detect_buyable(ShopItem.from_api(_payload(4, on_sale=True)))

    assert _queued(bot) == [4]


def test_non_rare_item_is_queued_only_when_new_and_on_sale(bot) -> None:
    bot._detect_buyable(ShopItem.from_api(_payload(5, rare=False)))

    assert _queued(bot) == [5]


def test_non_rare_item_seen_before_is_not_queued(bot) -> None:
    bot._stock_tracker[6] = 5
    bot._on_sale_tracker[6] = True

    bot._detect_buyable(ShopItem.from_api(_payload(6, rare=False)))

    assert _queued(bot) == []
