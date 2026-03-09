import time
from typing import Any

from bp_tools.core.contracts import BotBase

from .constants import WALLET_REFRESH_INTERVAL

from .db import count_items, init_rare_cache, load_rare_ids, load_rare_names, load_rare_raps
from .models import PendingBuy, SnaggerConfig


class SnaggerBot(BotBase[SnaggerConfig]):
    """
    Scans resale listings for rare items and auto-buys below a price threshold.

    Loads the rare item catalog from SQLite cache. If the cache is empty
    (first run), automatically scans the full catalog to populate it.
    Each cycle picks the next item, fetches its resellers, and buys if
    the cheapest listing is at or below the configured max-credits.
    Items with override of 0 are skipped entirely.
    """

    name = "rare_snagger"
    CONFIG_CLASS = SnaggerConfig
    poll_interval = 3.0

    def __init__(self, ctx: Any, tool_config: dict[str, Any], **kwargs: Any) -> None:
        super().__init__(ctx, tool_config, **kwargs)

        self._rare_item_ids: list[int] = []
        self._scan_index: int = 0
        self._cycle_count: int = 1
        self._pending_buy: PendingBuy | None = None

        # Wallet cache
        self._wallet: dict[str, int] = {}
        self._last_wallet_refresh: float = 0.0
        self._WALLET_REFRESH_INTERVAL = WALLET_REFRESH_INTERVAL

    def initialize(self) -> None:
        config_dir = getattr(self._ctx, "config_dir", None)

        # Auto-populate cache if empty
        if count_items(config_dir) == 0:
            self._log("No rare items cached — scanning catalog...")
            client = self._next_get_client()
            init_rare_cache(client, config_dir=config_dir, log=self._log)

        self._rare_item_ids = load_rare_ids(config_dir)
        self._rare_names: dict[int, str] = load_rare_names(config_dir)
        # TEMPORARY FALLBACK — local RAP values until API populates average_sales_price
        self._rare_raps: dict[int, int] = load_rare_raps(config_dir)
        self._log(f"Loaded {len(self._rare_item_ids)} rare items from cache.", True)

        # Fetch initial wallet
        self._refresh_wallet()
        self._log(
            f"Wallet — {self._wallet.get('credits', 0):,} credits, "
            f"{self._wallet.get('bits', 0):,} bits"
        )

    def update(self) -> None:
        self._pending_buy = None

        if not self._rare_item_ids:
            return

        # Pick the next item to scan
        item_id = self._rare_item_ids[self._scan_index]
        self._scan_index += 1

        # Reset after a full pass through the list
        if self._scan_index >= len(self._rare_item_ids):
            self._scan_index = 0
            self._cycle_count += 1

        item_name = self._rare_names.get(item_id, f"#{item_id}")

        # Check override — 0 means skip
        max_credits = self.config.max_for(item_id)

        self._log(
            f"Checking rares... ({self._scan_index}/{len(self._rare_item_ids)}, "
            f"cycle {self._cycle_count}) | Current: {item_name} (ID: {item_id})",
            True,
        )

        if max_credits <= 0:
            return

        # Use GET /items/{id} for scanning — gives us lowest_resale_price
        # and average_sales_price without calling get_resellers
        try:
            client = self._next_get_client()
            result = client.get_item(item_id)
        except Exception as exc:
            self._log(f"Error — fetching item {item_name}: {exc}")
            return

        data = result.get("data", {})
        price = data.get("lowest_resale_price")
        if not price or price <= 0:
            return

        # Compute the max we're willing to pay = greater of max-credits or RAP threshold
        avg_price = data.get("average_sales_price")
        # TEMPORARY FALLBACK — use local DB rap if API doesn't have it
        if (avg_price is None or avg_price == 0) and item_id in self._rare_raps:
            avg_price = self._rare_raps[item_id]
        rap_threshold = 0
        if self.config.rap_percentage > 0 and avg_price is not None and avg_price > 0:
            rap_threshold = int(avg_price * self.config.rap_percentage / 100)

        max_willing = max(max_credits, rap_threshold)

        if price <= max_willing:
            self._log(
                f"SNAG! {item_name} (ID: {item_id}) listed at {price:,} credits"
            )
            # Store item info — we'll fetch reseller_id in execute()
            self._pending_buy = PendingBuy(
                item_id=item_id,
                item_name=item_name,
                reseller_id=0,  # will be resolved in execute()
                price=price,
                seller="?",
            )

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

    def execute(self) -> None:
        if not self._pending_buy:
            return

        buy = self._pending_buy
        self._pending_buy = None

        import sys

        sys.stdout.write("\a")
        sys.stdout.flush()  # terminal bell

        # Resolve reseller_id — update() only checked price via get_item
        try:
            result = self._next_get_client().get_resellers(buy.item_id)
        except Exception as exc:
            self._log(f"Error — fetching resellers for {buy.item_name}: {exc}")
            return

        listings = result.get("data", [])
        if not listings:
            self._log(f"No resellers found for {buy.item_name} — listing may be gone.")
            return

        cheapest = listings[0]
        reseller_id = cheapest.get("id")
        actual_price = cheapest.get("price", 0)
        seller_name = cheapest.get("seller", {}).get("username", "?")

        if reseller_id is None or actual_price <= 0:
            return

        # Verify price hasn't changed since scan
        if actual_price > buy.price:
            self._log(
                f"Price changed — {buy.item_name} now {actual_price:,} "
                f"(was {buy.price:,}). Skipping."
            )
            return

        # Check cached wallet first, refresh if insufficient
        wallet = self._get_cached_wallet()
        credits_balance = wallet.get("credits", 0)
        if credits_balance < actual_price:
            # Might be stale — force refresh
            wallet = self._refresh_wallet()
            credits_balance = wallet.get("credits", 0)
            if credits_balance < actual_price:
                self._log(f"Not enough credits — {credits_balance:,} < {actual_price:,}")
                return

        try:
            result = self._write_client.buy_item(
                item_id=buy.item_id,
                currency="credits",
                reseller_id=reseller_id,
            )
            msg = result.get("data", {}).get("message", "")
            backpack_id = result.get("data", {}).get("backpack_id")
            suffix = (
                f"(backpack_id: {backpack_id})"
                if backpack_id
                else "(DRY RUN)" if not msg else msg
            )
            self._log(
                f"Snagged {buy.item_name} for {actual_price:,} credits from {seller_name}! {suffix}"
            )
            # Re-check same item next cycle in case there are more listings
            self._scan_index -= 1
            # Refresh wallet after purchase
            self._refresh_wallet()
        except Exception as exc:
            self._log(f"Buy failed — {buy.item_name}: {exc}")
