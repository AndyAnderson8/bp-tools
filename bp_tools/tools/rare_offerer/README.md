# rare_offerer

Places credit offers on all rare items at a flat rate.

## What It Does

- Maintains a SQLite cache of all rare items from the catalog
- Cycles through each rare item every 3 seconds, placing a flat credit offer
- Silently skips items that already have offers (API returns DUPLICATE_OFFER)
- Refreshes the item cache at the start of each full cycle
- Auto-populates the cache on first run by scanning the full catalog
- Enforces a 16-second cooldown between offer POST calls (4/minute)

## Config

```yaml
- name: rare_offerer
  enabled: true
  config:
    username: "Revolt"
    base-offer: 2                # credits to offer on each item
    poll-interval: 10            # seconds between cycles (default: 10)
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `username` | string | *required* | Account to place offers with |
| `base-offer` | int | `2` | Credits to offer on every rare item |
| `poll-interval` | float | `10` | Seconds between poll cycles |

## Files

| File | Purpose |
|------|---------|
| `bot.py` | `OffererBot` - cycle through rares, place offers |
| `models.py` | `OffererConfig` dataclass |
| `db.py` | SQLite cache for rare item IDs (shared schema with snagger) |
| `constants.py` | Tuning constants (offer cooldown) |
| `__init__.py` | Plugin registration |
