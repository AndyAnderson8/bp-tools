"""SQLite cache of rare items for rare_snagger, its catalog scan, and RAP values.

The ``rap`` column is a TEMPORARY FALLBACK until the API populates
``average_sales_price`` for every item.
"""

import time
from collections.abc import Callable
from pathlib import Path

from bp_tools.core.api import ApiClient
from bp_tools.core.item_cache import ItemCache

DB_NAME = "rare_snagger.db"
OFFICIAL_CREATOR_ID = 1

_cache = ItemCache(
    DB_NAME,
    base_dir=Path(__file__).resolve().parent,
    migrations=("ALTER TABLE rare_items ADD COLUMN rap INTEGER DEFAULT NULL",),
)

count_items = _cache.count
load_rare_ids = _cache.load_ids
load_rare_names = _cache.load_names
add_items = _cache.add_items


def load_rare_raps(config_dir: Path | None = None) -> dict[int, int]:
    """Item ID -> RAP for items that have one. (TEMPORARY FALLBACK)"""
    with _cache.connect(config_dir) as conn:
        rows = conn.execute(
            "SELECT item_id, rap FROM rare_items WHERE rap IS NOT NULL AND rap > 0"
        ).fetchall()
        return {r[0]: r[1] for r in rows}


def _collect_page(
    data: list,
    existing_ids: set[int],
    batch: list[tuple[int, str]],
) -> tuple[int, int]:
    """Add new official items from one browse page to *batch*.

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
        if item_id is None:
            continue
        if item_id in existing_ids:
            seen_existing += 1
        else:
            batch.append((item_id, item.get("name", "")))
            existing_ids.add(item_id)
            page_new += 1
    return page_new, seen_existing


def init_rare_cache(
    client: ApiClient,
    config_dir: Path | None = None,
    log: Callable[[str, bool], None] | None = None,
) -> int:
    """
    Page through rare items and cache new ones by the official creator.

    Stops at the first page that contains only already-cached items.

    :returns: Total number of cached items after the scan.
    """

    def _status(msg: str) -> None:
        if log is not None:
            log(msg, True)

    page = 1
    batch: list[tuple[int, str]] = []
    existing_ids = set(load_rare_ids(config_dir))

    while True:
        try:
            payload = client.browse_items(
                sort="newest", per_page=50, rare=True, page=page
            )
        except Exception as exc:
            _status(f"Error on page {page} — {exc}")
            break

        data = payload.get("data", [])
        if not data:
            break

        page_new, seen_existing = _collect_page(data, existing_ids, batch)
        if page_new == 0 and seen_existing > 0:
            break

        _status(f"Building rare item cache... (page {page})")
        page += 1
        time.sleep(0.5)

    add_items(batch, config_dir)
    return count_items(config_dir)
