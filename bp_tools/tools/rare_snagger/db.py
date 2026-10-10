"""SQLite cache of rare items for rare_snagger, including RAP values.

The ``rap`` column is a TEMPORARY FALLBACK until the API populates
``average_sales_price`` for every item.
"""

from pathlib import Path

from bp_tools.core.rare_cache import RareCache

DB_NAME = "rare_snagger.db"

_cache = RareCache(
    DB_NAME,
    base_dir=Path(__file__).resolve().parent,
    migrations=("ALTER TABLE rare_items ADD COLUMN rap INTEGER DEFAULT NULL",),
)

count_items = _cache.count
load_rare_ids = _cache.load_ids
load_rare_names = _cache.load_names
add_items = _cache.add_items
init_rare_cache = _cache.init_scan


def load_rare_raps(config_dir: Path | None = None) -> dict[int, int]:
    """Item ID -> RAP for items that have one. (TEMPORARY FALLBACK)"""
    with _cache.connect(config_dir) as conn:
        rows = conn.execute(
            "SELECT item_id, rap FROM rare_items WHERE rap IS NOT NULL AND rap > 0"
        ).fetchall()
        return {r[0]: r[1] for r in rows}
