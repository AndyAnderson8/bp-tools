"""RareCache: schema, dedupe, migrations, and the creator-filtered page scan."""

from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from bp_tools.core import rare_cache
from bp_tools.core.rare_cache import RareCache


def _cache(tmp_path: Path, migrations: tuple[str, ...] = ()) -> RareCache:
    return RareCache("test.db", base_dir=tmp_path, migrations=migrations)


def test_add_items_skips_duplicates(tmp_path: Path) -> None:
    cache = _cache(tmp_path)

    assert cache.add_items([(1, "a"), (2, "b")]) == 2
    assert cache.add_items([(2, "b"), (3, "c")]) == 1
    assert cache.load_ids() == [3, 2, 1]
    assert cache.load_names() == {1: "a", 2: "b", 3: "c"}
    assert cache.count() == 3


def test_empty_cache_counts_zero(tmp_path: Path) -> None:
    assert _cache(tmp_path).count() == 0


def test_migration_adds_column_once(tmp_path: Path) -> None:
    migration = "ALTER TABLE rare_items ADD COLUMN rap INTEGER DEFAULT NULL"
    cache = _cache(tmp_path, migrations=(migration,))

    # Opening repeatedly must not fail on "column already exists"
    cache.add_items([(1, "a")])
    cache.add_items([(2, "b")])

    with cache.connect() as conn:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(rare_items)")]
    assert "rap" in columns


def test_data_lives_in_tool_data_dir(tmp_path: Path) -> None:
    _cache(tmp_path).add_items([(1, "a")])

    assert (tmp_path / "data" / "test.db").exists()


def _page(items: list[tuple[int, str, int]]) -> dict[str, Any]:
    """Build a browse payload from (id, name, creator_id) tuples."""
    return {"data": [{"id": i, "name": n, "creator": {"id": c}} for i, n, c in items]}


def test_scan_keeps_only_official_creator(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(rare_cache.time, "sleep", lambda _s: None)
    client = mock.Mock()
    client.browse_items.side_effect = [
        _page([(10, "official", 1), (11, "fan made", 999)]),
        {"data": []},
    ]

    total = _cache(tmp_path).init_scan(client, config_dir=tmp_path)

    assert total == 1
    assert _cache(tmp_path).load_ids(tmp_path) == [10]


def test_scan_stops_when_page_has_only_known_items(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(rare_cache.time, "sleep", lambda _s: None)
    cache = _cache(tmp_path)
    cache.add_items([(10, "old")], tmp_path)
    client = mock.Mock()
    client.browse_items.return_value = _page([(10, "old", 1)])

    cache.init_scan(client, config_dir=tmp_path)

    assert client.browse_items.call_count == 1


def test_scan_survives_api_error(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(rare_cache.time, "sleep", lambda _s: None)
    client = mock.Mock()
    client.browse_items.side_effect = RuntimeError("down")
    messages: list[str] = []

    total = _cache(tmp_path).init_scan(
        client, config_dir=tmp_path, log=lambda m, _o: messages.append(m)
    )

    assert total == 0
    assert any("down" in m for m in messages)
