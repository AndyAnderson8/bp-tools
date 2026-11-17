import sys

from bp_tools.core.contracts import BotBase
from bp_tools.core.runner import RunnerContext

from .db import (
    count_items,
    init_rare_cache,
    load_rare_ids,
    load_rare_names,
    load_rare_raps,
)
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

    def __init__(
        self,
        ctx: RunnerContext,
        config: SnaggerConfig,
        poll_interval: float = 3.0,
        **kwargs: str,
    ) -> None:
        super().__init__(ctx, config, poll_interval=poll_interval, **kwargs)

        self._rare_raps: dict[int, int] = {}
        self._rare_names: dict[int, str] = {}
        self._rare_item_ids: list[int] = []
        self._scan_index: int = 0
        self._cycle_count: int = 1
        self._pending_buy: PendingBuy | None = None

    def initialize(self) -> None:
        config_dir = self._ctx.config_dir

        # Autopopulate cache if empty
        if count_items(config_dir) == 0:
            self._info("No rare items cached - scanning catalog...")
            client = self._next_get_client()
            init_rare_cache(client, config_dir=config_dir, log=self._log)

        self._rare_item_ids = load_rare_ids(config_dir)
        self._rare_names = load_rare_names(config_dir)
        # TEMPORARY FALLBACK - local RAP values until API populates average_sales_price
        self._rare_raps = load_rare_raps(config_dir)
        self._info(f"Loaded {len(self._rare_item_ids)} rare items from cache.")

        # Fetch initial wallet
        balances = self._refresh_wallet()
        self._info(
            f"Wallet — {balances.get('credits', 0):,} credits, "
            f"{balances.get('bits', 0):,} bits"
        )

    def _refresh_items(self) -> None:
        """Incremental scan for new rare items, then reload from DB."""
        config_dir = self._ctx.config_dir
        client = self._next_get_client()
        init_rare_cache(client, config_dir=config_dir, log=self._log)
        self._rare_item_ids = load_rare_ids(config_dir)
        self._rare_names = load_rare_names(config_dir)
        self._rare_raps = load_rare_raps(config_dir)
        self._info(
            f"Refreshed — {len(self._rare_item_ids)} rare items.",
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
            self._refresh_items()

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

        # Scan with GET /items/{id}/resellers: the real active listings.
        # GET /items/{id}'s lowest_resale_price is stale/wrong (e.g. Bitpot
        # reports 1 while its cheapest listing is 2,999), so it isn't trusted.
        client = self._next_get_client()
        try:
            result = client.get_resellers(item_id)
        except Exception as exc:
            self._error(f"Fetching resellers for {item_name} failed: {exc}")
            return

        own = {name.lower() for name in self.config.usernames}
        listings = [
            listing
            for listing in result.get("data", [])
            if listing.get("id") is not None
            and (listing.get("price") or 0) > 0
            # Can't buy our own listing
            and (listing.get("seller") or {}).get("username", "").lower() not in own
        ]
        if not listings:
            return
        cheapest = min(listings, key=lambda listing: listing["price"])
        price = cheapest["price"]
        seller = (cheapest.get("seller") or {}).get("username", "?")

        # Compute the max we're willing to pay = greater of max-credits or RAP threshold
        avg_price = None
        if self.config.rap_percentage > 0 and price > max_credits:
            # RAP only matters when the price is over the flat max, so only then
            # spend a second request on GET /items/{id} for average_sales_price.
            try:
                avg_price = client.get_item(item_id).get("data", {}).get(
                    "average_sales_price"
                )
            except Exception as exc:
                self._error(f"Fetching item {item_name} failed: {exc}")
                return
        # TEMPORARY FALLBACK — use local DB rap if API doesn't have it
        if (avg_price is None or avg_price == 0) and item_id in self._rare_raps:
            avg_price = self._rare_raps[item_id]
        rap_threshold = 0
        if self.config.rap_percentage > 0 and avg_price is not None and avg_price > 0:
            rap_threshold = int(avg_price * self.config.rap_percentage / 100)

        max_willing = max(max_credits, rap_threshold)

        if price <= max_willing:
            self._highlight(
                f"Found {item_name} (ID: {item_id}) listed at {price:,} credits; "
                "checking the listing before purchase."
            )
            # execute() re-fetches the listing right before buying
            self._pending_buy = PendingBuy(
                item_id=item_id,
                item_name=item_name,
                reseller_id=cheapest["id"],
                price=price,
                seller=seller,
            )

    def _verify_listing(self, buy: "PendingBuy") -> tuple[int, int, str] | None:
        """Verify listing still exists and price is valid.

        :returns: (reseller_id, actual_price, seller_name) or None.
        """
        try:
            result = self._next_get_client().get_resellers(buy.item_id)
        except Exception as exc:
            self._error(f"Fetching resellers for {buy.item_name} failed: {exc}")
            return None

        listings = result.get("data", [])
        if not listings:
            self._warn(
                f"No resellers found for {buy.item_name}" " — listing may be gone."
            )
            return None

        cheapest = listings[0]
        reseller_id = cheapest.get("id")
        actual_price = cheapest.get("price", 0)
        seller_name = cheapest.get("seller", {}).get("username", "?")

        if reseller_id is None or actual_price <= 0:
            return None

        if actual_price > buy.price:
            self._info(
                f"Price changed — {buy.item_name} now {actual_price:,} "
                f"(was {buy.price:,}). Skipping."
            )
            return None

        return reseller_id, actual_price, seller_name

    def _attempt_purchase(
        self,
        buy: "PendingBuy",
        reseller_id: int,
        actual_price: int,
        seller_name: str,
    ) -> None:
        """Check wallet and attempt the purchase."""
        wallet = self._get_wallet()
        credits_balance = wallet.get("credits", 0)
        if credits_balance < actual_price:
            wallet = self._refresh_wallet()
            credits_balance = wallet.get("credits", 0)
            if credits_balance < actual_price:
                self._info(
                    f"Not enough credits" f" — {credits_balance:,} < {actual_price:,}"
                )
                return

        try:
            result = self._write_client.buy_item(
                item_id=buy.item_id,
                currency="credits",
                reseller_id=reseller_id,
            )
            msg = result.get("data", {}).get("message", "")
            backpack_id = result.get("data", {}).get("backpack_id")
            if backpack_id:
                suffix = f"(backpack_id: {backpack_id})"
            elif msg:
                suffix = f"({msg})"
            else:
                suffix = ""
            self._log(
                f"Snagged {buy.item_name} for {actual_price:,} credits"
                f" from {seller_name}! {suffix}"
            )
            self._scan_index -= 1
            self._refresh_wallet()
        except Exception as exc:
            self._error(f"Buy failed — {buy.item_name}: {exc}")

    def execute(self) -> None:
        if not self._pending_buy:
            return

        buy = self._pending_buy
        self._pending_buy = None

        sys.stdout.write("\a")
        sys.stdout.flush()  # terminal bell

        listing = self._verify_listing(buy)
        if listing is None:
            return

        reseller_id, actual_price, seller_name = listing
        self._attempt_purchase(buy, reseller_id, actual_price, seller_name)
