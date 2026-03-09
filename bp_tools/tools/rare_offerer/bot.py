import time

from bp_tools.core.contracts import BotBase
from bp_tools.core.runner import RunnerContext

from .constants import OFFER_COOLDOWN
from .db import count_items, init_rare_cache, load_rare_ids, load_rare_names
from .models import OffererConfig


class OffererBot(BotBase[OffererConfig]):
    """
    Places credit offers on all rare items at a flat rate.

    Iterates through all items in the cache. Silently skips
    items that already have offers (API returns DUPLICATE_OFFER).
    """

    name = "rare_offerer"
    CONFIG_CLASS = OffererConfig

    def __init__(
        self,
        ctx: RunnerContext,
        config: OffererConfig,
        poll_interval: float = 10.0,
        **kwargs: str,
    ) -> None:
        super().__init__(ctx, config, poll_interval=poll_interval, **kwargs)
        self._scan_index: int = 0
        self._cycle_count: int = 1
        self._last_offer_time: float = 0.0
        self._rare_ids: list[int] = []
        self._rare_names: dict[int, str] = {}
        self._pending_offer: tuple | None = None

    def initialize(self) -> None:
        config_dir = getattr(self._ctx, "config_dir", None)

        if count_items(config_dir) == 0:
            self._log("No rare items cached — scanning catalog...")
            client = self._next_get_client()
            init_rare_cache(client, config_dir=config_dir, log=self._log)

        self._rare_ids = load_rare_ids(config_dir)
        self._rare_names = load_rare_names(config_dir)
        self._log(
            f"Loaded {len(self._rare_ids)} rare items.",
            True,
        )

    def _advance(self) -> None:
        """Move to the next item; wrap around = new cycle."""
        self._scan_index += 1
        if self._scan_index >= len(self._rare_ids):
            self._scan_index = 0
            self._cycle_count += 1
            self._refresh_items()

    def _refresh_items(self) -> None:
        """Incremental scan for new rare items, then reload from DB."""
        config_dir = getattr(self._ctx, "config_dir", None)
        client = self._next_get_client()
        init_rare_cache(client, config_dir=config_dir, log=self._log)
        self._rare_ids = load_rare_ids(config_dir)
        self._rare_names = load_rare_names(config_dir)
        self._log(
            f"Refreshed — {len(self._rare_ids)} rare items.",
            True,
        )

    def update(self) -> None:
        """Pick the next item and queue an offer."""
        if not self._rare_ids:
            return

        item_id = self._rare_ids[self._scan_index]
        name = self._rare_names.get(item_id, f"#{item_id}")

        idx = self._scan_index + 1
        total = len(self._rare_ids)
        self._log(
            f"Placing rare offers... ({idx}/{total}, "
            f"cycle {self._cycle_count}) | "
            f"Current: {name} (ID: {item_id})",
            True,
        )

        # Don't queue if still in cooldown — return without
        # advancing so we retry this item next cycle.
        if time.monotonic() - self._last_offer_time < OFFER_COOLDOWN:
            return

        # Queue the offer and advance
        self._pending_offer = (
            item_id,
            name,
            self.config.base_offer,
        )
        self._advance()

    def execute(self) -> None:
        """Place the pending offer if one was set."""
        if self._pending_offer is None:
            return

        item_id, name, offer_amount = self._pending_offer
        self._pending_offer = None

        try:
            self._write_client.make_offer(item_id, offer_amount)
            self._last_offer_time = time.monotonic()
            self._log(f"Offered {offer_amount:,} credits" f" on {name} (ID: {item_id})")
        except Exception as exc:
            err_msg = str(exc)
            # Silently skip 422s (duplicate, insufficient, etc.)
            if "422" not in err_msg:
                self._log(f"Error offering on {name}" f" (ID: {item_id}): {exc}")
