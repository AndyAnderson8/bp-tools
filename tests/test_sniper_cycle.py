"""ItemSniperBot cycle: update() polling and execute() purchasing, offline."""

from typing import Any
from unittest import mock

import pytest

from bp_tools.core.config import AppConfig, UserToken
from bp_tools.core.runner import RunnerContext
from bp_tools.tools.item_sniper import bot as botmod
from bp_tools.tools.item_sniper.models import ItemSniperConfig


def _raw(item_id: int, **fields: Any) -> dict[str, Any]:
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


class RecordingWeb:
    bought: list[int] = []

    def __init__(self, *_a: Any, **_k: Any) -> None:
        pass

    def buy_item(self, item_id: int, currency: str = "credits") -> dict[str, Any]:
        RecordingWeb.bought.append(item_id)
        return {"success": True, "message": "ok"}


@pytest.fixture()
def bot(monkeypatch: pytest.MonkeyPatch):
    RecordingWeb.bought = []
    monkeypatch.setattr(botmod, "WebSession", RecordingWeb)
    monkeypatch.setattr(
        botmod.time, "sleep", lambda _s: None
    )  # skip role-restriction wait
    client = mock.Mock()
    client.get_me.return_value = {"data": {"wallets": {"credits": 1000, "bits": 0}}}
    client.get_inventory.return_value = {"data": [], "meta": {"last_page": 1}}
    client.browse_items.return_value = {"data": []}
    ctx = RunnerContext(
        config=AppConfig(users=[UserToken("Revolt", "t", "pw")], tools={}),
        clients={"Revolt": client},
    )
    cfg = ItemSniperConfig.from_dict(
        {"users": [{"username": "Revolt", "rares-only": False}]}
    )
    b = botmod.ItemSniperBot(ctx=ctx, config=cfg, poll_interval=0)
    b._seed_tracker = lambda: None  # type: ignore[method-assign]
    b.initialize()
    logs: list[str] = []
    b._log = lambda msg, *_: logs.append(msg)  # type: ignore[method-assign]
    return b, client, logs


def test_update_queues_newly_listed_item(bot) -> None:
    b, client, _ = bot
    client.browse_items.return_value = {"data": [_raw(42)]}

    b.update()

    assert [i.item_id for i in b._items_to_buy] == [42]


def test_update_ignores_other_creators(bot) -> None:
    b, client, _ = bot
    client.browse_items.return_value = {"data": [_raw(42, creator={"id": 999})]}

    b.update()

    assert b._items_to_buy == []


def test_execute_buys_queued_items_for_each_account(bot) -> None:
    b, client, _ = bot
    client.browse_items.return_value = {"data": [_raw(42)]}
    b.update()

    b.execute()

    assert RecordingWeb.bought == [42]


def test_poll_failure_is_logged_and_cycle_continues(bot) -> None:
    b, client, logs = bot
    client.browse_items.side_effect = RuntimeError("catalog down")

    b.update()  # must not raise

    assert b._items_to_buy == []
    assert any("catalog down" in m for m in logs)
    assert b._loop_iterations == 1


def test_malformed_payload_is_logged(bot) -> None:
    b, client, logs = bot
    client.browse_items.return_value = {"data": "not a list"}

    b.update()

    assert b._items_to_buy == []
    assert any("unexpected items payload" in m for m in logs)


def test_execute_with_nothing_queued_does_nothing(bot) -> None:
    b, _, _ = bot

    b.execute()

    assert RecordingWeb.bought == []
