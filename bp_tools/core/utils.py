import sys
from rich.console import Console, Group
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


def parse_semver(version: str) -> tuple[int, int, int]:
    """Parse 'major.minor.patch' into a 3-tuple. Returns (0,0,0) on error."""
    try:
        parts = version.split(".")
        return (int(parts[0]), int(parts[1]), int(parts[2]))
    except (IndexError, ValueError):
        return (0, 0, 0)


# -- gradient helpers --------------------------------------------------------

_GRADIENT_NORMAL = ((0, 255, 255), (255, 95, 255))
_GRADIENT_WARNING = ((255, 200, 0), (255, 100, 0))


def _gradient_text(text: str, warning: bool = False) -> Text:
    """Build a Rich Text object with gradient colouring."""
    start, end = _GRADIENT_WARNING if warning else _GRADIENT_NORMAL
    indented = "    " + text
    rich_text = Text()
    n = max(len(indented) - 1, 1)
    for i, char in enumerate(indented):
        r = int(start[0] + (end[0] - start[0]) * i / n)
        g = int(start[1] + (end[1] - start[1]) * i / n)
        b = int(start[2] + (end[2] - start[2]) * i / n)
        rich_text.append(char, style=f"rgb({r},{g},{b})")
    return rich_text


def _build_status_display() -> Group:
    """Build the Rich renderable for the status dashboard."""
    parts = [Text(""), _gradient_text("Current status(es):")]
    for line in _status_lines.values():
        parts.append(_gradient_text(line))
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


def color_print(
    text: str = "", warning: bool = False, **_kw: object,
) -> None:
    """
    Print a regular scrolling log message with gradient colouring.

    Works correctly alongside the Live status display — Rich handles
    the coordination so log messages scroll above the status block.
    """
    if _live is not None:
        _live.console.print(_gradient_text(text))
    else:
        # Fallback before live is started (e.g. banner)
        _gradient_print_raw(text, warning=warning)


def _gradient_print_raw(text: str, warning: bool = False) -> None:
    """Write gradient text directly to stdout (used before Live starts)."""
    start, end = _GRADIENT_WARNING if warning else _GRADIENT_NORMAL
    indented = "    " + text
    n = max(len(indented) - 1, 1)
    for i, char in enumerate(indented):
        r = int(start[0] + (end[0] - start[0]) * i / n)
        g = int(start[1] + (end[1] - start[1]) * i / n)
        b = int(start[2] + (end[2] - start[2]) * i / n)
        sys.stdout.write(f"\033[38;2;{r};{g};{b}m{char}\033[0m")
    sys.stdout.write("\n")
    sys.stdout.flush()
