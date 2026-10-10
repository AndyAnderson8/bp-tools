"""Terminal UI: headless smoke test (skipped when the 'tui' extra is not installed)."""

import asyncio
from pathlib import Path

import pytest

pytest.importorskip("textual")

from bp_tools.tui import app as tui_app  # noqa: E402


class FakeBot:
    name = "fake_bot"
    poll_interval = 60.0

    def __init__(self) -> None:
        self.enabled = True
        self.last_run_at: float | None = None
        self.last_error = ""

    def run_once(self) -> None:
        pass


def test_space_toggles_selected_bot_and_q_quits(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bot = FakeBot()
    monkeypatch.setattr(tui_app, "build_bots", lambda *a, **k: [bot])
    monkeypatch.setattr(tui_app, "initialize_bots", lambda bots: None)

    async def scenario() -> list[bool]:
        app = tui_app.BpToolsApp(tmp_path / "config.yaml", dry_run=True)
        async with app.run_test(size=(120, 40)) as pilot:
            for _ in range(60):
                await pilot.pause(0.1)
                if app._bots:
                    break
            before = bot.enabled
            await pilot.press("space")
            await pilot.pause(0.2)
            after = bot.enabled
            await pilot.press("q")
            return [before, after]

    before, after = asyncio.run(scenario())

    assert before is True
    assert after is False
