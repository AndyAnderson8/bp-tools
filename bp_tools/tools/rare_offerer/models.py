from dataclasses import dataclass, field

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
