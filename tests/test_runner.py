"""Runner: bot ticking, enable/disable, and config-driven bot building."""

from pathlib import Path

from bp_tools.core.runner import build_bots, tick_bot


class CountingBot:
    name = "counting"
    poll_interval = 10.0

    def __init__(self, fail: bool = False) -> None:
        self.enabled = True
        self.last_run_at: float | None = None
        self.last_error = ""
        self.runs = 0
        self._fail = fail

    def run_once(self) -> None:
        self.runs += 1
        if self._fail:
            raise RuntimeError("boom")


def test_tick_runs_when_interval_elapsed() -> None:
    bot = CountingBot()
    last_run = {bot.name: 0.0}

    tick_bot(bot, now=100.0, last_run=last_run)  # type: ignore[arg-type]

    assert bot.runs == 1
    assert bot.last_run_at is not None


def test_tick_waits_for_interval() -> None:
    bot = CountingBot()
    last_run = {bot.name: 0.0}

    tick_bot(bot, now=100.0, last_run=last_run)  # type: ignore[arg-type]
    tick_bot(bot, now=100.0, last_run=last_run)  # type: ignore[arg-type]

    assert bot.runs == 1


def test_disabled_bot_does_not_run() -> None:
    bot = CountingBot()
    bot.enabled = False

    tick_bot(bot, now=100.0, last_run={bot.name: 0.0})  # type: ignore[arg-type]

    assert bot.runs == 0


def test_error_is_recorded_and_not_raised() -> None:
    bot = CountingBot(fail=True)

    tick_bot(bot, now=100.0, last_run={bot.name: 0.0})  # type: ignore[arg-type]

    assert bot.last_error == "boom"
    assert bot.runs == 1


def test_build_bots_with_nothing_enabled_returns_empty(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text("api_tokens: []\ntools: []\n", encoding="utf-8")

    assert build_bots(config) == []


def test_run_bots_stops_when_asked() -> None:
    from bp_tools.core.runner import run_bots

    bot = CountingBot()
    bot.poll_interval = 0.0
    ticks = {"n": 0}

    def should_stop() -> bool:
        ticks["n"] += 1
        return ticks["n"] > 3

    run_bots([bot], should_stop=should_stop, sleep_seconds=0)  # type: ignore[list-item]

    assert bot.runs == 3
