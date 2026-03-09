"""
Entitlements: fetch bot and framework restrictions from a remote JSON.

JSON format::

    {
      "version": "1.0.0",
      "group_id": 2213,
      "sniper_delay": 5.0,
      "bots": [
        {"uuid": "...", "min_role_num": 4, "premium_role_num": 60, "version": "1.0.0"}
      ]
    }

Fails open — if the JSON can't be fetched, all bots are unrestricted.
"""

from dataclasses import dataclass, field

import requests

from bp_tools.core.api import ApiClient
from bp_tools.core.constants import ENTITLEMENTS_URL


@dataclass
class Entitlements:
    """Parsed entitlements payload."""

    group_id: int = 0
    framework_version: str | None = None
    # uuid -> min_role_num
    requirements: dict[str, int] = field(default_factory=dict)
    # uuid -> premium_role_num
    premium_roles: dict[str, int] = field(default_factory=dict)
    # uuid -> sniper_delay
    sniper_delays: dict[str, float] = field(default_factory=dict)
    # uuid -> latest version (semver string)
    versions: dict[str, str] = field(default_factory=dict)

    def min_role_for(self, uuid: str) -> int | None:
        """Return the minimum role_num required, or None if unrestricted."""
        return self.requirements.get(uuid)

    def premium_role_for(self, uuid: str) -> int | None:
        """Return the premium role_num threshold, or None if not set."""
        return self.premium_roles.get(uuid)

    def sniper_delay_for(self, uuid: str) -> float:
        """Return the sniper delay for a bot, defaulting to 5.0."""
        return self.sniper_delays.get(uuid, 5.0)

    def version_for(self, uuid: str) -> str | None:
        """Return the latest version for a bot, or None if not specified."""
        return self.versions.get(uuid)


def fetch_entitlements(url: str = ENTITLEMENTS_URL) -> Entitlements:
    """
    Fetch and parse the entitlements JSON.
    Returns an empty Entitlements (everything unrestricted) on any failure.
    """
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return Entitlements()

    group_id = data.get("group_id", 0)
    fw_ver = data.get("version")
    reqs: dict[str, int] = {}
    premium: dict[str, int] = {}
    delays: dict[str, float] = {}
    vers: dict[str, str] = {}
    for bot in data.get("bots", []):
        uuid = bot.get("uuid")
        if not isinstance(uuid, str):
            continue
        min_role = bot.get("min_role_num")
        if isinstance(min_role, int):
            reqs[uuid] = min_role
        prem_role = bot.get("premium_role_num")
        if isinstance(prem_role, int):
            premium[uuid] = prem_role
        delay_raw = bot.get("sniper_delay")
        if delay_raw is not None:
            delays[uuid] = float(delay_raw)
        version = bot.get("version")
        if isinstance(version, str):
            vers[uuid] = version

    return Entitlements(
        group_id=group_id,
        framework_version=fw_ver if isinstance(fw_ver, str) else None,
        requirements=reqs,
        premium_roles=premium,
        sniper_delays=delays,
        versions=vers,
    )


def resolve_user_role(client: ApiClient, group_id: int) -> int:
    """
    Check a user's role_num in a group via the BrickPlanet API.
    Returns 0 if not a member or on error.
    """
    try:
        result = client.get_group_membership(group_id)
        data = result.get("data", {})
        if not data.get("is_member"):
            return 0
        role = data.get("role", {})
        return role.get("role_num", 0) if role else 0
    except Exception:
        return 0
