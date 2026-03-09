# item_sniper

Auto-buy new and restocked items from the BrickPlanet shop.

## What It Does

- Polls the item catalog every 2 seconds
- Detects brand-new items and restocks of sold-out rares
- Buys instantly using the cheapest currency (credits or bits)
- Supports multiple accounts with per-user spending caps
- Round-robins GET requests across all configured accounts

## Config

```yaml
- name: item_sniper
  enabled: true
  config:
    poll-interval: 2             # seconds between cycles (default: 2)
    users:
      - username: "Revolt"
        rares-only: false        # false = buy ALL new items, true = rares only
        max-credits: 10000       # optional spending cap per item
        max-bits: 50000
      - username: "AltAccount"
        rares-only: true
    credit-to-bits-ratio: 50    # 1 credit = 50 bits (used to pick cheapest)
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `poll-interval` | float | `2` | Seconds between poll cycles |
| `users[].username` | string | *required* | BrickPlanet username (must have a token in `api_tokens`) |
| `users[].rares-only` | bool | `true` | Only buy rare/limited items |
| `users[].max-credits` | int | *none* | Max credits willing to spend per item |
| `users[].max-bits` | int | *none* | Max bits willing to spend per item |
| `credit-to-bits-ratio` | int | `50` | Conversion ratio for comparing currencies |

## Access

Requires membership in the [bp-tools authorization group](https://www.brickplanet.com/groups/2213) with **L2+** access.

## Files

| File | Purpose |
|------|---------|
| `bot.py` | `ItemSniperBot` - polling, detection, and buy logic |
| `models.py` | `ItemSniperConfig`, `ShopItem`, `UserSniperConfig` dataclasses |
| `__init__.py` | Plugin registration (`TOOL_NAME`, `BOT_CLASS`) |
