# rare_snagger

Scans resale listings for rare items and auto-buys below a price threshold.

## What It Does

- Maintains a SQLite cache of all rare items from the catalog
- Cycles through each rare item, checking resale listings every 3 seconds
- If the cheapest listing is at or below your max price, it buys instantly
- Supports per-item price overrides (set to 0 to skip an item entirely)
- Auto-populates the cache on first run by scanning the full catalog

## Config

```yaml
- name: rare_snagger
  enabled: true
  config:
    username: "Revolt"
    max-credits: 500             # default max price for any rare resale
    rap-percentage: 50           # buy if price <= 50% of avg sale price (0 = off)
    poll-interval: 3             # seconds between cycles (default: 3)
    overrides:                   # per-item overrides
      - item-id: 42
        max-credits: 1000        # pay up to 1000 for this specific item
      - item-id: 99
        max-credits: 0           # skip this item entirely
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `username` | string | *required* | Account to buy with |
| `max-credits` | int | `500` | Default max price for any rare listing |
| `rap-percentage` | int | `0` | Buy if price ≤ X% of avg sale price (0 = disabled) |
| `poll-interval` | float | `3` | Seconds between poll cycles |
| `overrides[].item-id` | int | - | Item ID to override |
| `overrides[].max-credits` | int | - | Max price for this item (0 = skip) |

## Files

| File | Purpose |
|------|---------|
| `bot.py` | `SnaggerBot` - resale scanning and buy logic |
| `models.py` | `SnaggerConfig`, `PendingBuy`, `ItemOverride` dataclasses |
| `db.py` | SQLite cache for rare item IDs and RAP values |
| `constants.py` | Tuning constants (wallet refresh interval) |
| `__init__.py` | Plugin registration |
