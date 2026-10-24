import argparse
import sys
from pathlib import Path

from bp_tools.core.config import load_config
from bp_tools.core.runner import discover_tools, start as start_runner
from bp_tools.core.utils import log_event


def _parse_args(argv: list[str]) -> argparse.Namespace:
    """
    Parse CLI arguments.

    :param argv: Raw argv list (excluding program name).
    :returns: Parsed args.
    """
    parser = argparse.ArgumentParser(
        prog="bp-tools", description="Run configured BrickPlanet tools."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path.cwd() / "config.yaml",
        help="Path to config.yaml (default: ./config.yaml)",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.1,
        help="Seconds between bot cycles (default: 0.1).",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List enabled tools from config and exit.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run normally but print POST/DELETE requests instead of sending them.",
    )
    parser.add_argument(
        "--tools",
        nargs="+",
        metavar="NAME",
        help="Only run these tools (by name). Omit to run all enabled tools.",
    )
    parser.add_argument(
        "--tui",
        action="store_true",
        help="Run the full-screen terminal UI (needs the 'tui' extra: textual).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """
    CLI entrypoint.

    :param argv: Optional argv override (excluding program name).
    :returns: Exit code.
    """
    args = _parse_args(argv or sys.argv[1:])

    if args.sleep <= 0:
        log_event("--sleep must be > 0", level="WARN")
        return 2

    if args.tui:
        try:
            from bp_tools.tui.app import run_tui
        except ImportError:
            log_event(
                "--tui needs the 'tui' extra: pip install -e .[tui]",
                level="WARN",
            )
            return 2
        return run_tui(
            config_path=args.config,
            dry_run=args.dry_run,
            only_tools=args.tools,
        )

    if args.list:
        try:
            cfg = load_config(args.config)
        except Exception as exc:
            log_event(f"Failed to load config: {exc}", level="ERROR")
            return 2

        registry = discover_tools()
        enabled = [t for t in cfg.tools.values() if t.enabled]
        log_event(f"Config: {args.config}")
        log_event(f"Enabled tools: {len(enabled)}")
        for t in enabled:
            tool = registry.get(t.uuid)
            name = tool.tool_name if tool else "unknown"
            log_event(f"  - {name} ({t.uuid})")
        return 0

    return start_runner(
        config_path=args.config,
        sleep_seconds=args.sleep,
        dry_run=args.dry_run,
        only_tools=args.tools,
    )


if __name__ == "__main__":
    raise SystemExit(main())
