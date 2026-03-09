from abc import ABC, abstractmethod
from typing import Any, ClassVar, Generic, TypeVar


class BotConfigBase(ABC):
    """
    Base config contract for bots.
    """

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "BotConfigBase":
        """
        Parse and validate tool config.

        Uses :func:`parse_config` to auto-map kebab-case YAML keys to
        snake_case dataclass fields.  Override in subclasses that need
        custom parsing or cross-field validation.

        :param raw: Raw config dict from config.yaml for this tool.
        :returns: Parsed config instance.
        """
        from bp_tools.core.config_utils import parse_config

        return parse_config(cls, raw)


C = TypeVar("C", bound=BotConfigBase)


class BotBase(ABC, Generic[C]):
    """
    Minimal bot contract.

    A bot updates its view of the world, then optionally executes actions.

    Auth:
    - On init, resolves each user's ``role_num`` in the entitlements group.
    - Stores ``user_roles: dict[str, int]`` (username → role_num, 0 = not a member).
    - Calls ``authorize()`` which subclasses can override for custom auth logic.
    - Default ``authorize()`` checks ``min_role_num`` from entitlements JSON
      and raises if no user meets the requirement.
    """

    name: str
    CONFIG_CLASS: ClassVar[type[C]]
    poll_interval: float | None = 1.0  # None = run once at startup
    init_before: ClassVar[list[str]] = []  # UUIDs this bot must init BEFORE

    def __init__(
        self,
        ctx: Any,
        tool_config: dict[str, Any],
        tool_uuid: str = "",
        tool_version: str = "0.0.0",
    ) -> None:
        """
        :param ctx: Runner context.
        :param tool_config: Raw tool config dict from config.yaml.
        :param tool_uuid: UUID from the tool's __init__.py.
        :param tool_version: Semantic version from the tool's __init__.py.
        """
        self._ctx = ctx
        self.config: C = self.CONFIG_CLASS.from_dict(tool_config)  # type: ignore[assignment]
        self.tool_uuid: str = tool_uuid
        self.tool_version: str = tool_version
        self._get_client_index: int = 0

        # Resolve user roles from entitlements
        self.user_roles: dict[str, int] = {}
        self._resolve_roles()
        self._check_version()
        self.authorize()

    def _log(self, msg: str, overwrite: bool = False) -> None:
        """Print a scrolling log message with bot name prefix.

        If *overwrite* is True the message is routed to set_status instead
        (backward-compat shim – prefer ``_set_status`` for new code).
        """
        prefixed = f"[{self.name}] {msg}"
        if overwrite:
            self._set_status(prefixed)
            return
        from bp_tools.core.utils import color_print

        color_print(prefixed)

    def _set_status(self, text: str) -> None:
        """Update this bot's live status line in the dashboard."""
        from bp_tools.core.utils import set_status

        set_status(self.name, text)

    @staticmethod
    def _parse_semver(version: str) -> tuple[int, int, int]:
        """Parse 'major.minor.patch' into a 3-tuple. Delegates to utils."""
        from bp_tools.core.utils import parse_semver

        return parse_semver(version)

    def _check_version(self) -> None:
        """
        Compare local version against the entitlements JSON.
        - Major bump → block (raise)
        - Minor bump → warn (print)
        - Fails open if no version info available.
        """
        entitlements = getattr(self._ctx, "entitlements", None)
        if entitlements is None or not self.tool_uuid:
            return

        remote_ver = entitlements.version_for(self.tool_uuid)
        if remote_ver is None:
            return

        local = self._parse_semver(self.tool_version)
        remote = self._parse_semver(remote_ver)

        if remote[0] > local[0]:
            raise RuntimeError(
                f"Bot '{self.name}' v{self.tool_version} is outdated. "
                f"Version {remote_ver} is required. Please update."
            )

        if remote[1] > local[1]:
            print(
                f"  [!] Bot '{self.name}' v{self.tool_version}: "
                f"version {remote_ver} is available. Consider updating."
            )

    def _resolve_roles(self) -> None:
        """Resolve each user's role_num from the pre-resolved context roles."""
        from bp_tools.core.constants import ENTITLEMENTS_DISABLED

        if ENTITLEMENTS_DISABLED:
            return

        # Use pre-resolved roles from RunnerContext (resolved once, not per-bot)
        ctx_roles: dict[str, int] = getattr(self._ctx, "user_roles", {})
        if ctx_roles:
            self.user_roles = dict(ctx_roles)
            return

        # Fallback: resolve per-bot if context didn't pre-resolve
        entitlements = getattr(self._ctx, "entitlements", None)
        if entitlements is None or entitlements.group_id == 0:
            return

        from bp_tools.core.entitlements import resolve_user_role

        for username, client in self._ctx.clients.items():
            role_num = resolve_user_role(client, entitlements.group_id)
            self.user_roles[username] = role_num

    def authorize(self) -> None:
        """
        Called during init after roles are resolved.

        Default: checks if the entitlements JSON specifies a ``min_role_num``
        for this bot's UUID. If it does, requires at least one user to meet it.
        Raises ``PermissionError`` if no user qualifies.

        Override in subclasses for custom auth logic (e.g., per-feature gating).
        If the UUID is not in the entitlements, this is a no-op.
        """
        entitlements = getattr(self._ctx, "entitlements", None)
        if entitlements is None or not self.tool_uuid:
            return

        min_role = entitlements.min_role_for(self.tool_uuid)
        if min_role is None:
            # Not restricted
            return

        # Check if any user meets the requirement
        for username, role_num in self.user_roles.items():
            if role_num >= min_role:
                return

        raise PermissionError(
            f"Bot '{self.name}' requires role_num >= {min_role} in group "
            f"{entitlements.group_id}, but no user qualifies. "
            f"User roles: {self.user_roles}"
        )

    # ------------------------------------------------------------------
    # Shared client helpers
    # ------------------------------------------------------------------

    def _next_get_client(self) -> Any:
        """Round-robin through ALL available clients for GET requests."""
        clients = list(self._ctx.clients.values())
        if not clients:
            raise RuntimeError("No API clients available in context.")
        client = clients[self._get_client_index % len(clients)]
        self._get_client_index += 1
        return client

    @property
    def _write_username(self) -> str | None:
        """Override in subclass to set the username used for write operations."""
        return getattr(self.config, "username", None)

    @property
    def _write_client(self) -> Any:
        """The API client used for mutating requests (buy, cancel, etc.)."""
        username = self._write_username
        if username is None:
            raise ValueError(f"Bot '{self.name}' has no write username configured.")
        client = self._ctx.clients.get(username)
        if client is None:
            raise KeyError(f"API client not found for username: {username}")
        return client

    # ------------------------------------------------------------------
    # Bot contract
    # ------------------------------------------------------------------

    def initialize(self) -> None:
        """
        Called once after all bots are constructed, in dependency order.
        Override for startup work (cache init, wallet fetch, etc.).
        """
        pass

    @abstractmethod
    def update(self) -> None:
        """
        Fetch and store the latest state needed by the bot.
        This should NOT perform any irreversible actions.
        """
        raise NotImplementedError

    @abstractmethod
    def execute(self) -> None:
        """
        Perform actions based on the most recent update.
        """
        raise NotImplementedError

    def run_once(self) -> None:
        """
        One full bot cycle.
        """
        self.update()
        self.execute()
