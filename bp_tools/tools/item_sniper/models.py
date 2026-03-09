from dataclasses import dataclass, field
from typing import Any

from bp_tools.core.contracts import BotConfigBase


@dataclass(frozen=True, slots=True)
class UserSniperConfig:
    """Per-user caps. All fields optional — None means no cap."""

    username: str
    max_credits: int | None = None
    max_bits: int | None = None
    rares_only: bool = True


@dataclass(frozen=True, slots=True)
class ItemSniperConfig(BotConfigBase):
    """
    Tool config for item_sniper.

    YAML (under tools[].config)::

        users:
          - username: "Revolt"
            max-credits: 1000
            max-bits: 50000
          - username: "RevoIt"       # no caps = buy anything affordable
        credit-to-bits-ratio: 50
        rares-only: false            # true = only buy rare/limited items
    """

    users: list[UserSniperConfig] = field(default_factory=list)
    credit_to_bits_ratio: int = 50

    def caps_for(self, username: str) -> UserSniperConfig:
        """Look up per-user caps."""
        for u in self.users:
            if u.username == username:
                return u
        # Shouldn't happen — but return no-cap defaults
        return UserSniperConfig(username=username)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ItemSniperConfig":
        from bp_tools.core.config_utils import parse_config

        # Backwards compat: plain "usernames" list (no per-user caps)
        users_raw = raw.get("users")
        if users_raw is None:
            usernames = raw.get("usernames", [])
            if not isinstance(usernames, list):
                raise TypeError("item_sniper.config.users or usernames required.")
            users_raw = [{"username": u} for u in usernames]

        if not isinstance(users_raw, list):
            raise TypeError("item_sniper.config.users must be a list.")

        # Support both string shorthand and full dict entries
        users: list[UserSniperConfig] = []
        for entry in users_raw:
            if isinstance(entry, str):
                users.append(UserSniperConfig(username=entry))
            elif isinstance(entry, dict):
                users.append(parse_config(UserSniperConfig, entry))
            else:
                raise TypeError("each users entry must be a mapping or string.")

        if not users:
            raise ValueError("item_sniper: at least one user required.")

        # Parse remaining fields (sans users)
        clean = {k: v for k, v in raw.items() if k not in ("users", "usernames")}
        clean["users"] = []  # placeholder to satisfy required field
        clean["usernames"] = [u.username for u in users]
        base = parse_config(cls, clean)

        # Replace with real users list
        return cls(
            users=users,
            usernames=[u.username for u in users],
            credit_to_bits_ratio=base.credit_to_bits_ratio,
        )


@dataclass(frozen=True, slots=True)
class ShopItem:
    """
    Item from the ``GET /api/v1/items`` endpoint.
    """

    item_id: int
    name: str
    slug: str
    item_type: int
    image: str
    credits: int
    bits: int
    rare: bool
    on_sale: bool
    stock: int
    remaining_stock: int
    creator_id: int
    created_at: str

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "ShopItem":
        """
        Parse ShopItem from v1 API payload.

        :param data: Item dict from ``GET /api/v1/items``.
        :returns: ShopItem.
        """
        try:
            creator = data.get("creator", {})
            creator_id = int(creator.get("id", 0)) if isinstance(creator, dict) else 0

            return cls(
                item_id=int(data["id"]),
                name=str(data.get("name", "")),
                slug=str(data.get("slug", "")),
                item_type=(
                    int(data.get("type", 0))
                    if str(data.get("type", 0)).isdigit()
                    else 0
                ),
                image=str(data.get("image", "")),
                credits=int(data.get("credits") or 0),
                bits=int(data.get("bits") or 0),
                rare=bool(data.get("rare", False)),
                on_sale=bool(data.get("on_sale", False)),
                stock=int(data.get("stock") or 0),
                remaining_stock=int(data.get("remaining_stock") or 0),
                creator_id=creator_id,
                created_at=str(data.get("created_at", "")),
            )
        except KeyError as exc:
            raise KeyError(f"Missing expected key in item payload: {exc}") from exc

    def best_currency(self, ratio: int) -> tuple[str, int]:
        """
        Pick the cheapest currency.

        Compares ``credits`` vs ``bits / ratio`` and returns the winner.

        :param ratio: How many bits equal 1 credit.
        :returns: ``("credits", price)`` or ``("bits", price)``.
        """
        has_credits = self.credits > 0
        has_bits = self.bits > 0

        if has_credits and has_bits:
            bits_in_credits = self.bits / ratio
            if bits_in_credits < self.credits:
                return ("bits", self.bits)
            return ("credits", self.credits)

        if has_bits:
            return ("bits", self.bits)
        return ("credits", self.credits)

    def __str__(self) -> str:
        base = f"(ID: {self.item_id}) {self.name}"
        if self.credits > 0:
            return f"{base} — {self.credits:,} Credits"
        if self.bits > 0:
            return f"{base} — {self.bits:,} Bits"
        return f"{base} — Free"
