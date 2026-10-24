"""Thin wrapper around requests.Session for the BrickPlanet v1 API."""

import fnmatch
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Optional

from requests import Response, Session

from bp_tools.core.constants import BASE_URL, RATE_LIMITS
from bp_tools.core.utils import log_print as print
from bp_tools.core.utils import sleep_with_status

# Fallback when the server omits Retry-After. Repeated 429s back off up to five
# minutes; valid Retry-After values are followed as sent by the API.
RATE_LIMIT_COOLDOWN_SECONDS = 60.0
RATE_LIMIT_MAX_COOLDOWN_SECONDS = 300.0


@dataclass
class _AccountRateLimitState:
    """Rate-limit pause shared by clients using the same API token."""

    paused_until: float = 0.0
    consecutive_429s: int = 0


class ApiError(RuntimeError):
    """Non-2xx response from the API."""

    def __init__(
        self,
        status_code: int,
        path: str,
        detail: object,
        *,
        account: str | None = None,
        retry_after: float | None = None,
        is_backoff: bool = False,
    ) -> None:
        account_label = f" [{account}]" if account else ""
        super().__init__(f"{status_code} {path}{account_label}: {detail}")
        self.status_code = status_code
        self.account = account
        self.retry_after = retry_after
        self.is_backoff = is_backoff


class RateLimiter:
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
                sleep_with_status(
                    "_rate_limit",
                    f"Rate limit ({self._limit}/{self._window}s)"
                    f" — sleeping {sleep_for:.1f}s",
                    sleep_for,
                )
        self._timestamps.append(time.monotonic())


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
        username: str | None = None,
        account_rate_limit_state: _AccountRateLimitState | None = None,
    ) -> None:
        """
        :param token: BrickPlanet API token (Bearer).
        :param rate_limits: Parsed rate-limits dict (from ``load_rate_limits``).
        :param dry_run: If True, mutating requests (POST/DELETE) are printed instead of sent.
        :param username: Account name for useful rate-limit diagnostics.
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
        self.username = username
        self._account_rate_limit_state = (
            account_rate_limit_state or _AccountRateLimitState()
        )

        # Rate limiting
        rl = rate_limits or RATE_LIMITS
        tiers_raw = rl.get("tiers", {})
        self._limiters: dict[str, RateLimiter] = {}
        for tier_name, tier_cfg in tiers_raw.items():
            self._limiters[tier_name] = RateLimiter(
                limit=int(tier_cfg.get("limit", 60)),
                window=int(tier_cfg.get("window", 60)),
            )

        self._routes: dict[str, str] = rl.get("routes", {})

    @property
    def _paused_until(self) -> float:
        """Compatibility accessor for the shared account cooldown deadline."""
        return self._account_rate_limit_state.paused_until

    @_paused_until.setter
    def _paused_until(self, value: float) -> None:
        self._account_rate_limit_state.paused_until = value

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

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict[str, Any]] = None,
        json_body: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """
        Send a rate-limited request and return the parsed JSON body.

        A 429 pauses requests for this account until Retry-After expires.
        Repeated 429s without that header use exponential backoff. Requests
        are never retried automatically.
        Any other non-2xx response raises :class:`ApiError`.
        """
        self._raise_if_paused(path)
        url = f"{BASE_URL}{path}"
        self._rate_limit(method, path)
        response = self._session.request(method, url, params=params, json=json_body)
        if response.status_code == 429:
            cooldown = self._pause(response)
            headers = response.headers
            limit = headers.get("X-RateLimit-Limit")
            remaining = headers.get("X-RateLimit-Remaining")
            detail = f"rate limited; backing off {cooldown:.0f}s"
            if limit is not None or remaining is not None:
                detail += f" (limit={limit or '?'} remaining={remaining or '?'})"
            raise ApiError(
                429,
                path,
                detail,
                account=self.username,
                retry_after=cooldown,
            )
        if not response.ok:
            try:
                detail = response.json()
            except Exception:
                detail = response.text
            raise ApiError(response.status_code, path, detail, account=self.username)
        self._account_rate_limit_state.consecutive_429s = 0
        return response.json()

    def _paused_for(self) -> float:
        return max(0.0, self._paused_until - time.monotonic())

    def _pause(self, response: Response) -> float:
        """Start an account-wide cooldown and return its duration in seconds."""
        try:
            retry_after = float(response.headers.get("Retry-After", ""))
        except ValueError:
            retry_after = 0.0
        if retry_after > 0:
            cooldown = retry_after
        else:
            state = self._account_rate_limit_state
            state.consecutive_429s += 1
            cooldown = min(
                RATE_LIMIT_COOLDOWN_SECONDS * 2 ** (state.consecutive_429s - 1),
                RATE_LIMIT_MAX_COOLDOWN_SECONDS,
            )
        self._paused_until = max(self._paused_until, time.monotonic() + cooldown)
        return cooldown

    def _raise_if_paused(self, path: str) -> None:
        """Fail fast, without a network call, while a cooldown is active."""
        remaining = self._paused_for()
        if remaining > 0:
            raise ApiError(
                429,
                path,
                f"[backoff] request suppressed for {remaining:.0f}s",
                account=self.username,
                retry_after=remaining,
                is_backoff=True,
            )

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
        return self._request("GET", path, params=params)

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
        return self._request("POST", path, json_body=json_body)

    def delete(self, path: str) -> dict[str, Any]:
        """
        DELETE request to the API.

        :param path: Path relative to base URL.
        :returns: Parsed JSON response.
        """
        if self.dry_run:
            print(f"  [DRY RUN] DELETE {path}")
            return {"data": {"message": "dry-run"}}
        return self._request("DELETE", path)

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
