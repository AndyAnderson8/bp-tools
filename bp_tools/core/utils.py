import sys
import time
from typing import Callable, Iterator

from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.text import Text

# ---------------------------------------------------------------------------
# Status dashboard  (powered by Rich)
# ---------------------------------------------------------------------------
# Each bot keeps one "status" line that overwrites in place at the bottom of
# the terminal.  Regular log messages scroll above the status block.
#
# Rich's Live display handles terminal width, line wrapping, cursor
# management, and cleanup — no manual ANSI escape codes needed.
# ---------------------------------------------------------------------------

_console = Console(highlight=False)
_status_lines: dict[str, str] = {}
_live: Live | None = None
_log_sink: Callable[[str, bool], None] | None = None


# -- gradient helpers --------------------------------------------------------

_GRADIENT_NORMAL = ((0, 255, 255), (255, 95, 255))
_GRADIENT_WARNING = ((255, 200, 0), (255, 100, 0))


def _gradient_chars(
    text: str, warning: bool = False
) -> Iterator[tuple[str, int, int, int]]:
    """Yield `(char, r, g, b)` for *text* (indented) along the gradient."""
    start, end = _GRADIENT_WARNING if warning else _GRADIENT_NORMAL
    indented = "    " + text
    n = max(len(indented) - 1, 1)
    for i, char in enumerate(indented):
        r = int(start[0] + (end[0] - start[0]) * i / n)
        g = int(start[1] + (end[1] - start[1]) * i / n)
        b = int(start[2] + (end[2] - start[2]) * i / n)
        yield char, r, g, b


def _gradient_text(text: str, warning: bool = False) -> Text:
    """Build a Rich Text object with gradient colouring."""
    rich_text = Text()
    for char, r, g, b in _gradient_chars(text, warning):
        rich_text.append(char, style=f"rgb({r},{g},{b})")
    return rich_text


def _build_status_display() -> Group:
    """Build the Rich renderable for the status dashboard."""
    parts: list[RenderableType] = [Text(""), Text("Current status(es):", style="dim")]
    for key, line in _status_lines.items():
        if not line:
            continue
        if key.startswith("_"):
            parts.append(Text(""))
        parts.append(Text(line, style="dim"))
    return Group(*parts)


# -- lifecycle ---------------------------------------------------------------


def start_live() -> None:
    """Start the live status display.  Call once at runner startup."""
    global _live
    if _live is not None:
        return
    _live = Live(
        "",
        console=_console,
        refresh_per_second=4,
        transient=True,  # status block disappears when stopped
    )
    _live.start()


def stop_live() -> None:
    """Stop the live status display.  Call at runner shutdown."""
    global _live
    if _live is not None:
        _live.stop()
        _live = None


# -- public API --------------------------------------------------------------


def set_status(source: str, text: str) -> None:
    """Update or create the status line for *source* and redraw."""
    _status_lines[source] = text
    if _live is not None:
        _live.update(_build_status_display())


def get_status(source: str) -> str:
    """Return the current status line for *source* ('' if none)."""
    return _status_lines.get(source, "")


def sleep_with_status(source: str, text: str, seconds: float) -> None:
    """Show *text* on the *source* status line while sleeping for *seconds*."""
    set_status(source, text)
    try:
        time.sleep(seconds)
    finally:
        set_status(source, "")


def set_log_sink(sink: Callable[[str, bool], None] | None) -> None:
    """
    Route log messages to *sink* instead of the console (None restores it).

    Used by alternate front-ends (e.g. the TUI) to capture log lines.
    """
    global _log_sink
    _log_sink = sink


def log_print(
    text: str = "",
    warning: bool = False,
    **_kw: object,
) -> None:
    """
    Print a scrolling log message with gradient colouring.

    When a log sink is set, the message goes there instead. When the Live
    status display is active, prints above the status block so it isn't
    overwritten.  Otherwise falls through to raw ANSI gradient output.
    """
    if _log_sink is not None:
        _log_sink(text, warning)
    elif _live is not None:
        if _console.is_terminal:
            _live.console.print(_gradient_text(text, warning=warning))
        else:
            _gradient_print_raw(text, warning=warning)
    else:
        _gradient_print_raw(text, warning=warning)


def log_event(text: str, *, level: str = "INFO") -> None:
    """Print a conventional, tagged log line without the bot-action gradient."""
    if "[backoff]" in text:
        return
    normalized = level.upper()
    if normalized not in {"INFO", "WARN", "ERROR"}:
        raise ValueError(f"Unknown log level: {level}")

    # Keep conventional log lines aligned with the indented action stream.
    line = f"    [{normalized}] {text}"
    style = {"INFO": "dim", "WARN": "yellow", "ERROR": "red"}[normalized]
    warning = normalized != "INFO"
    if _log_sink is not None:
        _log_sink(line, warning)
    elif _live is not None:
        _live.console.print(Text(line, style=style))
    elif sys.stdout.isatty():
        _console.print(Text(line, style=style))
    else:
        sys.stdout.write(f"{line}\n")
        sys.stdout.flush()


def _gradient_print_raw(text: str, warning: bool = False) -> None:
    """Write gradient text directly to stdout (used before Live starts)."""
    for char, r, g, b in _gradient_chars(text, warning):
        sys.stdout.write(f"\033[38;2;{r};{g};{b}m{char}\033[0m")
    sys.stdout.write("\n")
    sys.stdout.flush()
