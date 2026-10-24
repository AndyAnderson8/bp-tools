"""
Textual terminal UI for bp-tools (``--tui``).

Layout:
  - Bot table: number, name, ON/OFF state, last run, last status/error.
  - Log pane: everything the runner and bots print.
  - Keys: ``space`` toggles the selected bot, ``q`` quits.

Bots run on a worker thread so the UI stays responsive. Log lines are
routed here through :func:`bp_tools.core.utils.set_log_sink`.
"""

import threading
import time
from pathlib import Path

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import DataTable, Footer, Header, RichLog, Static

from bp_tools.core import utils
from bp_tools.core.contracts import BotBase
from bp_tools.core.runner import build_bots, initialize_bots, run_bots

_REFRESH_SECONDS = 0.5
_TICK_SECONDS = 0.1


class BpToolsApp(App[None]):
    """Control panel: bot table on top, live log underneath."""

    TITLE = "bp-tools"
    CSS = """
    #bots {
        height: auto;
        max-height: 50%;
    }
    #notices {
        height: auto;
        padding: 0 1;
        color: $warning;
    }
    #log {
        border: round $accent;
        height: 1fr;
    }
    """
    BINDINGS = [
        Binding("space", "toggle_selected", "Toggle bot"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(
        self,
        config_path: Path,
        dry_run: bool = False,
        only_tools: list[str] | None = None,
    ) -> None:
        super().__init__()
        self._config_path = config_path
        self._dry_run = dry_run
        self._only_tools = only_tools
        self._bots: list[BotBase] = []
        self._rows_built = 0
        self._columns: list = []
        self._stop = threading.Event()
        self._main_thread = threading.get_ident()

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header()
        yield DataTable(id="bots", cursor_type="row", zebra_stripes=True)
        yield Static("", id="notices")
        yield RichLog(id="log", wrap=True, markup=False, highlight=False)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#bots", DataTable)
        self._columns = list(
            table.add_columns("#", "Bot", "State", "Last run", "Status")
        )
        utils.set_log_sink(self._on_log)
        self.set_interval(_REFRESH_SECONDS, self._refresh)
        self._start_bots()

    def on_unmount(self) -> None:
        self._stop.set()
        utils.set_log_sink(None)

    # ------------------------------------------------------------------
    # Logging (may be called from worker threads)
    # ------------------------------------------------------------------

    def _on_log(self, text: str, warning: bool) -> None:
        if threading.get_ident() == self._main_thread:
            self._write_log(text, warning)
        else:
            self.call_from_thread(self._write_log, text, warning)

    def _write_log(self, text: str, warning: bool) -> None:
        if text.startswith("[ERROR]"):
            style = "bold red"
        elif text.startswith("[WARN]") or warning:
            style = "bold yellow"
        elif text.startswith("[INFO]"):
            style = "dim"
        else:
            self.query_one("#log", RichLog).write(utils._gradient_text(text))
            return
        self.query_one("#log", RichLog).write(Text(text, style=style))

    def _notice(self, text: str) -> None:
        self.query_one("#notices", Static).update(text)

    # ------------------------------------------------------------------
    # Bots (worker thread)
    # ------------------------------------------------------------------

    @work(thread=True, exclusive=True)
    def _start_bots(self) -> None:
        try:
            bots = build_bots(
                self._config_path,
                dry_run=self._dry_run,
                only_tools=self._only_tools,
            )
        except Exception as exc:
            utils.log_event(f"Startup failed: {exc}", level="ERROR")
            return
        if not bots:
            utils.log_event("No bots to run.", level="WARN")
            return

        self._bots = bots
        initialize_bots(bots)
        run_bots(bots, should_stop=self._stop.is_set, sleep_seconds=_TICK_SECONDS)

    # ------------------------------------------------------------------
    # Table refresh (main thread)
    # ------------------------------------------------------------------

    def _refresh(self) -> None:
        table = self.query_one("#bots", DataTable)

        # Add rows for bots that appeared since the last refresh
        for i in range(self._rows_built, len(self._bots)):
            table.add_row(*[""] * len(self._columns), key=str(i))
        self._rows_built = len(self._bots)

        for i, bot in enumerate(self._bots):
            state = (
                Text("ON", style="green") if bot.enabled else Text("OFF", style="red")
            )
            last = (
                time.strftime("%H:%M:%S", time.localtime(bot.last_run_at))
                if bot.last_run_at
                else "-"
            )
            status = bot.last_error or utils.get_status(bot.name) or "-"
            values = [str(i + 1), bot.name, state, last, status]
            for column, value in zip(self._columns, values):
                table.update_cell(str(i), column, value)

        rate_limit = utils.get_status("_rate_limit")
        self._notice(rate_limit)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_toggle_selected(self) -> None:
        table = self.query_one("#bots", DataTable)
        row = table.cursor_row
        if row is None or row >= len(self._bots):
            return
        bot = self._bots[row]
        bot.enabled = not bot.enabled
        state = "ON" if bot.enabled else "OFF"
        utils.log_event(f"[ui] {bot.name} -> {state}")

    async def action_quit(self) -> None:
        self._stop.set()
        self.exit()


def run_tui(
    config_path: Path,
    dry_run: bool = False,
    only_tools: list[str] | None = None,
) -> int:
    """
    Run the terminal UI until the user quits.

    :param config_path: Path to config.yaml.
    :param dry_run: If True, POST/DELETE are printed not sent.
    :param only_tools: If set, only run these tool names/UUIDs.
    :returns: Exit code.
    """
    BpToolsApp(config_path, dry_run=dry_run, only_tools=only_tools).run()
    return 0
