"""
Generic SQLite cache of ``(id, name)`` items, one database file per tool.

Knows nothing about BrickPlanet: callers decide what goes in and how it is
fetched. Each tool owns its database file (``<base_dir>/data/<db_name>``)
and may add columns through ``migrations``.

The default table name ``rare_items`` is kept so databases created before
this module existed still open unchanged.
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

_DATA_DIR = "data"
DEFAULT_TABLE = "rare_items"


class ItemCache:
    """
    Keyed item store backed by SQLite.

    :param db_name: File name inside the tool's ``data`` directory.
    :param base_dir: Directory holding ``data/`` (usually the tool package).
    :param table: Table name; the default keeps existing databases readable.
    :param migrations: ``ALTER TABLE`` statements applied on every connection;
        errors (column already exists) are ignored.
    """

    def __init__(
        self,
        db_name: str,
        base_dir: Path,
        table: str = DEFAULT_TABLE,
        migrations: tuple[str, ...] = (),
    ) -> None:
        self._db_name = db_name
        self._base_dir = base_dir
        self._table = table
        self._migrations = migrations
        self._schema = (
            f"CREATE TABLE IF NOT EXISTS {table} ("
            "item_id INTEGER PRIMARY KEY, "
            "name TEXT NOT NULL DEFAULT '', "
            "added_at TEXT NOT NULL DEFAULT (datetime('now')))"
        )

    def _path(self, config_dir: Path | None) -> Path:
        base = config_dir if config_dir is not None else self._base_dir
        data_dir = base / _DATA_DIR
        data_dir.mkdir(parents=True, exist_ok=True)
        return data_dir / self._db_name

    @contextmanager
    def connect(
        self, config_dir: Path | None = None
    ) -> Generator[sqlite3.Connection, None, None]:
        """Open the database, ensuring the schema and migrations are applied."""
        conn = sqlite3.connect(str(self._path(config_dir)))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(self._schema)
        for statement in self._migrations:
            try:
                conn.execute(statement)
            except sqlite3.OperationalError:
                pass  # column already exists
        conn.commit()
        try:
            yield conn
        finally:
            conn.close()

    def load_ids(self, config_dir: Path | None = None) -> list[int]:
        """All item IDs, newest (highest ID) first."""
        with self.connect(config_dir) as conn:
            rows = conn.execute(
                f"SELECT item_id FROM {self._table} ORDER BY item_id DESC"
            ).fetchall()
            return [r[0] for r in rows]

    def load_names(self, config_dir: Path | None = None) -> dict[int, str]:
        """Mapping of item ID to name."""
        with self.connect(config_dir) as conn:
            rows = conn.execute(f"SELECT item_id, name FROM {self._table}").fetchall()
            return {r[0]: r[1] for r in rows}

    def count(self, config_dir: Path | None = None) -> int:
        """Number of stored items."""
        with self.connect(config_dir) as conn:
            row = conn.execute(f"SELECT COUNT(*) FROM {self._table}").fetchone()
            return row[0] if row else 0

    def add_items(
        self,
        items: list[tuple[int, str]],
        config_dir: Path | None = None,
    ) -> int:
        """
        Insert ``(item_id, name)`` rows, skipping duplicates.

        :returns: Number of rows actually inserted.
        """
        with self.connect(config_dir) as conn:
            before = conn.execute(f"SELECT COUNT(*) FROM {self._table}").fetchone()[0]
            conn.executemany(
                f"INSERT OR IGNORE INTO {self._table} (item_id, name) VALUES (?, ?)",
                items,
            )
            conn.commit()
            after = conn.execute(f"SELECT COUNT(*) FROM {self._table}").fetchone()[0]
            return after - before
