"""Browser-style session for BrickPlanet web purchases.

Reimplements the pre-v1.0.0 ``aqua_sniper`` technique: log in via the
web form to obtain session cookies + CSRF token, then buy items through
the standard ``POST /shop/{id}/buy-item`` form endpoint instead of the
API ``POST /items/{id}/buy``.
"""

import re
import time
from typing import Any, Optional

from requests import Response, Session

from bp_tools.core.utils import log_print as print

# BrickPlanet web base (not the API base)
_WEB_BASE = "https://www.brickplanet.com"

# Maximum session lifetime before forced re-login (24 hours in seconds)
SESSION_LIFETIME_SECONDS = 86400

# Regex to extract the CSRF _token from an HTML page's hidden input
_TOKEN_RE = re.compile(
    r'<input[^>]+name=["\']_token["\'][^>]+value=["\']([^"\']+)["\']',
    re.IGNORECASE,
)


class WebSessionError(RuntimeError):
    """Session could not be used (login failed, or still in backoff)."""


class WebRateLimited(WebSessionError):
    """The site answered 429; requests are paused until ``retry_at``."""


class WebSession:
    """
    Authenticated browser session for BrickPlanet.

    Logs in with username/password, maintains session cookies
    (``brickplanet_session``, ``XSRF-TOKEN``), and exposes a
    :meth:`buy_item` method that submits the purchase form.
    Automatically kills and re-establishes session every 24 hours.
    Failed logins and 429 responses back off exponentially instead of
    retrying on every cycle.
    """

    # Failed re-login backoff: 30s, 60s, 120s ... capped at 10 minutes
    _BACKOFF_BASE_SECONDS = 30.0
    _BACKOFF_MAX_SECONDS = 600.0
    # Used when a 429 has no usable Retry-After header
    _DEFAULT_RETRY_AFTER_SECONDS = 60.0

    def __init__(
        self,
        username: str,
        password: str,
        two_factor_code: str | None = None,
    ) -> None:
        self.username = username
        self._password = password
        self._two_factor_code = two_factor_code
        self._session: Session = Session()
        self._token: str = ""
        self._created_at: float = 0.0
        self._retry_at: float = 0.0
        self._failures: int = 0

        self._login()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _extract_token(self, response: Response) -> None:
        """Extract the CSRF ``_token`` from an HTML response body."""
        match = _TOKEN_RE.search(response.text)
        if match:
            self._token = match.group(1)

    def _send(self, method: str, url: str, **kwargs: Any) -> Response:
        """
        Send a request on the session, honouring 429 responses.

        On 429 the session is paused until ``Retry-After`` has elapsed and
        :class:`WebRateLimited` is raised.
        """
        response = self._session.request(method, url, **kwargs)
        if response.status_code == 429:
            try:
                retry_after = float(response.headers.get("Retry-After", ""))
            except ValueError:
                retry_after = self._DEFAULT_RETRY_AFTER_SECONDS
            self._retry_at = max(self._retry_at, time.time() + retry_after)
            raise WebRateLimited(
                f"[{self.username}] Rate limited by site (429), "
                f"pausing {retry_after:.0f}s."
            )
        response.raise_for_status()
        return response

    def _login(self) -> None:
        """
        Authenticate via the web login form.

        1. GET /login — seeds cookies and grabs the initial CSRF token.
        2. POST /login — submits credentials with the CSRF token.
        """
        self._session.close()
        self._session = Session()
        self._token = ""

        # Step 1: GET the login page to seed cookies + grab _token
        login_page = self._send("GET", f"{_WEB_BASE}/login")
        self._extract_token(login_page)

        if not self._token:
            raise ConnectionError(
                f"[{self.username}] Could not extract CSRF token from login page."
            )

        # Step 2: POST credentials
        response = self._send(
            "POST",
            f"{_WEB_BASE}/login",
            data={
                "_token": self._token,
                "username": self.username,
                "password": self._password,
            },
            allow_redirects=True,
        )

        # Accounts with email 2FA are redirected to a code-entry page
        if "/email-2fa" in response.url:
            response = self._submit_email_2fa(response)

        # Refresh the token from the redirected page
        self._extract_token(response)

        # Verify login succeeded - the page title should be "Home | BrickPlanet"
        if "Home | BrickPlanet" not in response.text:
            raise ConnectionRefusedError(
                f"[{self.username}] Web login failed — check username/password."
            )

        self._created_at = time.time()
        self._failures = 0
        self._retry_at = 0.0

    def _submit_email_2fa(self, page: Response) -> Response:
        """
        Submit the emailed 6-digit code on the 2FA page.

        Codes are single-use and expire, so a stored code only works for
        the login it was issued for. Without one, login fails with a clear
        message instead of a generic "check password" error.
        """
        if not self._two_factor_code:
            raise WebSessionError(
                f"[{self.username}] Account requires email 2FA. Add a "
                "'two-factor-code' to its api_tokens entry, or disable 2FA "
                "on the account."
            )
        self._extract_token(page)
        action = re.search(r'<form[^>]*action="([^"]*email-2fa[^"]*)"', page.text)
        url = action.group(1) if action else f"{_WEB_BASE}/account/email-2fa/verify"
        return self._send(
            "POST",
            url,
            data={
                "_token": self._token,
                "code": self._two_factor_code,
                "trust_device": "1",
            },
            allow_redirects=True,
        )

    def _is_stale(self) -> bool:
        return time.time() - self._created_at >= SESSION_LIFETIME_SECONDS

    def ensure_fresh_session(self) -> None:
        """
        Re-login if the session is older than 24 hours.

        While in backoff this returns without trying; :meth:`buy_item`
        refuses to submit on a stale session.
        """
        if not self._is_stale() or time.time() < self._retry_at:
            return

        print(
            f"[WebSession] [{self.username}] Session reached 24h limit — "
            "re-logging in..."
        )
        try:
            self._login()
        except Exception:
            self._failures += 1
            delay = min(
                self._BACKOFF_BASE_SECONDS * 2 ** (self._failures - 1),
                self._BACKOFF_MAX_SECONDS,
            )
            self._retry_at = max(self._retry_at, time.time() + delay)
            raise

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def buy_item(
        self,
        item_id: int,
        currency: str = "credits",
    ) -> dict:
        """
        Purchase an item via the web form endpoint.

        ``POST /shop/{item_id}/buy-item`` with the CSRF token and
        currency parameter, mimicking a browser form submission.

        :param item_id: The shop item ID to purchase.
        :param currency: ``"credits"`` or ``"bits"``.
        :returns: Dict with ``success`` bool and ``message`` str.
        :raises WebSessionError: If the session is stale and cannot be renewed yet.
        :raises WebRateLimited: If the site returned 429.
        """
        if time.time() < self._retry_at:
            raise WebSessionError(
                f"[{self.username}] Web session paused until backoff ends."
            )
        if self._is_stale():
            self.ensure_fresh_session()
            if self._is_stale():
                raise WebSessionError(
                    f"[{self.username}] Session expired and re-login is pending."
                )

        # Map currency name to the numeric type the form expects
        currency_type = 1 if currency == "credits" else 2

        # Refresh the CSRF token by visiting the item page first
        item_page = self._send("GET", f"{_WEB_BASE}/shop/{item_id}")
        self._extract_token(item_page)

        response = self._send(
            "POST",
            f"{_WEB_BASE}/shop/{item_id}/buy-item",
            data={
                "_token": self._token,
                "currency": currency_type,
                "quantity": 1,
            },
            allow_redirects=True,
        )

        # Refresh CSRF token for next request
        self._extract_token(response)

        # Check for success indicators in the response
        text = response.text
        if "You own this" in text:
            return {
                "success": False,
                "already_owned": True,
                "message": "Already owned",
            }
        if "successfully" in text.lower():
            return {
                "success": True,
                "message": "Purchase successful (web)",
            }

        # Try to extract an error message
        error_match = re.search(
            r'<div[^>]*class="[^"]*alert[^"]*"[^>]*>(.*?)</div>',
            text,
            re.DOTALL,
        )
        error_msg = error_match.group(1).strip() if error_match else "Unknown error"

        return {
            "success": False,
            "message": f"Purchase may have failed: {error_msg}",
        }

    def refresh_session(self, password: Optional[str] = None) -> None:
        """
        Re-login to refresh an expired session.

        :param password: Optional password if updating.
        """
        if password is not None:
            self._password = password
        self._login()
