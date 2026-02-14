from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True, slots=True)
class UserToken:
    username: str
    api_token: str


@dataclass(frozen=True, slots=True)
class ToolConfig:
    name: str
    enabled: bool
    config: dict[str, Any]


@dataclass(frozen=True, slots=True)
class AppConfig:
    users: list[UserToken]
    tools: dict[str, ToolConfig]


def load_config(path: Path) -> AppConfig:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError("config.yaml must be a mapping")

    # ---- api tokens ----
    tokens_raw = data.get("api_tokens", [])
    if not isinstance(tokens_raw, list):
        raise TypeError("api_tokens must be a list")

    users: list[UserToken] = []
    for entry in tokens_raw:
        if not isinstance(entry, dict):
            raise TypeError("each api_tokens entry must be a mapping")
        users.append(
            UserToken(
                username=entry["username"],
                api_token=entry["token"],
            )
        )

    # ---- tools ----
    tools_raw = data.get("tools", [])
    if not isinstance(tools_raw, list):
        raise TypeError("tools must be a list")

    tools: dict[str, ToolConfig] = {}
    for t in tools_raw:
        if not isinstance(t, dict):
            raise TypeError("each tools entry must be a mapping")

        name = t.get("name")
        if not isinstance(name, str):
            raise TypeError("tool name must be a string")

        enabled = bool(t.get("enabled", True))
        config = t.get("config", {})
        if not isinstance(config, dict):
            raise TypeError(f"tools[{name}].config must be a mapping")

        tools[name] = ToolConfig(
            name=name,
            enabled=enabled,
            config=config,
        )

    return AppConfig(users=users, tools=tools)
