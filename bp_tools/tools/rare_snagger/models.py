from dataclasses import dataclass, field
from typing import Any

from bp_tools.core.config_utils import parse_config
from bp_tools.core.contracts import BotConfigBase


@dataclass(frozen=True, slots=True)
class PendingBuy:
    """A resale listing the snagger intends to purchase."""

    item_id: int
    item_name: str
    reseller_id: int
    price: int
    seller: str


@dataclass(frozen=True, slots=True)
class ItemOverride:
    """Per-item price override."""

    item_id: int
    max_credits: int  # 0 = skip this item entirely


@dataclass(frozen=True, slots=True)
class SnaggerConfig(BotConfigBase):
    """
    Tool config for snagger.

    YAML (under tools[].config)::

        username: "Revolt"
        max-credits: 500          # default max price for any rare resale
        rap-percentage: 50        # buy if price <= 50% of avg sale price
        overrides:                # per-item overrides (optional)
          - item-id: 42
            max-credits: 1000     # pay up to 1000 for this item
          - item-id: 99
            max-credits: 0        # skip this item entirely
    """

    max_credits: int = 500
    rap_percentage: int = (
        0  # 0 = disabled; e.g. 50 = buy if price <= 50% of avg sale price
    )
    overrides: dict[int, int] = field(default_factory=dict)  # item_id → max_credits

    def max_for(self, item_id: int) -> int:
        """Return the max credits willing to pay for this item."""
        return self.overrides.get(item_id, self.max_credits)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "SnaggerConfig":
        # Parse overrides list[{item-id, max-credits}] → dict[int, int]
        overrides: dict[int, int] = {}
        for entry in raw.get("overrides") or []:
            if not isinstance(entry, dict):
                raise TypeError("snagger.config.overrides entries must be mappings.")
            item_id = entry.get("item-id")
            max_credits_override = entry.get("max-credits")
            if not isinstance(item_id, int) or not isinstance(
                max_credits_override, int
            ):
                raise TypeError("overrides require int item-id and int max-credits.")
            overrides[item_id] = max_credits_override

        # Strip overrides from raw so parse_config doesn't choke on it
        clean = {k: v for k, v in raw.items() if k != "overrides"}
        # Normalize singular username → usernames list
        if "username" in clean and "usernames" not in clean:
            clean["usernames"] = [clean.pop("username")]

        config = parse_config(cls, {**clean, "overrides": overrides})
        return config
