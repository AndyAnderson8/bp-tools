"""SQLite cache of rare item IDs for rare_offerer (see bp_tools.core.rare_cache)."""

from pathlib import Path

from bp_tools.core.rare_cache import RareCache

DB_NAME = "rare_offerer.db"

_cache = RareCache(DB_NAME, base_dir=Path(__file__).resolve().parent)

count_items = _cache.count
load_rare_ids = _cache.load_ids
load_rare_names = _cache.load_names
add_items = _cache.add_items
init_rare_cache = _cache.init_scan
