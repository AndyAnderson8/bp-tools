from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from bp_tools.core.contracts import BotConfigBase


class TradeSide(Enum):
    """Which side of the spread we're operating on."""

    BID = "bid"  # bits → credits (buying credits with bits)
    ASK = "ask"  # credits → bits (selling credits for bits)

    @property
    def trade_type(self) -> str:
        return "bits-to-credits" if self is TradeSide.BID else "credits-to-bits"

    @property
    def label(self) -> str:
        """Currency being offered."""
        return "bits" if self is TradeSide.BID else "credits"

    @property
    def equiv_label(self) -> str:
        """Currency received."""
        return "credits" if self is TradeSide.BID else "bits"

    @property
    def wallet_key(self) -> str:
        """Key in the wallet dict."""
        return "bits" if self is TradeSide.BID else "credits"

    @property
    def spot_label(self) -> str:
        """Human-readable direction for log messages."""
        return "bits-to-credit" if self is TradeSide.BID else "credit-to-bits"

    @property
    def tick_sign(self) -> int:
        """Direction tick is applied: +1 for bids (higher is better), -1 for asks (lower is better)."""
        return 1 if self is TradeSide.BID else -1

    def clamp_rate(self, rate: float, limit: float) -> float:
        """Apply ceiling (BID) or floor (ASK) to the computed rate."""
        return min(rate, limit) if self is TradeSide.BID else max(rate, limit)

    def is_overtaken(self, best: float, our_rate: float) -> bool:
        """Has someone posted a better rate than ours?"""
        return best > our_rate if self is TradeSide.BID else best < our_rate

    def rate_in_limit(self, rate: float, limit: float) -> bool:
        """Is the rate within the configured limit?"""
        return rate <= limit if self is TradeSide.BID else rate >= limit

    def equivalent(self, amount: int, rate: float) -> int:
        """Convert amount at rate to the other currency."""
        return int(amount / rate) if self is TradeSide.BID else int(amount * rate)


@dataclass
class SideState:
    """Runtime state for one side of the spread."""

    order_id: int | None = None
    rate: float | None = None
    amount: int | None = None


@dataclass(frozen=True, slots=True)
class ExchangeSideConfig:
    """Config for one side of the spread."""

    amount: int
    max_rate: float


@dataclass(frozen=True, slots=True)
class CurrencyExchangeConfig(BotConfigBase):
    """
    Tool config for currency_exchange.

    Rate = bits per credit (1 credit = X bits).

    YAML (under tools[].config)::

        username: "Revolt"
        offer-bits:               # sell bits, receive credits
          amount: 500             # bits to offer
          max-rate: 40.00         # ceiling: won't pay more than 40 bits/credit
        offer-credits:            # sell credits, receive bits
          amount: 50              # credits to offer
          max-rate: 70.00         # floor: won't accept less than 70 bits/credit
    """

    username: str
    offer_bits: ExchangeSideConfig | None = None
    offer_credits: ExchangeSideConfig | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "CurrencyExchangeConfig":
        from bp_tools.core.config_utils import parse_config

        config = parse_config(cls, raw)

        if config.offer_bits is None and config.offer_credits is None:
            raise ValueError(
                "currency_exchange: must configure at least one of 'offer-bits' or 'offer-credits'."
            )

        if (
            config.offer_bits is not None
            and config.offer_credits is not None
            and config.offer_bits.max_rate >= config.offer_credits.max_rate
        ):
            raise ValueError(
                f"currency_exchange: offer-bits max-rate ({config.offer_bits.max_rate}) must be "
                f"less than offer-credits max-rate ({config.offer_credits.max_rate}). "
                f"Otherwise you'd pay more bits/credit to buy credits than you "
                f"receive when selling them."
            )

        return config
