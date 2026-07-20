"""Browser-style session for BrickPlanet web purchases.

Reimplements the pre-v1.0.0 ``aqua_sniper`` technique: log in via the
web form to obtain session cookies + CSRF token, then buy items through
the standard ``POST /shop/{id}/buy-item`` form endpoint instead of the
API ``POST /items/{id}/buy``.
"""

import re
from typing import Optional

from requests import Response, Session

from bp_tools.core.utils import log_print as print

# BrickPlanet web base (not the API base)
_WEB_BASE = "https://www.brickplanet.com"

# Regex to extract the CSRF _token from an HTML page's hidden input
_TOKEN_RE = re.compile(
    r'<input[^>]+name=["\']_token["\'][^>]+value=["\']([^"\']+)["\']',
    re.IGNORECASE,
)


class WebSession:
    """
    Authenticated browser session for BrickPlanet.

    Logs in with username/password, maintains session cookies
    (``brickplanet_session``, ``XSRF-TOKEN``), and exposes a
    :meth:`buy_item` method that submits the purchase form.
    """

    def __init__(self, username: str, password: str) -> None:
        self.username = username
        self._session = Session()
        self._token: str = ""

        self._login(username, password)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _extract_token(self, response: Response) -> None:
        """Extract the CSRF ``_token`` from an HTML response body."""
        match = _TOKEN_RE.search(response.text)
        if match:
            self._token = match.group(1)

    def _login(self, username: str, password: str) -> None:
        """
        Authenticate via the web login form.

        1. GET /login — seeds cookies and grabs the initial CSRF token.
        2. POST /login — submits credentials with the CSRF token.
        """
        # Step 1: GET the login page to seed cookies + grab _token
        login_page = self._session.get(f"{_WEB_BASE}/login")
        login_page.raise_for_status()
        self._extract_token(login_page)

        if not self._token:
            raise ConnectionError(
                f"[{username}] Could not extract CSRF token from login page."
            )

        # Step 2: POST credentials
        response = self._session.post(
            f"{_WEB_BASE}/login",
            data={
                "_token": self._token,
                "username": username,
                "password": password,
            },
            allow_redirects=True,
        )
        response.raise_for_status()

        # Refresh the token from the redirected page
        self._extract_token(response)

        # Verify login succeeded — the page title should be "Home | BrickPlanet"
        if "Home | BrickPlanet" not in response.text:
            raise ConnectionRefusedError(
                f"[{username}] Web login failed — check username/password."
            )

        print(f"[WebSession] Logged in as {username}")

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
        """
        # Map currency name to the numeric type the form expects
        currency_type = 1 if currency == "credits" else 2

        # Refresh the CSRF token by visiting the item page first
        item_page = self._session.get(f"{_WEB_BASE}/shop/{item_id}")
        item_page.raise_for_status()
        self._extract_token(item_page)

        response = self._session.post(
            f"{_WEB_BASE}/shop/{item_id}/buy-item",
            data={
                "_token": self._token,
                "currency": currency_type,
                "quantity": 1,
            },
            allow_redirects=True,
        )
        response.raise_for_status()

        # Refresh CSRF token for next request
        self._extract_token(response)

        # Check for success indicators in the response
        text = response.text
        if "You own this" in text or "successfully" in text.lower():
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

        :param password: Password to re-login with. Required.
        """
        if password is None:
            raise ValueError("Password required to refresh web session.")
        self._session = Session()
        self._token = ""
        self._login(self.username, password)
