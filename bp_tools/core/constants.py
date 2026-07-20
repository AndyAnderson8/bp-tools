"""
Application-level constants.

Values here are baked into the compiled distribution and should not be user-configured.
"""

# ── Framework ────────────────────────────────────────────────────
FRAMEWORK_VERSION = "1.1.0"

# ── BrickPlanet API ──────────────────────────────────────────────
BASE_URL = "https://www.brickplanet.com/api/v1"

# ── API Rate Limits ──────────────────────────────────────────────
# Per the docs: tracked per authenticated user (not per IP).
# See: https://docs.brickplanet.com/#rate-limits
RATE_LIMITS: dict = {
    "tiers": {
        "default": {"limit": 60, "window": 60},
        "write": {"limit": 30, "window": 60},
        "trading": {"limit": 10, "window": 60},
    },
    "routes": {
        "POST /items/*/buy": "trading",
        "POST /items/*/offers": "trading",
        "POST /currency/orders": "trading",
        "DELETE /currency/orders": "trading",
        "POST /trades": "trading",
        "POST /trades/*/accept": "trading",
        "POST /trades/*/decline": "trading",
        "POST /trades/*/cancel": "trading",
        "POST /friends": "trading",
        "GET /search": "write",
        "GET /users/search": "write",
        "POST /items/*/resell": "write",
        "DELETE /items/*/resell": "write",
        "DELETE /offers": "write",
        "DELETE /friends": "write",
        "POST /friends/requests/*/accept": "write",
        "POST /friends/requests/*/decline": "write",
    },
}
