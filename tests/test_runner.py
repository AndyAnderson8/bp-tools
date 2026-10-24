"""Runner: bot ticking, enable/disable, and config-driven bot building."""

from pathlib import Path
from unittest import mock

from bp_tools.core.config import AppConfig, UserToken
from bp_tools.core.runner import build_bots, create_api_clients, tick_bot


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


def test_clients_for_same_token_share_rate_limit_cooldown() -> None:
    config = AppConfig(
        users=[
            UserToken("reader-a", "same-token"),
            UserToken("reader-b", "same-token"),
        ],
        tools={},
    )

    clients = create_api_clients(config, {"reader-a", "reader-b"})

    assert (
        clients["reader-a"]._account_rate_limit_state
        is clients["reader-b"]._account_rate_limit_state
    )
    assert clients["reader-a"]._limiters is clients["reader-b"]._limiters


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


def test_start_with_no_bots_exits_cleanly(monkeypatch, tmp_path: Path) -> None:
    from bp_tools.core import runner

    monkeypatch.setattr(runner, "build_bots", lambda *a, **k: [])
    loop = mock.Mock()
    monkeypatch.setattr(runner, "_run_loop", loop)

    assert runner.start(tmp_path / "config.yaml") == 0
    loop.assert_not_called()


def test_start_initializes_then_runs_loop(monkeypatch, tmp_path: Path) -> None:
    from bp_tools.core import runner

    bot = CountingBot()
    order: list[str] = []
    monkeypatch.setattr(runner, "build_bots", lambda *a, **k: [bot])
    monkeypatch.setattr(runner, "initialize_bots", lambda bots: order.append("init"))
    monkeypatch.setattr(
        runner, "_run_loop", lambda bots, sleep: order.append("loop") or 0
    )

    assert runner.start(tmp_path / "config.yaml", sleep_seconds=0.5) == 0
    assert order == ["init", "loop"]


def test_run_loop_stops_on_ctrl_c(monkeypatch, capsys) -> None:
    from bp_tools.core import runner

    monkeypatch.setattr(runner, "start_live", lambda: None)
    monkeypatch.setattr(runner, "stop_live", lambda: None)

    def interrupt(*_a, **_k):
        raise KeyboardInterrupt

    monkeypatch.setattr(runner, "run_bots", interrupt)

    assert runner._run_loop([], 0.1) == 0
