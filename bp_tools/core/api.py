"""Thin wrapper around requests.Session for the BrickPlanet v1 API."""

import fnmatch
import time
from collections import deque
from pathlib import Path
from typing import Any, Optional

import yaml
from requests import Response, Session

from bp_tools.core.constants import BASE_URL
from bp_tools.core.utils import color_print as print

# Fallback defaults if no rate_limits.yaml is found
_DEFAULT_RATE_LIMITS: dict[str, Any] = {
    "tiers": {
        "default": {"limit": 60, "window": 60},
        "write": {"limit": 30, "window": 60},
        "trading": {"limit": 10, "window": 60},
    },
    "routes": {},
}


class _RateLimiter:
    """Per-tier sliding-window rate limiter."""

    def __init__(self, limit: int, window: int) -> None:
        self._limit = limit
        self._window = window
        self._timestamps: deque[float] = deque()

    def acquire(self) -> None:
        """Block until a request slot is available."""
        now = time.monotonic()
        # Purge timestamps outside the window
        while self._timestamps and self._timestamps[0] <= now - self._window:
            self._timestamps.popleft()
        if len(self._timestamps) >= self._limit:
            sleep_for = self._timestamps[0] + self._window - now
            if sleep_for > 0:
                print(
                    f"Rate limit ({self._limit}/{self._window}s) — sleeping {sleep_for:.1f}s"
                )
                time.sleep(sleep_for)
        self._timestamps.append(time.monotonic())


def load_rate_limits(path: Optional[Path] = None) -> dict[str, Any]:
    """
    Load rate limits from a YAML file.

    :param path: Path to ``rate_limits.yaml``. If ``None``, searches CWD.
    :returns: Parsed rate-limits dict.
    """
    if path is None:
        path = Path.cwd() / "rate_limits.yaml"
    if path.exists():
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    return _DEFAULT_RATE_LIMITS


class ApiClient:
    """
    HTTP client for the BrickPlanet v1 API.

    Uses Bearer-token auth and enforces configurable per-tier rate
    limits loaded from ``rate_limits.yaml``.
    """

    def __init__(
        self,
        token: str,
        rate_limits: Optional[dict[str, Any]] = None,
        dry_run: bool = False,
    ) -> None:
        """
        :param token: BrickPlanet API token (Bearer).
        :param rate_limits: Parsed rate-limits dict (from ``load_rate_limits``).
        :param dry_run: If True, mutating requests (POST/DELETE) are printed instead of sent.
        """
        self._session = Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )
        self.dry_run = dry_run

        # Rate limiting
        rl = rate_limits or _DEFAULT_RATE_LIMITS
        tiers_raw = rl.get("tiers", {})
        self._limiters: dict[str, _RateLimiter] = {}
        for tier_name, tier_cfg in tiers_raw.items():
            self._limiters[tier_name] = _RateLimiter(
                limit=int(tier_cfg.get("limit", 60)),
                window=int(tier_cfg.get("window", 60)),
            )

        self._routes: dict[str, str] = rl.get("routes", {})

    # ------------------------------------------------------------------
    # Low-level helpers
    # ------------------------------------------------------------------

    def _tier_for(self, method: str, path: str) -> str:
        """Resolve which rate-limit tier a request belongs to."""
        key = f"{method.upper()} {path}"
        for pattern, tier in self._routes.items():
            if fnmatch.fnmatch(key, pattern):
                return tier
        return "default"

    def _rate_limit(self, method: str, path: str) -> None:
        """Block if the relevant tier's rate limit is exhausted."""
        tier = self._tier_for(method, path)
        limiter = self._limiters.get(tier) or self._limiters.get("default")
        if limiter:
            limiter.acquire()

    def _handle_429(self, response: Response) -> bool:
        """Sleep on server-side 429 as a fallback. Returns True if retryable."""
        if response.status_code == 429:
            retry_after = int(response.headers.get("Retry-After", "5"))
            print(f"429 Too Many Requests — sleeping {retry_after}s")
            time.sleep(retry_after)
            return True
        return False

    def get(
        self,
        path: str,
        params: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """
        GET request to the API.

        :param path: Path relative to base URL, e.g. ``/items``.
        :param params: Query-string parameters.
        :returns: Parsed JSON response.
        """
        url = f"{BASE_URL}{path}"
        for _ in range(3):
            self._rate_limit("GET", path)
            response = self._session.get(url, params=params)
            if not self._handle_429(response):
                break
        response.raise_for_status()
        return response.json()

    def post(
        self,
        path: str,
        json_body: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """
        POST request to the API.

        :param path: Path relative to base URL.
        :param json_body: JSON request body.
        :returns: Parsed JSON response.
        """
        if self.dry_run:
            print(f"  [DRY RUN] POST {path} body={json_body}")
            return {"data": {"message": "dry-run"}}
        url = f"{BASE_URL}{path}"
        for _ in range(3):
            self._rate_limit("POST", path)
            response = self._session.post(url, json=json_body)
            if not self._handle_429(response):
                break
        response.raise_for_status()
        return response.json()

    def delete(self, path: str) -> dict[str, Any]:
        """
        DELETE request to the API.

        :param path: Path relative to base URL.
        :returns: Parsed JSON response.
        """
        if self.dry_run:
            print(f"  [DRY RUN] DELETE {path}")
            return {"data": {"message": "dry-run"}}
        url = f"{BASE_URL}{path}"
        for _ in range(3):
            self._rate_limit("DELETE", path)
            response = self._session.delete(url)
            if not self._handle_429(response):
                break
        response.raise_for_status()
        return response.json()

    # ------------------------------------------------------------------
    # High-level API methods — Items
    # ------------------------------------------------------------------

    def get_me(self) -> dict[str, Any]:
        """
        ``GET /me`` — current user profile and wallet balances.
        """
        return self.get("/me")

    def get_inventory(
        self,
        *,
        per_page: int = 50,
        page: int = 1,
        rare: Optional[bool] = None,
    ) -> dict[str, Any]:
        """
        ``GET /me/inventory`` — items in your backpack.
        """
        params: dict[str, Any] = {"per_page": per_page, "page": page}
        if rare is not None:
            params["rare"] = 1 if rare else 0
        return self.get("/me/inventory", params=params)

    def get_group_membership(self, group_id: int) -> dict[str, Any]:
        """
        ``GET /groups/{id}/my-membership`` — your membership status and role.
        """
        return self.get(f"/groups/{group_id}/my-membership")

    def browse_items(
        self,
        *,
        sort: str = "newest",
        on_sale: Optional[bool] = None,
        rare: Optional[bool] = None,
        search: Optional[str] = None,
        item_type: Optional[int] = None,
        per_page: int = 50,
        page: int = 1,
    ) -> dict[str, Any]:
        """
        ``GET /items`` — paginated item catalog.
        """
        params: dict[str, Any] = {
            "sort": sort,
            "per_page": per_page,
            "page": page,
        }
        if on_sale is not None:
            params["on_sale"] = 1 if on_sale else 0
        if rare is not None:
            params["rare"] = 1 if rare else 0
        if search is not None:
            params["search"] = search
        if item_type is not None:
            params["type"] = item_type
        return self.get("/items", params=params)

    def get_item(self, item_id: int) -> dict[str, Any]:
        """
        ``GET /items/{id}`` — full details for a single item.
        """
        return self.get(f"/items/{item_id}")

    def buy_item(
        self,
        item_id: int,
        currency: str = "credits",
        reseller_id: Optional[int] = None,
    ) -> dict[str, Any]:
        """
        ``POST /items/{id}/buy`` — purchase from catalog or resale.
        """
        body: dict[str, Any] = {"currency": currency}
        if reseller_id is not None:
            body["reseller_id"] = reseller_id
        return self.post(f"/items/{item_id}/buy", json_body=body)

    def get_resellers(self, item_id: int) -> dict[str, Any]:
        """
        ``GET /items/{id}/resellers`` — active resale listings, cheapest first.
        """
        return self.get(f"/items/{item_id}/resellers")

    def make_offer(
        self,
        item_id: int,
        offer_amount: int,
        message: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        ``POST /items/{id}/offers`` — send a credits offer to the owner.

        Offers auto-expire after 7 days if not responded to.
        """
        body: dict[str, Any] = {"offer_amount": offer_amount}
        if message is not None:
            body["message"] = message
        return self.post(f"/items/{item_id}/offers", json_body=body)

    def withdraw_offer(self, offer_id: int) -> dict[str, Any]:
        """
        ``DELETE /offers/{id}`` — withdraw a pending offer you made.
        """
        return self.delete(f"/offers/{offer_id}")

    # ------------------------------------------------------------------
    # Currency Exchange
    # ------------------------------------------------------------------

    def get_ticker(self) -> dict[str, Any]:
        """
        ``GET /currency/ticker`` — best bid/ask, spread, last price.
        """
        return self.get("/currency/ticker")

    def get_orderbook(self, limit: int = 20) -> dict[str, Any]:
        """
        ``GET /currency/orderbook`` — open orders grouped by price level.
        """
        return self.get("/currency/orderbook", params={"limit": limit})

    def get_my_orders(self) -> dict[str, Any]:
        """
        ``GET /currency/orders`` — your open limit orders.
        """
        return self.get("/currency/orders")

    def place_order(
        self,
        trade_type: str,
        order_type: str,
        amount: int,
        limit_rate: Optional[float] = None,
    ) -> dict[str, Any]:
        """
        ``POST /currency/orders`` — place a market or limit order.

        :param trade_type: ``bits-to-credits`` or ``credits-to-bits``.
        :param order_type: ``market`` or ``limit``.
        :param amount: Amount of source currency to convert.
        :param limit_rate: Rate for limit orders (required if limit).
        """
        body: dict[str, Any] = {
            "trade_type": trade_type,
            "order_type": order_type,
            "amount": amount,
        }
        if limit_rate is not None:
            body["limit_rate"] = limit_rate
        return self.post("/currency/orders", json_body=body)

    def cancel_order(self, order_id: int) -> dict[str, Any]:
        """
        ``DELETE /currency/orders/{id}`` — cancel an open limit order.
        """
        return self.delete(f"/currency/orders/{order_id}")
