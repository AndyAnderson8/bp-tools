from dataclasses import dataclass

from bp_tools.core.contracts import BotConfigBase


@dataclass(frozen=True, slots=True)
class OffererConfig(BotConfigBase):
    """
    Tool config for rare_offerer.

    YAML (under tools[].config)::

        username: "Revolt"
        base-offer: 2
    """

    base_offer: int = 2
