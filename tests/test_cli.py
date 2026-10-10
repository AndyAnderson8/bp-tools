"""Command-line entry point: flag handling and --list."""

import builtins
import re
from pathlib import Path

import pytest

from bp_tools import __main__ as cli


def _config(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_nonpositive_sleep_is_rejected(tmp_path: Path) -> None:
    config = _config(tmp_path, "tools: []\n")

    assert cli.main(["--config", str(config), "--sleep", "0"]) == 2


def test_list_prints_enabled_tools(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _config(
        tmp_path,
        "tools:\n"
        "  - uuid: 2a0b9214-7f29-41f2-b913-067ff45fc778\n"
        "    enabled: true\n"
        "  - uuid: 121ce010-69e4-41c0-84af-0aac360b32df\n"
        "    enabled: false\n",
    )

    assert cli.main(["--config", str(config), "--list"]) == 0

    out = re.sub(r"\x1b\[[0-9;]*m", "", capsys.readouterr().out)
    assert "Enabled tools: 1" in out
    assert "item_sniper" in out


def test_bad_config_reports_and_fails(tmp_path: Path) -> None:
    config = _config(tmp_path, "- not a mapping\n")

    assert cli.main(["--config", str(config), "--list"]) == 2


def test_tui_without_textual_fails_cleanly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    real_import = builtins.__import__

    def fake_import(name: str, *args: object, **kwargs: object) -> object:
        if name.startswith("bp_tools.tui"):
            raise ImportError("textual missing")
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(builtins, "__import__", fake_import)
    config = _config(tmp_path, "tools: []\n")

    assert cli.main(["--config", str(config), "--tui"]) == 2
