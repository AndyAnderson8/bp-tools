"""Config schema rules shared by all tools."""

import re
from pathlib import Path

from bp_tools.core.config import ToolConfig
from bp_tools.core.contracts import normalize_usernames
from bp_tools.core.runner import _collect_usernames, build_bots


def test_singular_username_is_normalized() -> None:
    assert normalize_usernames({"username": "A", "max-credits": 3}) == {
        "usernames": ["A"],
        "max-credits": 3,
    }


def test_usernames_list_is_left_alone() -> None:
    assert normalize_usernames({"usernames": ["A", "B"]}) == {"usernames": ["A", "B"]}


def test_normalization_does_not_mutate_input() -> None:
    raw = {"username": "A"}

    normalize_usernames(raw)

    assert raw == {"username": "A"}


def _tool(config: dict) -> ToolConfig:
    return ToolConfig(uuid="x", enabled=True, poll_interval=None, config=config)


def test_collects_from_each_supported_shape() -> None:
    names = _collect_usernames(
        [
            _tool({"username": "A"}),
            _tool({"usernames": ["B", "C"]}),
            _tool({"users": [{"username": "D"}, "E"]}),
        ]
    )

    assert names == {"A", "B", "C", "D", "E"}


def test_bad_tool_config_is_skipped_not_fatal(tmp_path: Path, capsys) -> None:
    config = tmp_path / "config.yaml"
    config.write_text(
        "api_tokens:\n"
        "  - username: Revolt\n"
        "    token: t\n"
        "tools:\n"
        "  - uuid: 2a0b9214-7f29-41f2-b913-067ff45fc778\n"  # item_sniper
        "    config:\n"
        "      users: [A]\n"
        "      credit-to-bits-ratio: lots\n",  # invalid: must be an int
        encoding="utf-8",
    )

    bots = build_bots(config)

    assert bots == []
    out = re.sub(r"\x1b\[[0-9;]*m", "", capsys.readouterr().out)
    assert "Skipping item_sniper" in out
