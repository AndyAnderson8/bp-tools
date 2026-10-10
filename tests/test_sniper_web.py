"""Sniper web purchase outcomes and the per-user buy decision."""

from typing import Any
from unittest import mock

import pytest

from bp_tools.core.config import AppConfig, UserToken
from bp_tools.core.runner import RunnerContext
from bp_tools.tools.item_sniper import bot as botmod
from bp_tools.tools.item_sniper.models import ItemSniperConfig, ShopItem


def _item(item_id: int = 5) -> ShopItem:
    return ShopItem.from_api(
        {
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
    )


class ScriptedWeb:
    """Web session stand-in whose buy_item result is set per test."""

    result: Any = None

    def __init__(self, *_a: Any, **_k: Any) -> None:
        pass

    def buy_item(self, item_id: int, currency: str = "credits") -> Any:
        if isinstance(ScriptedWeb.result, Exception):
            raise ScriptedWeb.result
        return ScriptedWeb.result


@pytest.fixture()
def bot(monkeypatch: pytest.MonkeyPatch) -> botmod.ItemSniperBot:
    monkeypatch.setattr(botmod, "WebSession", ScriptedWeb)
    client = mock.Mock()
    client.get_me.return_value = {"data": {"wallets": {"credits": 1000, "bits": 0}}}
    client.get_inventory.return_value = {"data": [], "meta": {"last_page": 1}}
    ctx = RunnerContext(
        config=AppConfig(users=[UserToken("Revolt", "t", "pw")], tools={}),
        clients={"Revolt": client},
    )
    sniper_cfg = ItemSniperConfig.from_dict(
        {"users": [{"username": "Revolt", "rares-only": False}]}
    )
    b = botmod.ItemSniperBot(ctx=ctx, config=sniper_cfg, poll_interval=0)
    b._seed_tracker = lambda: None  # type: ignore[method-assign]
    b._web_sessions["Revolt"] = ScriptedWeb()  # type: ignore[assignment]
    return b


def _logs(bot: botmod.ItemSniperBot) -> list[str]:
    lines: list[str] = []
    bot._log = lambda msg, *_: lines.append(msg)  # type: ignore[method-assign]
    return lines


def test_successful_web_buy_is_recorded(bot, monkeypatch) -> None:
    ScriptedWeb.result = {"success": True, "message": "ok"}
    lines = _logs(bot)

    bot._buy_via_web("Revolt", _item(5), bot._web_sessions["Revolt"], "credits")

    assert ("Revolt", 5) in bot._purchased
    assert any("Purchased" in m for m in lines)


def test_already_owned_is_recorded_not_reported_as_purchase(bot) -> None:
    ScriptedWeb.result = {"success": False, "already_owned": True}
    lines = _logs(bot)

    bot._buy_via_web("Revolt", _item(5), bot._web_sessions["Revolt"], "credits")

    assert ("Revolt", 5) in bot._purchased
    assert not any("Purchased" in m for m in lines)
    assert any("Already owned" in m for m in lines)


def test_failed_web_buy_is_not_recorded_so_it_can_retry(bot) -> None:
    ScriptedWeb.result = {"success": False, "message": "Purchase may have failed"}
    _logs(bot)

    bot._buy_via_web("Revolt", _item(5), bot._web_sessions["Revolt"], "credits")

    assert ("Revolt", 5) not in bot._purchased


def test_web_exception_is_logged_not_raised(bot) -> None:
    ScriptedWeb.result = RuntimeError("network down")
    lines = _logs(bot)

    bot._buy_via_web("Revolt", _item(5), bot._web_sessions["Revolt"], "credits")

    assert any("network down" in m for m in lines)
    assert ("Revolt", 5) not in bot._purchased


def test_cannot_afford_skips_purchase(bot) -> None:
    bot._ctx.clients["Revolt"].get_me.return_value = {
        "data": {"wallets": {"credits": 0, "bits": 0}}
    }
    ScriptedWeb.result = {"success": True}
    lines = _logs(bot)

    bot._buy_for_user(_item(5), bot.config.users[0])

    assert ("Revolt", 5) not in bot._purchased
    assert any("Can't afford" in m for m in lines)


def test_rares_only_user_skips_non_rare(bot) -> None:
    ScriptedWeb.result = {"success": True}
    rare_only = bot.config.users[0].__class__(username="Revolt", rares_only=True)
    plain = ShopItem.from_api({**_raw(5), "rare": False})

    bot._buy_for_user(plain, rare_only)

    assert ("Revolt", 5) not in bot._purchased


def _raw(item_id: int) -> dict[str, Any]:
    return {
        "id": item_id,
        "name": "x",
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


def test_web_buy_passes_through_rate_limiter(bot, monkeypatch) -> None:
    ScriptedWeb.result = {"success": True}
    calls: list[int] = []
    limiter = bot._web_limiter("Revolt")
    monkeypatch.setattr(limiter, "acquire", lambda: calls.append(1))

    bot._buy_via_web("Revolt", _item(5), bot._web_sessions["Revolt"], "credits")

    assert calls == [1]


def test_web_limiter_uses_trading_budget(bot) -> None:
    limiter = bot._web_limiter("Revolt")

    assert (limiter._limit, limiter._window) == (10, 60)
