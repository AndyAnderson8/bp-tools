import importlib
import pkgutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Type

from bp_tools.core.api import ApiClient
from bp_tools.core.config import AppConfig, ToolConfig, load_config
from bp_tools.core.constants import (
    FRAMEWORK_VERSION,
    RATE_LIMITS,
)
from bp_tools.core.contracts import BotBase
from bp_tools.core.utils import log_print as print
from bp_tools.core.utils import start_live, stop_live
from bp_tools.core.web_session import WebSession


@dataclass(frozen=True, slots=True)
class RunnerContext:
    """
    Shared context for all bots.

    :param config: Loaded app config.
    :param clients: API clients keyed by username.
    :param config_dir: Directory containing config.yaml (for DB path).
    :param web_sessions: Browser sessions keyed by username (for web purchases).
    """

    config: AppConfig
    clients: dict[str, ApiClient]
    config_dir: Path | None = None
    web_sessions: dict[str, WebSession] = field(default_factory=dict)

    @property
    def dev_mode(self) -> bool:
        return self.config.dev_mode


@dataclass(frozen=True, slots=True)
class LoadedTool:
    """
    :param tool_name: Tool name from tool package.
    :param tool_uuid: UUID from tool package.
    :param tool_version: Semantic version from tool package.
    :param module_path: Module path for that tool package.
    :param bot_cls: Bot class to instantiate.
    """

    tool_name: str
    tool_uuid: str
    tool_version: str
    module_path: str
    bot_cls: Type[BotBase]


def discover_tools(package_name: str = "bp_tools.tools") -> dict[str, LoadedTool]:
    """
    Discover tool packages.

    Tool package contract (in each tool package __init__.py):
      - TOOL_NAME: str
      - TOOL_UUID: str
      - BOT_CLASS: type[BotBase]

    :param package_name: Root package containing tools.
    :returns: Mapping tool_uuid -> LoadedTool.
    """
    root = importlib.import_module(package_name)
    found: dict[str, LoadedTool] = {}

    for mod_info in pkgutil.iter_modules(root.__path__, prefix=f"{package_name}."):
        module = importlib.import_module(mod_info.name)

        tool_name = getattr(module, "TOOL_NAME", None)
        bot_cls = getattr(module, "BOT_CLASS", None)

        # Skip non-tools
        if not isinstance(tool_name, str):
            continue

        if not isinstance(bot_cls, type) or not issubclass(bot_cls, BotBase):
            raise TypeError(f"{mod_info.name}: BOT_CLASS must be a BotBase subclass.")

        tool_uuid = getattr(module, "TOOL_UUID", "")
        tool_version = getattr(module, "TOOL_VERSION", "0.0.0")

        if not tool_uuid:
            raise ValueError(f"{mod_info.name}: TOOL_UUID is required.")

        if tool_uuid in found:
            raise ValueError(f"Duplicate TOOL_UUID: {tool_uuid!r}")

        found[tool_uuid] = LoadedTool(
            tool_name=tool_name,
            tool_uuid=tool_uuid if isinstance(tool_uuid, str) else "",
            tool_version=tool_version if isinstance(tool_version, str) else "0.0.0",
            module_path=mod_info.name,
            bot_cls=bot_cls,
        )

    return found


def _enabled_tools(cfg: AppConfig) -> list[ToolConfig]:
    """
    Return enabled tools from cfg.tools (dict).

    :param cfg: AppConfig.
    :returns: Enabled ToolConfig list.
    """
    enabled = [t for t in cfg.tools.values() if t.enabled]
    return enabled


def _collect_usernames(tools: list[ToolConfig]) -> set[str]:
    """
    Collect usernames referenced by enabled tools.

    Supports:
    - ``config.username`` (str) — normalized to usernames list
    - ``config.usernames`` (list of str)
    - ``config.users`` (list of dicts with "username" key)

    :param tools: Enabled tool configs.
    :returns: Set of usernames.
    """
    usernames: set[str] = set()
    for t in tools:
        # Plural form: list of usernames (covers normalized "username" too)
        raw = t.config.get("usernames", [])
        if isinstance(raw, list) and all(isinstance(x, str) for x in raw):
            usernames.update(raw)

        # Singular form: single username string
        single = t.config.get("username")
        if isinstance(single, str):
            usernames.add(single)

        # Nested users list (e.g. sniper: [{username: "Revolt"}, ...])
        users = t.config.get("users", [])
        if isinstance(users, list):
            for u in users:
                if isinstance(u, dict):
                    name = u.get("username")
                    if isinstance(name, str):
                        usernames.add(name)
    return usernames


def create_api_clients(
    cfg: AppConfig,
    usernames: set[str],
    rate_limits: dict[str, Any] | None = None,
    dry_run: bool = False,
) -> dict[str, ApiClient]:
    """
    Create API clients for requested users.

    Rate limits are tracked per authenticated user (per the BrickPlanet
    docs), so clients sharing the same API token share a single set of
    rate limiters.

    :param cfg: App config.
    :param usernames: Usernames to create clients for.
    :param rate_limits: Parsed rate-limits dict.
    :param dry_run: Pass through to ApiClient.
    :returns: Dict username -> ApiClient.
    """
    tokens_by_name = {u.username: u for u in cfg.users}

    missing = sorted(usernames - set(tokens_by_name.keys()))
    if missing:
        raise ValueError(f"Missing API tokens for usernames: {missing}")

    # Share limiters between clients with the same token (same user account)
    token_to_limiters: dict[str, Any] = {}
    clients: dict[str, ApiClient] = {}

    for username in sorted(usernames):
        user_token = tokens_by_name[username]
        print(f"Creating API client: {username}")
        client = ApiClient(
            token=user_token.api_token,
            rate_limits=rate_limits,
            dry_run=dry_run,
        )
        existing = token_to_limiters.get(user_token.api_token)
        if existing is not None:
            client._limiters = existing
        else:
            token_to_limiters[user_token.api_token] = client._limiters
        clients[username] = client

    return clients


def _print_banner(version: str) -> None:
    """Print the boot banner."""
    banner = r"""
▄▄▄▄▄▄▄   ▄▄▄▄▄▄▄      ▄▄▄▄▄▄▄▄▄   ▄▄▄▄▄     ▄▄▄▄▄   ▄▄▄       ▄▄▄▄▄▄▄
███▀▀███▄ ███▀▀███▄    ▀▀▀███▀▀▀ ▄███████▄ ▄███████▄ ███      █████▀▀▀
███▄▄███▀ ███▄▄███▀       ███    ███   ███ ███   ███ ███       ▀████▄
███  ███▄ ███▀▀▀▀ ▀▀▀▀▀   ███    ███▄▄▄███ ███▄▄▄███ ███         ▀████
████████▀ ███             ███     ▀█████▀   ▀█████▀  ████████ ███████▀

"""
    print()
    for line in banner.strip().split("\n"):
        print(line)
    print(f"by Revolt — Discord: Revolt8500 | v{version}\n")


def _instantiate_bots(
    enabled: list[ToolConfig],
    registry: dict[str, LoadedTool],
    ctx: RunnerContext,
) -> list[BotBase]:
    """Create bot instances, skipping on permission/runtime errors."""
    bots: list[BotBase] = []
    for t in enabled:
        tool = registry.get(t.uuid)
        if tool is None:
            raise ValueError(f"Tool enabled in config but not found: {t.uuid}")
        try:
            config = tool.bot_cls.CONFIG_CLASS.from_dict(t.config)
            bot = tool.bot_cls(
                ctx=ctx,
                config=config,
                tool_uuid=tool.tool_uuid,
                tool_version=tool.tool_version,
                poll_interval=t.poll_interval,
            )  # type: ignore[call-arg]
            bots.append(bot)
        except PermissionError as exc:
            print(f"  Skipping {tool.tool_name}: {exc}")
        except RuntimeError as exc:
            print(f"  Skipping {tool.tool_name}: {exc}")
    return bots


def _force_init_remaining(bots: list[BotBase]) -> None:
    """Force-init bots that are stuck in a circular dependency."""
    names = [b.name for b in bots]
    print(f"  [!] Circular init dependency, forcing: {names}")
    for b in bots:
        try:
            b.initialize()
        except Exception as exc:
            print(f"  [{b.name}] Init error: {exc}")


def _initialize_bots(bots: list[BotBase]) -> None:
    """
    Call ``initialize()`` on each bot in dependency order.

    Each bot can declare ``init_before: list[str]`` — UUIDs of bots that
    must NOT initialize until this bot has initialized first.
    """
    remaining = list(bots)

    while remaining:
        blocked: set[str] = set()
        for b in remaining:
            blocked.update(b.init_before)

        progressed = False
        next_remaining: list[BotBase] = []

        for b in remaining:
            if b.tool_uuid in blocked:
                next_remaining.append(b)
                continue
            try:
                b.initialize()
            except Exception as exc:
                print(f"  [{b.name}] Init error: {exc}")
            progressed = True

        remaining = next_remaining

        if not progressed and remaining:
            _force_init_remaining(remaining)
            break


def _tick_bot(
    b: BotBase,
    now: float,
    last_run: dict[str, float],
) -> None:
    """Run a single bot tick if its interval has elapsed."""
    elapsed = now - last_run[b.name]
    if elapsed >= b.poll_interval:
        try:
            b.run_once()
        except Exception as exc:
            print(f"  [{b.name}] Error: {exc}")
        last_run[b.name] = time.monotonic()


def _run_loop(bots: list[BotBase], sleep_seconds: float) -> int:
    """Main polling loop. Returns exit code."""
    start_live()
    last_run: dict[str, float] = {b.name: 0.0 for b in bots}

    try:
        while True:
            now = time.monotonic()
            for b in bots:
                _tick_bot(b, now, last_run)
            time.sleep(sleep_seconds)
    except KeyboardInterrupt:
        stop_live()
        print("\nStopped (Ctrl+C).")
        return 0
    finally:
        stop_live()
    return 0  # unreachable but keeps mypy happy


def _filter_tools(
    only_tools: list[str],
    enabled: list[ToolConfig],
    registry: dict[str, LoadedTool],
) -> list[ToolConfig]:
    """Filter enabled tools by name or UUID."""
    uuid_by_name = {lt.tool_name: lt.tool_uuid for lt in registry.values()}
    filter_uuids: set[str] = set()
    for name_or_uuid in only_tools:
        if name_or_uuid in registry:
            filter_uuids.add(name_or_uuid)
        elif name_or_uuid in uuid_by_name:
            filter_uuids.add(uuid_by_name[name_or_uuid])
        else:
            print(f"  Unknown tool: {name_or_uuid}")
    return [t for t in enabled if t.uuid in filter_uuids]


def _build_context(
    cfg: AppConfig,
    config_path: Path,
    dry_run: bool,
    bot_usernames: set[str],
) -> RunnerContext:
    """Create API clients, build RunnerContext."""
    all_usernames = {u.username for u in cfg.users}

    print(f"{len(all_usernames)} tokens found," " initializing user clients...")
    clients = create_api_clients(
        cfg, all_usernames, rate_limits=RATE_LIMITS, dry_run=dry_run
    )

    # Create web sessions for users that have passwords configured
    web_sessions: dict[str, WebSession] = {}
    for user_token in cfg.users:
        if user_token.password:
            try:
                web_sessions[user_token.username] = WebSession(
                    username=user_token.username,
                    password=user_token.password,
                )
            except Exception as exc:
                print(
                    f"  [!] Web session login failed for {user_token.username}: {exc}"
                )

    return RunnerContext(
        config=cfg,
        clients=clients,
        config_dir=config_path.parent,
        web_sessions=web_sessions,
    )


def _print_tool_summary(
    enabled: list[ToolConfig],
    registry: dict[str, LoadedTool],
    dry_run: bool,
) -> None:
    """Print the list of enabled tools."""
    print()
    print(f"Running {len(enabled)} tool(s):")
    for t in enabled:
        tool = registry.get(t.uuid)
        interval = t.poll_interval
        label = f"every {interval}s" if interval > 0 else "once"
        name = tool.tool_name if tool else t.uuid
        print(f"  - {name} ({label})")

    if dry_run:
        print("\n*** DRY RUN MODE" " — no POST/DELETE requests will be sent ***")
    print()


def start(
    config_path: Path,
    tools_package: str = "bp_tools.tools",
    sleep_seconds: float = 1.0,
    dry_run: bool = False,
    only_tools: list[str] | None = None,
) -> int:
    """
    Start runner: load config, create clients, run bots.

    :param config_path: Path to config.yaml.
    :param tools_package: Tools root package.
    :param sleep_seconds: Delay between cycles.
    :param dry_run: If True, POST/DELETE are printed not sent.
    :param only_tools: If set, only run these tool names/UUIDs.
    :returns: Exit code.
    """
    if sleep_seconds <= 0:
        raise ValueError("sleep_seconds must be > 0")

    _print_banner(FRAMEWORK_VERSION)

    cfg = load_config(config_path)
    registry = discover_tools(tools_package)

    enabled = _enabled_tools(cfg)
    if only_tools:
        enabled = _filter_tools(only_tools, enabled, registry)
    if not enabled:
        print("No enabled tools in config.")
        return 0

    bot_usernames = _collect_usernames(enabled)
    if not bot_usernames:
        print("No usernames configured for enabled tools.")
        return 0

    ctx = _build_context(cfg, config_path, dry_run, bot_usernames)
    _print_tool_summary(enabled, registry, dry_run)

    bots = _instantiate_bots(enabled, registry, ctx)
    _initialize_bots(bots)
    return _run_loop(bots, sleep_seconds)
