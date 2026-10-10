"""ItemSniperBot buy decisions, using a fake API client and fake web session."""

from typing import Any
from unittest import mock

import pytest

from bp_tools.core.config import AppConfig, UserToken
from bp_tools.core.runner import RunnerContext
from bp_tools.tools.item_sniper import bot as botmod
from bp_tools.tools.item_sniper.models import ItemSniperConfig, ShopItem


def _item_payload(
    item_id: int, *, creator: int = 1, rare: bool = True
) -> dict[str, Any]:
    return {
        "id": item_id,
        "name": f"Item {item_id}",
        "slug": f"item-{item_id}",
        "type": 1,
        "image": "",
        "credits": 10,
        "bits": 0,
        "rare": rare,
        "on_sale": True,
        "stock": 5,
        "remaining_stock": 5,
        "creator": {"id": creator},
        "created_at": "",
    }


class FakeApi:
    def __init__(self, owned: list[int] | None = None) -> None:
        self.owned = owned or []
        self.payload: dict[str, Any] = {"data": []}
        self.inventory_calls = 0

    def get_me(self) -> dict[str, Any]:
        return {"data": {"wallets": {"credits": 1000, "bits": 0}}}

    def browse_items(self, **_: Any) -> dict[str, Any]:
        return self.payload

    def get_inventory(self, per_page: int, page: int) -> dict[str, Any]:
        self.inventory_calls += 1
        data = [{"item": {"id": i}} for i in self.owned]
        return {"data": data, "meta": {"last_page": 1}}


class FakeWeb:
    buys: list[int] = []

    def __init__(
        self,
        username: str,
        password: str,
        two_factor_code: str | None = None,
        cookie_file: object = None,
    ):
        self.username = username

    def buy_item(self, item_id: int, currency: str = "credits") -> dict[str, Any]:
        FakeWeb.buys.append(item_id)
        return {"success": True, "message": "ok"}


@pytest.fixture()
def make_bot(monkeypatch: pytest.MonkeyPatch):
    FakeWeb.buys = []
    monkeypatch.setattr(botmod, "WebSession", FakeWeb)

    def factory(api: FakeApi, password: str | None = "pw") -> botmod.ItemSniperBot:
        cfg = AppConfig(
            users=[UserToken("Revolt", "tok", password)],
            tools={},
        )
        ctx = RunnerContext(config=cfg, clients={"Revolt": api})
        sniper_cfg = ItemSniperConfig.from_dict(
            {"users": [{"username": "Revolt", "rares-only": False}]}
        )
        bot = botmod.ItemSniperBot(ctx=ctx, config=sniper_cfg, poll_interval=0)
        bot._seed_tracker = lambda: None  # type: ignore[method-assign]
        bot.initialize()
        return bot

    return factory


def _shop_item(item_id: int) -> ShopItem:
    return ShopItem.from_api(_item_payload(item_id))


def test_new_item_is_bought_once(make_bot) -> None:
    api = FakeApi()
    bot = make_bot(api)
    user = bot.config.users[0]

    bot._buy_for_user(_shop_item(42), user)
    bot._buy_for_user(_shop_item(42), user)

    assert FakeWeb.buys == [42]


def test_item_already_in_inventory_is_skipped(make_bot) -> None:
    api = FakeApi(owned=[7])
    bot = make_bot(api)

    bot._buy_for_user(_shop_item(7), bot.config.users[0])

    assert FakeWeb.buys == []


def test_inventory_is_cached_between_buys(make_bot) -> None:
    api = FakeApi(owned=[])
    bot = make_bot(api)
    calls_after_init = api.inventory_calls

    bot._buy_for_user(_shop_item(1), bot.config.users[0])
    bot._buy_for_user(_shop_item(2), bot.config.users[0])

    assert api.inventory_calls == calls_after_init + 1  # one scan, then cache


def test_no_web_session_means_no_purchase(make_bot) -> None:
    api = FakeApi()
    bot = make_bot(api, password=None)

    bot._buy_for_user(_shop_item(3), bot.config.users[0])

    assert FakeWeb.buys == []


def test_non_rare_item_skipped_when_rares_only(make_bot) -> None:
    api = FakeApi()
    bot = make_bot(api)
    user = mock.Mock(username="Revolt", rares_only=True)

    bot._buy_for_user(ShopItem.from_api(_item_payload(9, rare=False)), user)

    assert FakeWeb.buys == []


def test_malformed_items_are_skipped_not_fatal(make_bot) -> None:
    bot = make_bot(FakeApi())

    parsed = bot._parse_items([_item_payload(1), {"name": "broken"}, _item_payload(2)])

    assert [i.item_id for i in parsed] == [1, 2]


def test_detect_buyable_on_new_item(make_bot) -> None:
    bot = make_bot(FakeApi())

    bot._detect_buyable(_shop_item(5))

    assert [i.item_id for i in bot._items_to_buy] == [5]
