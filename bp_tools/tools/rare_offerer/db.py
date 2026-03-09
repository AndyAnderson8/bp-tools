"""SQLite cache for rare item IDs."""

import sqlite3
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from bp_tools.core.api import ApiClient

DB_NAME = "rare_offerer.db"
_DATA_DIR = "data"


def _db_path(config_dir: Path | None = None) -> Path:
    """Resolve path to the SQLite database file inside /data/."""
    base = config_dir if config_dir is not None else Path(__file__).resolve().parent
    data_dir = base / _DATA_DIR
    data_dir.mkdir(exist_ok=True)
    return data_dir / DB_NAME


@contextmanager
def _connect(
    config_dir: Path | None = None,
) -> Generator[sqlite3.Connection, None, None]:
    path = _db_path(config_dir)
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rare_items (
            item_id   INTEGER PRIMARY KEY,
            name      TEXT NOT NULL DEFAULT '',
            added_at  TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    try:
        yield conn
    finally:
        conn.close()


# ------------------------------------------------------------------
# Rare item cache
# ------------------------------------------------------------------


def load_rare_ids(config_dir: Path | None = None) -> list[int]:
    with _connect(config_dir) as conn:
        rows = conn.execute(
            "SELECT item_id FROM rare_items ORDER BY item_id DESC"
        ).fetchall()
        return [r[0] for r in rows]


def load_rare_names(
    config_dir: Path | None = None,
) -> dict[int, str]:
    with _connect(config_dir) as conn:
        rows = conn.execute("SELECT item_id, name FROM rare_items").fetchall()
        return {r[0]: r[1] for r in rows}


def count_items(config_dir: Path | None = None) -> int:
    with _connect(config_dir) as conn:
        row = conn.execute("SELECT COUNT(*) FROM rare_items").fetchone()
        return row[0] if row else 0


def add_items(
    items: list[tuple[int, str]],
    config_dir: Path | None = None,
) -> int:
    with _connect(config_dir) as conn:
        before = conn.execute("SELECT COUNT(*) FROM rare_items").fetchone()[0]
        conn.executemany(
            "INSERT OR IGNORE INTO rare_items" " (item_id, name) VALUES (?, ?)",
            items,
        )
        conn.commit()
        after = conn.execute("SELECT COUNT(*) FROM rare_items").fetchone()[0]
        return after - before


# ------------------------------------------------------------------
# Cache initialisation
# ------------------------------------------------------------------


def _process_page(
    data: list,
    existing_ids: set[int],
    batch: list[tuple[int, str]],
) -> tuple[int, int]:
    """Process one page of browse results.

    :returns: (new_count, seen_existing_count).
    """
    page_new = 0
    seen_existing = 0
    for item in data:
        creator = item.get("creator", {})
        creator_id = int(creator.get("id", 0)) if isinstance(creator, dict) else 0
        if creator_id != 1:
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


def init_rare_cache(
    client: ApiClient,
    config_dir: Path | None = None,
    log: Callable[[str, bool], None] | None = None,
) -> int:
    """
    One-time full scan: paginate all rare items and cache them.
    """
    import time

    from bp_tools.core.utils import color_print as print

    def _out(msg: str, overwrite: bool = False) -> None:
        if log is not None:
            log(msg, overwrite)
        else:
            print(msg)

    page = 1
    batch: list[tuple[int, str]] = []
    existing_ids = set(load_rare_ids(config_dir))

    while True:
        try:
            payload = client.browse_items(
                sort="newest",
                per_page=50,
                rare=True,
                page=page,
            )
        except Exception as exc:
            _out(f"Error on page {page} — {exc}")
            break

        data = payload.get("data", [])
        if not data:
            break

        page_new, seen_existing = _process_page(data, existing_ids, batch)

        if page_new == 0 and seen_existing > 0:
            _out(f"Page {page}: all items already cached" " — stopping.")
            break

        _out(
            f"Building rare item cache... (page {page})",
            True,
        )
        page += 1
        time.sleep(0.5)

    inserted = add_items(batch, config_dir)
    total = count_items(config_dir)
    _out(f"DB init complete — inserted {inserted} new items," f" {total} total cached.")
    return total
