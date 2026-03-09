from dataclasses import dataclass, field
from typing import Any

from bp_tools.core.contracts import BotConfigBase


@dataclass(frozen=True, slots=True)
class OffererConfig(BotConfigBase):
    """
    Tool config for rare_offerer.

    YAML (under tools[].config)::

        username: "Revolt"
        offer-percentage: 5  # offer 5% of RAP value on each rare item
        min-offer: 2         # minimum offer amount (used when no RAP data)
        skip-items:          # item IDs to skip entirely
          - 26782
          - 26781
    """

    username: str
    offer_percentage: int = 5
    min_offer: int = 2
    skip_items: set[int] = field(default_factory=set)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "OffererConfig":
        username = raw.get("username")
        if not isinstance(username, str):
            raise TypeError("rare_offerer.config.username must be a string.")

        offer_percentage = raw.get("offer-percentage", 5)
        if not isinstance(offer_percentage, int):
            raise TypeError("rare_offerer.config.offer-percentage must be an int.")

        min_offer = raw.get("min-offer", 2)
        if not isinstance(min_offer, int):
            raise TypeError("rare_offerer.config.min-offer must be an int.")

        skip_items: set[int] = set()
        for item_id in raw.get("skip-items") or []:
            if not isinstance(item_id, int):
                raise TypeError("rare_offerer.config.skip-items entries must be ints.")
            skip_items.add(item_id)

        return cls(
            username=username,
            offer_percentage=offer_percentage,
            min_offer=min_offer,
            skip_items=skip_items,
        )
