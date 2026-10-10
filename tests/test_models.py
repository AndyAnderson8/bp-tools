"""Tool config models and item model: parsing, validation and derived values."""

from typing import Any

import pytest

from bp_tools.tools.item_sniper.models import (
    ItemSniperConfig,
    ShopItem,
    UserSniperConfig,
)
from bp_tools.tools.rare_snagger.models import SnaggerConfig
from bp_tools.tools.trade_currency.models import CurrencyExchangeConfig, TradeSide


def _item(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": 7,
        "name": "Thing",
        "slug": "thing",
        "type": 1,
        "image": "",
        "credits": 100,
        "bits": 0,
        "rare": True,
        "on_sale": True,
        "stock": 10,
        "remaining_stock": 5,
        "creator": {"id": 1},
        "created_at": "2026-01-01",
    }
    payload.update(overrides)
    return payload


# ---- ShopItem --------------------------------------------------------


def test_shop_item_parses_api_payload() -> None:
    item = ShopItem.from_api(_item())

    assert item.item_id == 7
    assert item.creator_id == 1
    assert item.remaining_stock == 5


def test_shop_item_missing_id_raises() -> None:
    payload = _item()
    del payload["id"]

    with pytest.raises(KeyError):
        ShopItem.from_api(payload)


def test_best_currency_prefers_cheaper_side_after_ratio() -> None:
    item = ShopItem.from_api(_item(credits=100, bits=1000))

    # At 50 bits/credit, 1000 bits = 20 credits -> bits are cheaper
    assert item.best_currency(ratio=50) == ("bits", 1000)
    # At 5 bits/credit, 1000 bits = 200 credits -> credits are cheaper
    assert item.best_currency(ratio=5) == ("credits", 100)


def test_best_currency_single_currency() -> None:
    assert ShopItem.from_api(_item(credits=0, bits=40)).best_currency(50) == (
        "bits",
        40,
    )
    assert ShopItem.from_api(_item(credits=30, bits=0)).best_currency(50) == (
        "credits",
        30,
    )


def test_shop_item_str_shows_price() -> None:
    assert "100 Credits" in str(ShopItem.from_api(_item(credits=100)))
    assert "Free" in str(ShopItem.from_api(_item(credits=0, bits=0)))


# ---- Item sniper config -----------------------------------------------


def test_sniper_accepts_string_and_dict_users() -> None:
    cfg = ItemSniperConfig.from_dict(
        {"users": ["A", {"username": "B", "rares-only": False, "max-credits": 5}]}
    )

    assert [u.username for u in cfg.users] == ["A", "B"]
    assert cfg.users[1].rares_only is False
    assert cfg.users[1].max_credits == 5
    assert cfg.users[0].rares_only is True  # default


def test_sniper_requires_a_user() -> None:
    with pytest.raises(ValueError, match="at least one user"):
        ItemSniperConfig.from_dict({"users": []})


def test_sniper_legacy_usernames_list_is_accepted() -> None:
    cfg = ItemSniperConfig.from_dict({"usernames": ["A", "B"]})

    assert [u.username for u in cfg.users] == ["A", "B"]


def test_caps_for_unknown_user_returns_no_caps() -> None:
    cfg = ItemSniperConfig.from_dict({"users": ["A"]})

    assert cfg.caps_for("Nobody") == UserSniperConfig(username="Nobody")


def test_credit_to_bits_ratio_is_read() -> None:
    cfg = ItemSniperConfig.from_dict({"users": ["A"], "credit-to-bits-ratio": 40})

    assert cfg.credit_to_bits_ratio == 40


# ---- Snagger config ----------------------------------------------------


def test_snagger_overrides_become_mapping() -> None:
    cfg = SnaggerConfig.from_dict(
        {
            "username": "Revolt",
            "max-credits": 3,
            "overrides": [
                {"item-id": 1, "max-credits": 20},
                {"item-id": 2, "max-credits": 0},
            ],
        }
    )

    assert cfg.usernames == ["Revolt"]
    assert cfg.max_for(1) == 20
    assert cfg.max_for(2) == 0  # 0 = skip
    assert cfg.max_for(999) == 3  # default


def test_snagger_rejects_malformed_override() -> None:
    with pytest.raises(TypeError):
        SnaggerConfig.from_dict({"overrides": [{"item-id": "x", "max-credits": 1}]})


# ---- Trade currency config --------------------------------------------


def _trade(**sides: Any) -> dict[str, Any]:
    return {"username": "Revolt", **sides}


def test_trade_requires_at_least_one_side() -> None:
    with pytest.raises(ValueError, match="at least one"):
        CurrencyExchangeConfig.from_dict(_trade())


def test_trade_rejects_crossed_limits() -> None:
    raw = _trade(
        **{
            "offer-bits": {"amount": 1, "max-rate": 80},
            "offer-credits": {"amount": 1, "max-rate": 70},
        }
    )

    with pytest.raises(ValueError, match="must be less than"):
        CurrencyExchangeConfig.from_dict(raw)


def test_trade_accepts_single_side() -> None:
    cfg = CurrencyExchangeConfig.from_dict(
        _trade(**{"offer-bits": {"amount": 500, "max-rate": 40}})
    )

    assert cfg.offer_credits is None
    assert cfg.offer_bits is not None
    assert cfg.offer_bits.amount == 500


def test_trade_side_helpers() -> None:
    assert TradeSide.BID.label == "bits"
    assert TradeSide.ASK.label == "credits"
    assert TradeSide.BID.rate_in_limit(30, 40) is True
    assert TradeSide.BID.rate_in_limit(50, 40) is False
    assert TradeSide.ASK.clamp_rate(10, 70) == 70
    assert TradeSide.BID.is_overtaken(best=45, our_rate=40) is True
    assert TradeSide.ASK.is_overtaken(best=75, our_rate=70) is False
