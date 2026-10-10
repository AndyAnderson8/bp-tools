"""
SQLite cache of rare item IDs/names, shared by the rare-item tools.

Each tool owns its own database file (``<tool>/data/<db_name>``) and may
add columns through ``migrations``. The first full catalog scan
(:meth:`RareCache.init_scan`) pages through ``GET /items?rare=1`` and keeps
items created by the official creator (ID 1).
"""

import sqlite3
import time
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from bp_tools.core.api import ApiClient

_DATA_DIR = "data"
OFFICIAL_CREATOR_ID = 1

_BASE_SCHEMA = """
    CREATE TABLE IF NOT EXISTS rare_items (
        item_id   INTEGER PRIMARY KEY,
        name      TEXT NOT NULL DEFAULT '',
        added_at  TEXT NOT NULL DEFAULT (datetime('now'))
    )
"""


class RareCache:
    """
    Rare item cache backed by SQLite.

    :param db_name: File name inside the tool's ``data`` directory.
    :param base_dir: Directory holding ``data/`` (usually the tool package).
    :param migrations: ``ALTER TABLE`` statements applied on every connection;
        errors (column already exists) are ignored.
    """

    def __init__(
        self,
        db_name: str,
        base_dir: Path,
        migrations: tuple[str, ...] = (),
    ) -> None:
        self._db_name = db_name
        self._base_dir = base_dir
        self._migrations = migrations

    def _path(self, config_dir: Path | None) -> Path:
        base = config_dir if config_dir is not None else self._base_dir
        data_dir = base / _DATA_DIR
        data_dir.mkdir(exist_ok=True)
        return data_dir / self._db_name

    @contextmanager
    def connect(
        self, config_dir: Path | None = None
    ) -> Generator[sqlite3.Connection, None, None]:
        """Open the cache database, ensuring schema and migrations are applied."""
        conn = sqlite3.connect(str(self._path(config_dir)))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(_BASE_SCHEMA)
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
        """All cached item IDs, newest first."""
        with self.connect(config_dir) as conn:
            rows = conn.execute(
                "SELECT item_id FROM rare_items ORDER BY item_id DESC"
            ).fetchall()
            return [r[0] for r in rows]

    def load_names(self, config_dir: Path | None = None) -> dict[int, str]:
        """Mapping of item ID to name."""
        with self.connect(config_dir) as conn:
            rows = conn.execute("SELECT item_id, name FROM rare_items").fetchall()
            return {r[0]: r[1] for r in rows}

    def count(self, config_dir: Path | None = None) -> int:
        """Number of cached items."""
        with self.connect(config_dir) as conn:
            row = conn.execute("SELECT COUNT(*) FROM rare_items").fetchone()
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
            before = conn.execute("SELECT COUNT(*) FROM rare_items").fetchone()[0]
            conn.executemany(
                "INSERT OR IGNORE INTO rare_items (item_id, name) VALUES (?, ?)",
                items,
            )
            conn.commit()
            after = conn.execute("SELECT COUNT(*) FROM rare_items").fetchone()[0]
            return after - before

    def init_scan(
        self,
        client: ApiClient,
        config_dir: Path | None = None,
        log: Callable[[str, bool], None] | None = None,
    ) -> int:
        """
        Page through rare items and cache any new ones by the official creator.

        Stops at the first page that contains only already-cached items.

        :param log: Optional ``(msg, overwrite)`` callback for progress.
        :returns: Total number of cached items after the scan.
        """

        def _status(msg: str, overwrite: bool = False) -> None:
            if log is not None:
                log(msg, overwrite)

        page = 1
        batch: list[tuple[int, str]] = []
        existing_ids = set(self.load_ids(config_dir))

        while True:
            try:
                payload = client.browse_items(
                    sort="newest",
                    per_page=50,
                    rare=True,
                    page=page,
                )
            except Exception as exc:
                _status(f"Error on page {page} — {exc}")
                break

            data = payload.get("data", [])
            if not data:
                break

            page_new, seen_existing = _process_page(data, existing_ids, batch)
            if page_new == 0 and seen_existing > 0:
                break

            _status(f"Building rare item cache... (page {page})", True)
            page += 1
            time.sleep(0.5)

        self.add_items(batch, config_dir)
        return self.count(config_dir)


def _process_page(
    data: list,
    existing_ids: set[int],
    batch: list[tuple[int, str]],
) -> tuple[int, int]:
    """
    Collect new official items from one page of browse results.

    :returns: ``(new_count, seen_existing_count)``.
    """
    page_new = 0
    seen_existing = 0
    for item in data:
        creator = item.get("creator", {})
        creator_id = int(creator.get("id", 0)) if isinstance(creator, dict) else 0
        if creator_id != OFFICIAL_CREATOR_ID:
            continue

        item_id = item.get("id")
        name = item.get("name", "")
        if item_id is None:
            continue

        if item_id in existing_ids:
            seen_existing += 1
        else:
            batch.append((item_id, name))
            existing_ids.add(item_id)
            page_new += 1

    return page_new, seen_existing
