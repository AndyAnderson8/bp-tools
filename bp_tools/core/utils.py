import sys

# Bot status dashboard: source → last status message
_status_lines: dict[str, str] = {}
_status_line_count: int = 0  # how many lines the status block currently occupies


def parse_semver(version: str) -> tuple[int, int, int]:
    """Parse 'major.minor.patch' into a 3-tuple. Returns (0,0,0) on error."""
    try:
        parts = version.split(".")
        return (int(parts[0]), int(parts[1]), int(parts[2]))
    except (IndexError, ValueError):
        return (0, 0, 0)


def _render_status() -> None:
    """Clear and redraw the status dashboard."""
    global _status_line_count

    # Move up and clear previous status lines
    if _status_line_count > 0:
        sys.stdout.write(f"\033[{_status_line_count}A")
        for _ in range(_status_line_count):
            sys.stdout.write("\033[2K\n")
        sys.stdout.write(f"\033[{_status_line_count}A")

    # Redraw current status lines
    for source, line in _status_lines.items():
        _write_gradient(line)
        sys.stdout.write("\n")

    _status_line_count = len(_status_lines)
    sys.stdout.flush()


def _write_gradient(text: str, warning: bool = False) -> None:
    """Write gradient-colored text to stdout (no newline)."""
    if warning:
        start_color = (255, 200, 0)
        end_color = (255, 100, 0)
    else:
        start_color = (0, 255, 255)
        end_color = (255, 95, 255)

    indented = "    " + text
    n = len(indented)
    for i, char in enumerate(indented):
        r = int(start_color[0] + (end_color[0] - start_color[0]) * i / max(n - 1, 1))
        g = int(start_color[1] + (end_color[1] - start_color[1]) * i / max(n - 1, 1))
        b = int(start_color[2] + (end_color[2] - start_color[2]) * i / max(n - 1, 1))
        sys.stdout.write(f"\033[38;2;{r};{g};{b}m{char}\033[0m")


def color_print(
    text: str = "", overwrite: bool = False, warning: bool = False, source: str = ""
) -> None:
    """
    Print text with a color transition.

    :param text: The text to print.
    :param overwrite: If True, update the status dashboard for this source.
    :param source: Bot name — used to track per-bot status lines.
    """
    global _status_line_count

    if overwrite and source:
        _status_lines[source] = text
        _render_status()
        return

    # Non-status message: clear status block, print message, redraw status
    if _status_line_count > 0:
        sys.stdout.write(f"\033[{_status_line_count}A")
        for _ in range(_status_line_count):
            sys.stdout.write("\033[2K\n")
        sys.stdout.write(f"\033[{_status_line_count}A")
        _status_line_count = 0

    for line in text.split("\n"):
        _write_gradient(line, warning=warning)
        sys.stdout.write("\n")
    sys.stdout.flush()

    # Redraw status dashboard below the new message
    if _status_lines:
        _render_status()
