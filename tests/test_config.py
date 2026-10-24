from pathlib import Path

import pytest

from bp_tools.core.config import load_config


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_parses_tokens_and_tools(tmp_path: Path) -> None:
    cfg = load_config(
        _write(
            tmp_path,
            """
api_tokens:
  - username: "Revolt"
    token: "t1"
    password: "pw"
    two-factor-code: "123456"
  - username: "RA1N"
    token: "t2"
tools:
  - uuid: abc
    enabled: false
    poll-interval: 5
    config:
      username: "Revolt"
dev-mode: true
""",
        )
    )

    revolt, ra1n = cfg.users
    assert (revolt.username, revolt.token, revolt.password) == ("Revolt", "t1", "pw")
    assert revolt.two_factor_code == "123456"
    assert ra1n.password is None
    assert ra1n.two_factor_code is None

    tool = cfg.tools["abc"]
    assert tool.enabled is False
    assert tool.poll_interval == 5.0
    assert tool.config == {"username": "Revolt"}
    assert cfg.dev_mode is True


def test_poll_interval_is_none_when_omitted(tmp_path: Path) -> None:
    cfg = load_config(_write(tmp_path, "tools:\n  - uuid: abc\n"))

    tool = cfg.tools["abc"]
    assert tool.poll_interval is None
    assert tool.enabled is True
    assert tool.config == {}


def test_defaults_when_sections_missing(tmp_path: Path) -> None:
    cfg = load_config(_write(tmp_path, "{}\n"))
    assert cfg.users == []
    assert cfg.tools == {}
    assert cfg.dev_mode is False
    assert cfg.read_usernames is None


def test_parses_read_username_pool(tmp_path: Path) -> None:
    cfg = load_config(
        _write(
            tmp_path,
            """
api_tokens:
  - username: Main
    token: main-token
  - username: Scraper
    token: scraper-token
read-usernames:
  - Scraper
tools: []
""",
        )
    )

    assert cfg.read_usernames == ["Scraper"]


def test_read_usernames_must_reference_configured_accounts(tmp_path: Path) -> None:
    text = "api_tokens: []\nread-usernames: [Missing]\n"

    with pytest.raises(ValueError, match="no API token"):
        load_config(_write(tmp_path, text))


def test_read_usernames_must_be_a_nonempty_list(tmp_path: Path) -> None:
    with pytest.raises(TypeError, match="read-usernames must be a list"):
        load_config(_write(tmp_path, "read-usernames: Scraper\n"))
    with pytest.raises(ValueError, match="must not be empty"):
        load_config(_write(tmp_path, "read-usernames: []\n"))


def test_empty_file_is_an_empty_config(tmp_path: Path) -> None:
    cfg = load_config(_write(tmp_path, ""))

    assert cfg.users == []


def test_rejects_non_mapping(tmp_path: Path) -> None:
    with pytest.raises(TypeError, match="must be a mapping"):
        load_config(_write(tmp_path, "- just\n- a list\n"))


def test_rejects_tool_without_uuid_and_names_the_entry(tmp_path: Path) -> None:
    with pytest.raises(TypeError, match=r"tools\[0\]\.uuid is required"):
        load_config(_write(tmp_path, "tools:\n  - enabled: true\n"))


def test_rejects_duplicate_tool_uuid(tmp_path: Path) -> None:
    text = "tools:\n  - uuid: abc\n  - uuid: abc\n"

    with pytest.raises(ValueError, match="duplicate uuid"):
        load_config(_write(tmp_path, text))


def test_rejects_wrong_field_type_with_path(tmp_path: Path) -> None:
    text = "api_tokens:\n  - username: 5\n    token: x\n"

    with pytest.raises(TypeError, match=r"api_tokens\[0\]\.username"):
        load_config(_write(tmp_path, text))


def test_dev_mode_must_be_boolean(tmp_path: Path) -> None:
    with pytest.raises(TypeError, match="dev-mode"):
        load_config(_write(tmp_path, "dev-mode: 'no'\n"))
