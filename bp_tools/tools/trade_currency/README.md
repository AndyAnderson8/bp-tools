# trade_currency

Market-maker bot for the BrickPlanet currency exchange.

## What It Does

- Places limit orders on both sides of the bits/credits spread
- Implements aggressive pricing (beat competitors) and regressive pricing (back off when alone)
- Uses the full orderbook to compute optimal rates
- Auto-cancels and reposts when the market moves
- Respects configurable rate ceilings/floors

## Config

```yaml
- name: trade_currency
  enabled: true
  config:
    username: "Revolt"
    offer-bits:                  # BID side: sell bits → buy credits
      amount: 200000             # bits to offer
      max-rate: 40.00            # ceiling: won't pay more than 40 bits/credit
    offer-credits:               # ASK side: sell credits → buy bits
      amount: 15000              # credits to offer
      max-rate: 70.00            # floor: won't accept less than 70 bits/credit
```

| Field | Type | Description |
|-------|------|-------------|
| `username` | string | Account to trade with |
| `offer-bits.amount` | int | Bits to place on the bid side |
| `offer-bits.max-rate` | float | Max bits/credit willing to pay |
| `offer-credits.amount` | int | Credits to place on the ask side |
| `offer-credits.max-rate` | float | Min bits/credit willing to accept |

Either side can be omitted to run one-sided.

## Files

| File | Purpose |
|------|---------|
| `bot.py` | `CurrencyExchangeBot` - orderbook polling, order management |
| `models.py` | `CurrencyExchangeConfig`, `ExchangeSideConfig` dataclasses |
| `__init__.py` | Plugin registration |
