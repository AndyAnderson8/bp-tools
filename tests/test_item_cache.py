"""ItemCache: generic keyed storage, dedupe, migrations and table naming."""

from pathlib import Path

from bp_tools.core.item_cache import ItemCache


def test_add_items_skips_duplicates(tmp_path: Path) -> None:
    cache = ItemCache("t.db", base_dir=tmp_path)

    assert cache.add_items([(1, "a"), (2, "b")]) == 2
    assert cache.add_items([(2, "b"), (3, "c")]) == 1
    assert cache.load_ids() == [3, 2, 1]
    assert cache.load_names() == {1: "a", 2: "b", 3: "c"}
    assert cache.count() == 3


def test_empty_store_counts_zero(tmp_path: Path) -> None:
    assert ItemCache("t.db", base_dir=tmp_path).count() == 0


def test_migration_adds_column_once(tmp_path: Path) -> None:
    migration = "ALTER TABLE rare_items ADD COLUMN rap INTEGER DEFAULT NULL"
    cache = ItemCache("t.db", base_dir=tmp_path, migrations=(migration,))

    cache.add_items([(1, "a")])
    cache.add_items([(2, "b")])  # reopening must not fail on the existing column

    with cache.connect() as conn:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(rare_items)")]
    assert "rap" in columns


def test_data_lives_in_data_subdirectory(tmp_path: Path) -> None:
    ItemCache("t.db", base_dir=tmp_path).add_items([(1, "a")])

    assert (tmp_path / "data" / "t.db").exists()


def test_custom_table_name_is_isolated(tmp_path: Path) -> None:
    a = ItemCache("t.db", base_dir=tmp_path, table="alpha")
    b = ItemCache("t.db", base_dir=tmp_path, table="beta")

    a.add_items([(1, "one")])

    assert a.count() == 1
    assert b.count() == 0


def test_config_dir_overrides_base_dir(tmp_path: Path) -> None:
    base = tmp_path / "base"
    override = tmp_path / "override"
    cache = ItemCache("t.db", base_dir=base)

    cache.add_items([(1, "a")], config_dir=override)

    assert (override / "data" / "t.db").exists()
    assert not (base / "data" / "t.db").exists()
