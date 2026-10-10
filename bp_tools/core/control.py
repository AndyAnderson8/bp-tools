"""
Optional control panel for the runner (``--ui``).

Shows a table of loaded bots with their on/off state, last run time and
status, and reads commands from stdin:

    <n>        toggle bot number n
    t <n>      same as above
    q          quit (same as Ctrl+C)
"""

import threading
import time
from typing import TYPE_CHECKING

from rich.table import Table

from bp_tools.core.utils import get_status
from bp_tools.core.utils import log_print as print

if TYPE_CHECKING:
    from bp_tools.core.contracts import BotBase

_HELP = "Commands: <n> or t <n> toggles a bot, q quits."


class BotControl:
    """Holds bot on/off state and renders the control panel."""

    def __init__(self, bots: "list[BotBase]") -> None:
        self._bots = bots
        self.running = True

    def toggle(self, index: int) -> None:
        """Flip the enabled flag of the bot at 1-based *index*."""
        if not 1 <= index <= len(self._bots):
            print(f"[ui] No bot #{index}", warning=True)
            return
        bot = self._bots[index - 1]
        bot.enabled = not bot.enabled
        state = "ON" if bot.enabled else "OFF"
        print(f"[ui] {bot.name} -> {state}")

    def handle(self, line: str) -> None:
        """Process one command line."""
        parts = line.strip().split()
        if not parts:
            return
        if parts[0] == "q":
            self.running = False
            return
        if parts[0] == "t" and len(parts) == 2:
            parts = parts[1:]
        if len(parts) == 1 and parts[0].isdigit():
            self.toggle(int(parts[0]))
            return
        print(f"[ui] Unknown command. {_HELP}", warning=True)

    def render(self) -> Table:
        """Build the control-panel table."""
        table = Table(title="bp-tools control panel", title_style="bold", expand=True)
        table.add_column("#", justify="right", no_wrap=True)
        table.add_column("Bot", no_wrap=True)
        table.add_column("State", no_wrap=True)
        table.add_column("Last run", no_wrap=True)
        table.add_column("Status")

        for i, bot in enumerate(self._bots, 1):
            state = "[green]ON[/]" if bot.enabled else "[red]OFF[/]"
            last = (
                time.strftime("%H:%M:%S", time.localtime(bot.last_run_at))
                if bot.last_run_at
                else "-"
            )
            status = bot.last_error or get_status(bot.name) or "-"
            table.add_row(str(i), bot.name, state, last, status)

        table.caption = _HELP
        return table


def start_command_reader(control: BotControl) -> threading.Thread:
    """Read commands from stdin on a daemon thread until quit or EOF."""

    def _loop() -> None:
        while control.running:
            try:
                line = input()
            except (EOFError, OSError):
                return
            control.handle(line)

    thread = threading.Thread(target=_loop, name="bp-tools-ui", daemon=True)
    thread.start()
    return thread
