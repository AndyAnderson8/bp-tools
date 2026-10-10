"""Rare-item catalog scan, checked for both rare tools (each owns its own copy)."""

from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from bp_tools.tools.rare_offerer import db as offerer_db
from bp_tools.tools.rare_snagger import db as snagger_db

TOOL_DBS = [offerer_db, snagger_db]


@pytest.fixture(params=TOOL_DBS, ids=["rare_offerer", "rare_snagger"])
def db(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch):
    module = request.param
    monkeypatch.setattr(module.time, "sleep", lambda _s: None)
    return module


def _page(items: list[tuple[int, str, int]]) -> dict[str, Any]:
    return {"data": [{"id": i, "name": n, "creator": {"id": c}} for i, n, c in items]}


def test_keeps_only_official_creator(db, tmp_path: Path) -> None:
    client = mock.Mock()
    client.browse_items.side_effect = [
        _page([(10, "official", 1), (11, "fan made", 999)]),
        {"data": []},
    ]

    total = db.init_rare_cache(client, config_dir=tmp_path)

    assert total == 1
    assert db.load_rare_ids(tmp_path) == [10]


def test_stops_when_a_page_has_only_known_items(db, tmp_path: Path) -> None:
    db.add_items([(10, "old")], tmp_path)
    client = mock.Mock()
    client.browse_items.return_value = _page([(10, "old", 1)])

    db.init_rare_cache(client, config_dir=tmp_path)

    assert client.browse_items.call_count == 1


def test_api_error_ends_scan_without_raising(db, tmp_path: Path) -> None:
    client = mock.Mock()
    client.browse_items.side_effect = RuntimeError("down")
    messages: list[str] = []

    total = db.init_rare_cache(
        client, config_dir=tmp_path, log=lambda m, _o: messages.append(m)
    )

    assert total == 0
    assert any("down" in m for m in messages)


def test_pages_until_no_new_items(db, tmp_path: Path) -> None:
    client = mock.Mock()
    client.browse_items.side_effect = [
        _page([(3, "c", 1), (2, "b", 1)]),
        _page([(1, "a", 1)]),
        _page([]),
    ]

    total = db.init_rare_cache(client, config_dir=tmp_path)

    assert total == 3
    assert db.load_rare_ids(tmp_path) == [3, 2, 1]
