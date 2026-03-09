import time
from typing import Any

from bp_tools.core.contracts import BotBase

from .constants import OFFER_COOLDOWN

from .db import (
    clear_offer,
    count_items,
    get_existing_offers,
    init_rare_cache,
    load_rare_ids,
    load_rare_names,
    load_rare_raps,
    record_offer,
)
from .models import OffererConfig


class OffererBot(BotBase[OffererConfig]):
    """
    Places credit offers on all rare items at a percentage of their RAP.

    Processes one item per cycle with a 15s poll interval (4 offers/min).
    Tracks placed offers in a local SQLite DB to avoid duplicates.
    """

    name = "rare_offerer"
    CONFIG_CLASS = OffererConfig
    poll_interval = 1.0


    def __init__(self, ctx: Any, tool_config: dict[str, Any], **kwargs: Any) -> None:
        super().__init__(ctx, tool_config, **kwargs)
        self._scan_index: int = 0
        self._cycle_count: int = 1
        self._last_offer_time: float = 0.0
        self._rare_ids: list[int] = []
        self._rare_names: dict[int, str] = {}
        self._rare_raps: dict[int, int] = {}
        self._existing: dict[int, int] = {}
        self._pending_offer: tuple | None = None

    def initialize(self) -> None:
        config_dir = getattr(self._ctx, "config_dir", None)

        # Auto-populate cache if empty (same pattern as snagger)
        if count_items(config_dir) == 0:
            self._log("No rare items cached — scanning catalog...")
            client = self._next_get_client()
            init_rare_cache(client, config_dir=config_dir, log=self._log)

        all_ids = load_rare_ids(config_dir)
        self._rare_names = load_rare_names(config_dir)
        # TEMPORARY FALLBACK — local RAP values until API populates average_sales_price
        self._rare_raps = load_rare_raps(config_dir)
        self._existing = get_existing_offers(config_dir)

        # Filter out items we already have offers on or are in skip list
        skip = self._existing.keys() | self.config.skip_items
        self._rare_ids = [i for i in all_ids if i not in skip]
        self._log(
            f"Loaded {len(all_ids)} rare items, {len(self._rare_ids)} need offers.",
            True,
        )

    def _advance(self, config_dir: Any) -> None:
        """Move to the next item; wrap around = new cycle."""
        self._scan_index += 1
        if self._scan_index >= len(self._rare_ids):
            self._scan_index = 0
            self._cycle_count += 1
            self._existing = get_existing_offers(config_dir)
            # Re-filter for next cycle
            all_ids = load_rare_ids(config_dir)
            skip = self._existing.keys() | self.config.skip_items
            self._rare_ids = [i for i in all_ids if i not in skip]

    def update(self) -> None:
        """Pick the next item and place an offer if needed."""
        if not self._rare_ids:
            return

        config_dir = getattr(self._ctx, "config_dir", None)
        item_id = self._rare_ids[self._scan_index]
        name = self._rare_names.get(item_id, f"#{item_id}")

        self._log(
            f"Checking to place offers... ({self._scan_index + 1}/{len(self._rare_ids)}, cycle {self._cycle_count}) | "
            f"Current: {name} (ID: {item_id})",
            True,
        )

        # Skip if in skip-items override list
        if item_id in self.config.skip_items:
            self._advance(config_dir)
            return

        # Skip if we already have a pending offer tracked
        if item_id in self._existing:
            self._advance(config_dir)
            return

        # Calculate offer amount: RAP % or min-offer, whichever is greater
        rap = self._rare_raps.get(item_id, 0)
        rap_amount = int(rap * self.config.offer_percentage / 100) if rap > 0 else 0
        offer_amount = max(rap_amount, self.config.min_offer)

        # Queue the offer and advance
        self._pending_offer = (item_id, name, offer_amount)
        self._advance(config_dir)

    def execute(self) -> None:
        """Place the pending offer if one was set."""
        if not hasattr(self, "_pending_offer") or self._pending_offer is None:
            return

        # Rate limit: wait if an offer was placed too recently
        now = time.monotonic()
        elapsed = now - self._last_offer_time
        if elapsed < OFFER_COOLDOWN:
            remaining = OFFER_COOLDOWN - elapsed
            time.sleep(remaining)

        item_id, name, offer_amount = self._pending_offer
        self._pending_offer = None
        config_dir = getattr(self._ctx, "config_dir", None)

        try:
            result = self._write_client.make_offer(item_id, offer_amount)
            data = result.get("data", {})
            offer_id = data.get("id")
            if offer_id:
                record_offer(item_id, offer_id, offer_amount, config_dir)
            self._existing[item_id] = offer_id or 0
            self._last_offer_time = time.monotonic()
            self._log(f"Offered {offer_amount:,} credits on {name} (ID: {item_id})")
        except Exception as exc:
            err_msg = str(exc)
            if "OFFERS_DISABLED" not in err_msg:
                self._log(f"Error offering on {name} (ID: {item_id}): {exc}")
