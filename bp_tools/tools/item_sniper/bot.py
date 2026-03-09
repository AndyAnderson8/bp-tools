import time
from typing import Any

from bp_tools.core.contracts import BotBase
from bp_tools.core.utils import color_print as print

from .constants import WALLET_REFRESH_INTERVAL
from .models import ItemSniperConfig, ShopItem, UserSniperConfig


class ItemSniperBot(BotBase[ItemSniperConfig]):
    """
    Monitors newly listed items via the official API and auto-buys them.

    Detection logic:
    - Tracks ``remaining_stock`` for every item seen from creator ID 1.
    - Triggers a buy when an item is seen for the first time with stock > 0,
      or when ``remaining_stock`` goes from 0 → >0 (restock).

    Polling strategy:
    - If ``rares-only`` is off, alternates between ``rare=true`` and no filter.
    - If ``rares-only`` is on, always queries with ``rare=true``.
    """

    name = "item_sniper"
    CONFIG_CLASS = ItemSniperConfig

    poll_interval = 2.0

    def __init__(self, ctx: Any, tool_config: dict[str, Any], **kwargs: Any) -> None:
        super().__init__(ctx, tool_config, **kwargs)

        # item_id → last known remaining_stock (0 means was sold out)
        self._stock_tracker: dict[int, int] = {}
        self._items_to_buy: list[ShopItem] = []
        self._loop_iterations: int = 0
        self._newest_rare: str = ""

        # Per-user wallet cache
        self._wallets: dict[str, dict[str, int]] = {}
        self._wallet_refresh_times: dict[str, float] = {}
        self._WALLET_REFRESH_INTERVAL = WALLET_REFRESH_INTERVAL

    def initialize(self) -> None:
        # Fetch initial wallets for all configured users
        for user_cfg in self.config.users:
            self._refresh_user_wallet(user_cfg.username)
        self._log_wallets()

    def authorize(self) -> None:
        """
        Custom auth for item_sniper based on role num.
        """
        # Run default entitlement check first (checks min_role_num from JSON)
        super().authorize()

        entitlements = getattr(self._ctx, "entitlements", None)

        # Read thresholds from entitlements (fall back to safe defaults)
        min_role = 0
        premium_role = 0
        if entitlements is not None and self.tool_uuid:
            min_role = entitlements.min_role_for(self.tool_uuid) or 0
            premium_role = entitlements.premium_role_for(self.tool_uuid) or 0

        # Block users below minimum role
        if min_role > 0:
            qualified = {u: r for u, r in self.user_roles.items() if r >= min_role}
            if not qualified and self.user_roles:
                raise PermissionError(
                    f"Bot '{self.name}' requires role_num >= {min_role}. "
                    f"User roles: {self.user_roles}"
                )

        # Per-user effects based on role
        delay_s = (
            entitlements.sniper_delay_for(self.tool_uuid)
            if entitlements is not None and self.tool_uuid
            else 5.0
        )

        self._user_delays: dict[str, float] = {}
        for username, role_num in self.user_roles.items():
            if premium_role > 0 and role_num < premium_role:
                self._user_delays[username] = delay_s
            else:
                self._user_delays[username] = 0.0

    def _resolve_poll_mode(self) -> tuple[bool | None, str]:
        """Decide whether to poll rare-only or all items."""
        all_rares = all(u.rares_only for u in self.config.users)
        if all_rares:
            return True, "rares"
        if self._loop_iterations % 2 == 0:
            return True, "rares"
        return None, "items"

    def _detect_buyable(self, item: ShopItem) -> None:
        """Check a single item for buy signals (new or restocked)."""
        prev_stock = self._stock_tracker.get(item.item_id)

        if item.rare:
            if prev_stock is None:
                if item.remaining_stock > 0 and item.on_sale:
                    self._items_to_buy.append(item)
            elif prev_stock == 0 and item.remaining_stock > 0 and item.on_sale:
                self._log(f"Restock detected — {item}")
                self._items_to_buy.append(item)
        else:
            if prev_stock is None and item.on_sale:
                self._items_to_buy.append(item)

        self._stock_tracker[item.item_id] = item.remaining_stock

    def update(self) -> None:
        self._items_to_buy.clear()

        client = self._next_get_client()
        rare_flag, label = self._resolve_poll_mode()

        newest = f" | Newest: {self._newest_rare}" if self._newest_rare else ""
        self._log(
            f"Polling new {label}... (cycle {self._loop_iterations}){newest}",
            True,
        )

        try:
            payload = client.browse_items(
                sort="newest",
                per_page=50,
                rare=rare_flag,
            )
        except Exception as exc:
            self._log(f"Error — polling items: {exc}")
            self._loop_iterations += 1
            return

        data = payload.get("data")
        if not isinstance(data, list):
            self._log("Error — unexpected items payload, missing list under key 'data'.")
            self._loop_iterations += 1
            return

        items = [ShopItem.from_api(item) for item in data]
        items = [item for item in items if item.creator_id == 1]

        for item in items:
            if item.rare:
                self._newest_rare = f"{item.name} (ID: {item.item_id})"
                break

        for item in items:
            self._detect_buyable(item)

        self._loop_iterations += 1

    def _pick_currency(
        self,
        item: ShopItem,
        caps: UserSniperConfig,
        wallet: dict[str, int],
    ) -> tuple[str, int] | None:
        """
        Choose the best currency to buy *item* with, considering:
        1. Per-user caps (``max-credits``, ``max-bits``).
        2. Actual wallet balance.
        3. Ratio-based cheapness when both are viable.
        """
        ratio = self.config.credit_to_bits_ratio

        credits_viable = item.credits > 0
        bits_viable = item.bits > 0

        if credits_viable and caps.max_credits is not None:
            credits_viable = item.credits <= caps.max_credits
        if bits_viable and caps.max_bits is not None:
            bits_viable = item.bits <= caps.max_bits

        if credits_viable:
            credits_viable = wallet.get("credits", 0) >= item.credits
        if bits_viable:
            bits_viable = wallet.get("bits", 0) >= item.bits

        if credits_viable and bits_viable:
            return item.best_currency(ratio)
        elif credits_viable:
            return ("credits", item.credits)
        elif bits_viable:
            return ("bits", item.bits)

        return None

    def _refresh_user_wallet(self, username: str) -> dict[str, int]:
        """Fetch fresh wallet for a specific user."""
        client = self._ctx.clients.get(username)
        if client is None:
            return {}
        me = client.get_me()
        wallet = me.get("data", {}).get("wallets", {"credits": 0, "bits": 0})
        self._wallets[username] = wallet
        self._wallet_refresh_times[username] = time.time()
        return wallet

    def _get_cached_user_wallet(
        self, username: str, force: bool = False
    ) -> dict[str, int]:
        elapsed = time.time() - self._wallet_refresh_times.get(username, 0.0)
        if (
            force
            or elapsed > self._WALLET_REFRESH_INTERVAL
            or username not in self._wallets
        ):
            return self._refresh_user_wallet(username)
        return self._wallets.get(username, {})

    def _log_wallets(self) -> None:
        for username, wallet in self._wallets.items():
            caps = self.config.caps_for(username)
            credits = wallet.get("credits", 0)
            bits = wallet.get("bits", 0)
            cr_str = f"{credits:,} credits"
            if caps.max_credits is not None:
                cr_str += f" (limit: {caps.max_credits:,})"
            bt_str = f"{bits:,} bits"
            if caps.max_bits is not None:
                bt_str += f" (limit: {caps.max_bits:,})"
            self._log(f"[{username}] Wallet — {cr_str}, {bt_str}")

    def _buy_for_user(self, item: ShopItem, user_cfg: UserSniperConfig) -> None:
        """Attempt to buy an item for a single user."""
        if user_cfg.rares_only and not item.rare:
            return

        username = user_cfg.username
        client = self._ctx.clients.get(username)
        if client is None:
            print(f"  [{username}] No API client — skipping.")
            return

        wallet = self._get_cached_user_wallet(username)
        pick = self._pick_currency(item, user_cfg, wallet)
        if pick is None:
            wallet = self._refresh_user_wallet(username)
            pick = self._pick_currency(item, user_cfg, wallet)
            if pick is None:
                print(f"  [{username}] Can't afford / exceeds caps — skipping.")
                return

        currency, price = pick

        delay = self._user_delays.get(username, 0.0)
        if delay > 0:
            print(f"  [{username}] Waiting {delay:.0f}s (role restricted)...")
            time.sleep(delay)

        print(f"  [{username}] Buying with {currency} ({price:,})")

        try:
            result = client.buy_item(
                item_id=item.item_id,
                currency=currency,
            )
            msg = result.get("data", {}).get("message", "Success")
            backpack_id = result.get("data", {}).get("backpack_id")
            print(f"  [{username}] Purchased! {msg} (backpack ID: {backpack_id})")
            self._refresh_user_wallet(username)
        except Exception as exc:
            print(f"  [{username}] Buy failed — {exc}")

    def execute(self) -> None:
        if not self._items_to_buy:
            return

        import sys

        sys.stdout.write("\a")
        sys.stdout.flush()  # terminal bell

        for item in self._items_to_buy:
            self._log(f"New/restocked item — {item} (stock: {item.remaining_stock})")
            for user_cfg in self.config.users:
                self._buy_for_user(item, user_cfg)

        self._items_to_buy.clear()
