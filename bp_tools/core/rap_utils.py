"""
TEMPORARY FALLBACK — RAP (Recent Average Price) utilities.

Remove this entire module once the BrickPlanet API populates
the ``average_sales_price`` field on GET /items/{id}.
"""

import json
import sqlite3
from pathlib import Path
from typing import Any


def import_rap_from_json(
    json_path: Path, conn: sqlite3.Connection
) -> int:
    """
    TEMPORARY FALLBACK — import RAP values from a local JSON export
    into any table that has ``item_id`` and ``rap`` columns.

    Expected JSON format: {"data": [{"id": 123, "value": 500, ...}, ...]}

    :returns: Number of items updated.
    """
    with open(json_path, "r") as f:
        raw = json.load(f)

    items = raw.get("data", raw) if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        return 0

    updates: list[tuple[int, int]] = []
    for item in items:
        item_id = item.get("id")
        value = item.get("value")
        if isinstance(item_id, int) and isinstance(value, int) and value > 0:
            updates.append((value, item_id))

    if not updates:
        return 0

    conn.executemany(
        "UPDATE rare_items SET rap = ? WHERE item_id = ?",
        updates,
    )
    conn.commit()
    return conn.total_changes


def load_raps_from_db(conn: sqlite3.Connection) -> dict[int, int]:
    """
    TEMPORARY FALLBACK — load item_id -> rap mapping from a rare_items table.
    """
    rows = conn.execute(
        "SELECT item_id, rap FROM rare_items WHERE rap IS NOT NULL AND rap > 0"
    ).fetchall()
    return {r[0]: r[1] for r in rows}
