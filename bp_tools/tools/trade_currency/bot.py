import time
from typing import Any

from bp_tools.core.contracts import BotBase
from bp_tools.core.runner import RunnerContext

from .constants import TICK, WALLET_REFRESH_INTERVAL
from .models import CurrencyExchangeConfig, ExchangeSideConfig, SideState, TradeSide


class CurrencyExchangeBot(BotBase[CurrencyExchangeConfig]):
    """
    Market-maker bot that sits on both sides of the currency exchange spread.

    Rate = bits per credit.

    - **offer-bits** (bits→credits): posts on the BID side, buying credits.
      Targets ``second_best_bid + TICK``, capped at ``max-rate`` ceiling.
    - **offer-credits** (credits→bits): posts on the ASK side, selling credits.
      Targets ``second_best_ask - TICK``, floored at ``max-rate``.

    Uses full orderbook to implement both aggressive AND regressive pricing:
    - Aggressive: if beaten, repost to beat the new best.
    - Regressive: if the order behind us disappears, back off to save money.

    On startup: cancels any existing open orders and places fresh limit orders.
    Each cycle: checks orderbook and adjusts position as needed.
    Does NOT re-up once fully filled.
    """

    name = "trade_currency"
    CONFIG_CLASS = CurrencyExchangeConfig
    init_before = [
        "2a0b9214-7f29-41f2-b913-067ff45fc778",  # item_sniper
        "8e61f94d-9ac5-4ca9-b1d9-ef60f0aa6a05",  # rare_snagger
    ]

    def __init__(
        self,
        ctx: RunnerContext,
        config: CurrencyExchangeConfig,
        poll_interval: float = 60.0,
        **kwargs: str,
    ) -> None:
        super().__init__(ctx, config, poll_interval=poll_interval, **kwargs)

        # Per-side state (replaces the old _ob_* / _oc_* instance vars)
        self._sides: dict[TradeSide, SideState] = {
            TradeSide.BID: SideState(),
            TradeSide.ASK: SideState(),
        }

        self._cycle_count: int = 0

        # Orderbook data (fetched each cycle)
        self._bid_levels: list[dict[str, Any]] = []  # sorted highest-first
        self._ask_levels: list[dict[str, Any]] = []  # sorted lowest-first
        self._best_bid: float | None = None
        self._best_ask: float | None = None

        # Wallet cache
        self._wallet: dict[str, int] = {}
        self._last_wallet_refresh: float = 0.0
        self._WALLET_REFRESH_INTERVAL = WALLET_REFRESH_INTERVAL

    def initialize(self) -> None:
        self._log("Starting up — cancelling all open orders", True)
        self._cancel_all_open_orders()
        self._refresh_wallet()
        self._log(
            f"Wallet — {self._wallet.get('credits', 0):,} credits, "
            f"{self._wallet.get('bits', 0):,} bits",
        )

        # Fetch initial orderbook so first cycle has data
        try:
            client = self._next_get_client()
            book = client.get_orderbook(limit=50)
            book_data = book.get("data", {})
            self._bid_levels = book_data.get("bids", [])
            self._ask_levels = book_data.get("asks", [])
            self._best_bid = self._bid_levels[0]["rate"] if self._bid_levels else None
            self._best_ask = self._ask_levels[0]["rate"] if self._ask_levels else None
        except Exception as exc:
            self._log(f"Error — fetching orderbook: {exc}")
            return

        # Place initial orders
        bid_placed = False
        for side in (TradeSide.BID, TradeSide.ASK):
            cfg = self._config_for(side)
            if cfg is None:
                continue
            if bid_placed:
                time.sleep(1.0)
            available = self._wallet.get(side.label, 0)
            amount = min(cfg.amount, available)
            if amount > 0:
                rate = self._compute_rate(side, cfg)
                state = self._sides[side]
                state.order_id = self._place_order(side, rate, amount)
                state.rate = rate if state.order_id else None
                if side is TradeSide.BID and state.order_id is not None:
                    bid_placed = True
            else:
                self._log(f"Not enough {side.label} to place order.")

    # ------------------------------------------------------------------
    # Side-aware accessors
    # ------------------------------------------------------------------

    def _config_for(self, side: TradeSide) -> ExchangeSideConfig | None:
        """Return the config for the given side, or None if not configured."""
        return (
            self.config.offer_bits
            if side is TradeSide.BID
            else self.config.offer_credits
        )

    def _best_price(self, side: TradeSide) -> float | None:
        """Best bid or best ask from the orderbook."""
        return self._best_bid if side is TradeSide.BID else self._best_ask

    def _levels(self, side: TradeSide) -> list[dict[str, Any]]:
        """Orderbook levels for the given side."""
        return self._bid_levels if side is TradeSide.BID else self._ask_levels

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _refresh_wallet(self) -> dict[str, int]:
        """Fetch fresh wallet from /me."""
        me = self._write_client.get_me()
        self._wallet = me.get("data", {}).get("wallets", {"credits": 0, "bits": 0})
        self._last_wallet_refresh = time.time()
        return self._wallet

    def _get_cached_wallet(self, force: bool = False) -> dict[str, int]:
        elapsed = time.time() - self._last_wallet_refresh
        if force or elapsed > self._WALLET_REFRESH_INTERVAL:
            return self._refresh_wallet()
        return self._wallet

    def _cancel_all_open_orders(self) -> None:
        """Cancel all open currency-exchange orders for the write user."""
        try:
            payload = self._write_client.get_my_orders()
        except Exception as exc:
            self._log(f"Error — fetching open orders: {exc}")
            return

        orders = payload.get("data", [])
        for i, order in enumerate(orders, 1):
            order_id = order.get("id")
            if order_id is None:
                continue
            self._log(f"Cancelling... ({i}/{len(orders)})", True)
            try:
                time.sleep(0.5)
                self._write_client.cancel_order(order_id)
            except Exception as exc:
                self._log(f"Failed to cancel order — {exc}")

    # ------------------------------------------------------------------
    # Generic order methods (parameterised by TradeSide)
    # ------------------------------------------------------------------

    def _place_order(self, side: TradeSide, rate: float, amount: int) -> int | None:
        """Place a limit order for the given side."""
        if amount <= 0:
            return None
        try:
            result = self._write_client.place_order(
                trade_type=side.trade_type,
                order_type="limit",
                amount=amount,
                limit_rate=rate,
            )
            order_id = result.get("data", {}).get("id")
            state = self._sides[side]
            state.amount = amount
            self._log(f"Posted {amount:,} {side.label} @ {rate:.2f}")
            return order_id
        except Exception as exc:
            self._log(f"Failed to place {side.label} order — {exc}")
            return None

    def _second_best(self, side: TradeSide) -> float | None:
        """Second-best rate on the given side of the book."""
        levels = self._levels(side)
        if len(levels) >= 2:
            return levels[1]["rate"]
        return None

    def _compute_rate(self, side: TradeSide, cfg: ExchangeSideConfig) -> float:
        """
        Compute the optimal rate for the given side.

        - If at top of book: regress to second_best ± TICK.
        - If NOT at top: go aggressive to beat the best.
        - Clamped at max_rate.
        """
        state = self._sides[side]
        best = self._best_price(side)

        if state.rate is not None and best is not None:
            if abs(best - state.rate) < TICK:
                # We're at top of book — regress to beat second best
                second = self._second_best(side)
                if second is not None:
                    target = round(second + side.tick_sign * TICK, 2)
                else:
                    target = cfg.max_rate
            else:
                # Not at top — beat the best aggressively
                target = round(best + side.tick_sign * TICK, 2)
        elif best is not None:
            target = round(best + side.tick_sign * TICK, 2)
        else:
            target = cfg.max_rate

        return side.clamp_rate(target, cfg.max_rate)

    def _get_order_remaining(self, order_id: int) -> int | None:
        """Look up remaining_amount for an order from our open orders."""
        try:
            payload = self._write_client.get_my_orders()
            for order in payload.get("data", []):
                if order.get("id") == order_id:
                    return order.get("remaining_amount", 0)
        except Exception as exc:
            self._log(f"Error — fetching order status: {exc}")
        return None

    def _cancel_and_repost(self, side: TradeSide, new_rate: float, reason: str) -> None:
        """Cancel current order on the given side and repost at new_rate."""
        state = self._sides[side]
        cfg = self._config_for(side)
        assert cfg is not None
        assert state.order_id is not None

        self._log(f"{reason} — repositioning @ {new_rate:.2f}...")

        remaining = self._get_order_remaining(state.order_id)

        try:
            self._write_client.cancel_order(state.order_id)
        except Exception as exc:
            self._log(f"Cancel failed ({side.label}) — {exc}")
            return

        time.sleep(0.5)

        if (
            remaining is not None
            and remaining > 0
            and side.rate_in_limit(new_rate, cfg.max_rate)
        ):
            state.order_id = self._place_order(side, new_rate, remaining)
            state.rate = new_rate if state.order_id else None
        else:
            if remaining == 0:
                self._log(f"{side.label.capitalize()} order filled!")
            else:
                self._log(f"Outside limit — {side.label} rate out of range.")
            state.order_id = None
            state.rate = None
            state.amount = None

    def _retry(self, side: TradeSide) -> None:
        """Retry a failed order placement on the given side."""
        cfg = self._config_for(side)
        assert cfg is not None
        state = self._sides[side]
        wallet = self._get_cached_wallet()
        available = wallet.get(side.label, 0)
        if available <= 0:
            return
        rate = self._compute_rate(side, cfg)
        if side.rate_in_limit(rate, cfg.max_rate):
            self._log(f"Retrying failed {side.label} placement...")
            amount = min(cfg.amount, available)
            state.order_id = self._place_order(side, rate, amount)
            state.rate = rate if state.order_id else None
            state.amount = amount if state.order_id else None

    def _monitor_side(self, side: TradeSide) -> bool:
        """
        Check and adjust one side of the spread.

        Returns True if an order was placed/reposted.
        """
        cfg = self._config_for(side)
        if cfg is None:
            return False

        state = self._sides[side]

        if state.order_id is not None and state.rate is not None:
            ideal = self._compute_rate(side, cfg)
            best = self._best_price(side)

            if best is not None and side.is_overtaken(best, state.rate):
                self._cancel_and_repost(
                    side,
                    ideal,
                    f"Overtaken — {side.label} spot rate moved "
                    f"({state.rate:.2f} → {best:.2f})",
                )
                return True
            elif abs(ideal - state.rate) >= TICK:
                self._cancel_and_repost(
                    side,
                    ideal,
                    f"Widening — {side.label} offer retracted @ {state.rate:.2f}",
                )
                return True
        elif state.order_id is None:
            self._retry(side)
            return state.order_id is not None
        return False

    # ------------------------------------------------------------------
    # Bot contract
    # ------------------------------------------------------------------

    def update(self) -> None:
        self._cycle_count += 1
        try:
            client = self._next_get_client()

            # Fetch full orderbook
            book = client.get_orderbook(limit=50)
            book_data = book.get("data", {})
            self._bid_levels = book_data.get("bids", [])
            self._ask_levels = book_data.get("asks", [])

            # Derive best bid/ask from the book
            self._best_bid = self._bid_levels[0]["rate"] if self._bid_levels else None
            self._best_ask = self._ask_levels[0]["rate"] if self._ask_levels else None

            # Build position summary for each side
            parts: list[str] = []
            for side in (TradeSide.ASK, TradeSide.BID):
                cfg = self._config_for(side)
                if cfg is None:
                    continue
                state = self._sides[side]
                if state.rate is not None and state.amount is not None:
                    parts.append(f"{state.amount:,} {side.label} @ {state.rate:.2f}")
                else:
                    parts.append(f"{side.label}: inactive")
            position = ", ".join(parts)

            self._log(
                f"Monitoring order book... (cycle {self._cycle_count}) | {position}",
                True,
            )
        except Exception as exc:
            self._log(f"Error — fetching orderbook: {exc}")

    def execute(self) -> None:
        self._monitor_and_repost()

    def _monitor_and_repost(self) -> None:
        bid_acted = self._monitor_side(TradeSide.BID)

        # Brief pause between adjusting both sides
        if bid_acted:
            time.sleep(1.0)

        self._monitor_side(TradeSide.ASK)

        # Check if both sides are done
        bid_state = self._sides[TradeSide.BID]
        ask_state = self._sides[TradeSide.ASK]
        if bid_state.order_id is None and ask_state.order_id is None:
            bid_done = self._config_for(TradeSide.BID) is None or bid_state.rate is None
            ask_done = self._config_for(TradeSide.ASK) is None or ask_state.rate is None
            if bid_done and ask_done:
                self._log("All orders filled or inactive. Holding.", True)
