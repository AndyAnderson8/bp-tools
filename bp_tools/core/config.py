from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from bp_tools.core.config_utils import parse_config


@dataclass(frozen=True, slots=True)
class UserToken:
    """
    One account from ``api_tokens``.

    ``password`` and ``two-factor-code`` are only needed for web purchases.
    """

    username: str
    token: str
    password: str | None = None
    two_factor_code: str | None = None


@dataclass(frozen=True, slots=True)
class ToolConfig:
    """
    One entry from ``tools``.

    ``poll_interval`` is None when ``poll-interval`` is omitted, in which
    case the bot's own default is used.
    """

    uuid: str
    enabled: bool = True
    poll_interval: float | None = None
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AppConfig:
    users: list[UserToken]
    tools: dict[str, ToolConfig]  # keyed by UUID
    dev_mode: bool = False
    # Optional allowlist for round-robin read requests. Omitted means all
    # configured accounts, preserving the historical behavior.
    read_usernames: list[str] | None = None


def _records(data: dict[str, Any], key: str, cls: type) -> list[Any]:
    """Parse a top-level list of mappings into dataclass instances."""
    raw = data.get(key, [])
    if not isinstance(raw, list):
        raise TypeError(f"{key} must be a list")
    records = []
    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise TypeError(f"{key}[{index}] must be a mapping")
        records.append(parse_config(cls, entry, _path=f"{key}[{index}]."))
    return records


def load_config(path: Path) -> AppConfig:
    """
    Load and validate ``config.yaml``.

    :raises TypeError: On malformed structure or field types.
    """
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise TypeError("config.yaml must be a mapping")

    users: list[UserToken] = _records(data, "api_tokens", UserToken)
    tools_list: list[ToolConfig] = _records(data, "tools", ToolConfig)

    tools: dict[str, ToolConfig] = {}
    for tool in tools_list:
        if tool.uuid in tools:
            raise ValueError(f"tools: duplicate uuid {tool.uuid}")
        tools[tool.uuid] = tool

    dev_mode = data.get("dev-mode", False)
    if not isinstance(dev_mode, bool):
        raise TypeError("dev-mode must be true or false")
    read_usernames = data.get("read-usernames")
    if read_usernames is not None:
        if not isinstance(read_usernames, list) or not all(
            isinstance(name, str) and name for name in read_usernames
        ):
            raise TypeError("read-usernames must be a list of usernames")
        if not read_usernames:
            raise ValueError("read-usernames must not be empty when specified")
        unknown = sorted(set(read_usernames) - {user.username for user in users})
        if unknown:
            raise ValueError(f"read-usernames has no API token for: {unknown}")
    return AppConfig(
        users=users,
        tools=tools,
        dev_mode=dev_mode,
        read_usernames=read_usernames,
    )
