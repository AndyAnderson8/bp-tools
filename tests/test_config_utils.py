"""parse_config: kebab-case mapping, coercion and validation."""

from dataclasses import dataclass, field

import pytest

from bp_tools.core.config_utils import parse_config


@dataclass(frozen=True, slots=True)
class Inner:
    amount: int
    max_rate: float = 1.0


@dataclass(frozen=True, slots=True)
class Outer:
    name: str
    poll_interval: float = 2.0
    flag: bool = False
    inner: Inner | None = None
    tags: list[str] = field(default_factory=list)
    inners: list[Inner] = field(default_factory=list)


def test_kebab_keys_map_to_snake_fields() -> None:
    cfg = parse_config(Outer, {"name": "x", "poll-interval": 5, "flag": True})

    assert cfg.poll_interval == 5.0
    assert cfg.flag is True


def test_nested_dataclasses_are_parsed() -> None:
    cfg = parse_config(
        Outer,
        {
            "name": "x",
            "inner": {"amount": 3, "max-rate": 2.5},
            "inners": [{"amount": 1}],
        },
    )

    assert cfg.inner == Inner(amount=3, max_rate=2.5)
    assert cfg.inners == [Inner(amount=1)]


def test_missing_required_field_raises() -> None:
    with pytest.raises(TypeError, match="name is required"):
        parse_config(Outer, {})


def test_wrong_type_names_the_field() -> None:
    with pytest.raises(TypeError, match="amount must be an int"):
        parse_config(Inner, {"amount": "lots"})


def test_bool_is_not_accepted_as_int() -> None:
    with pytest.raises(TypeError):
        parse_config(Inner, {"amount": True})


def test_none_for_non_optional_field_raises() -> None:
    with pytest.raises(TypeError, match="must be an int"):
        parse_config(Inner, {"amount": None})


def test_non_mapping_for_nested_dataclass_raises() -> None:
    with pytest.raises(TypeError, match="must be a mapping"):
        parse_config(Outer, {"name": "x", "inner": 5})


def test_list_expected_but_mapping_given() -> None:
    with pytest.raises(TypeError, match="must be a list"):
        parse_config(Outer, {"name": "x", "tags": {"a": 1}})


@pytest.mark.parametrize("value", ["no", "false", 0, None])
def test_bool_field_rejects_non_boolean_values(value: object) -> None:
    @dataclass(frozen=True, slots=True)
    class Flag:
        enabled: bool = True

    with pytest.raises(TypeError, match="true or false"):
        parse_config(Flag, {"enabled": value})
