from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar, Generic, TypeVar

from bp_tools.core.config_utils import parse_config
from bp_tools.core.utils import log_event, log_print, set_status

if TYPE_CHECKING:
    from bp_tools.core.runner import RunnerContext


def normalize_usernames(raw: dict[str, Any]) -> dict[str, Any]:
    """
    Return a copy of *raw* where a singular ``username`` becomes ``usernames``.

    Lets every tool accept either ``username: X`` or ``usernames: [X]``.
    """
    normalized = dict(raw)
    if "username" in normalized and "usernames" not in normalized:
        normalized["usernames"] = [normalized.pop("username")]
    return normalized


@dataclass(frozen=True, slots=True)
class BotConfigBase:
    """
    Base config contract for bots.

    All bot configs inherit ``usernames`` and ``poll_interval``.
    YAML ``username: "X"`` is auto-normalized to ``usernames: ["X"]``.
    """

    usernames: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "BotConfigBase":
        """
        Parse and validate tool config.

        Normalizes singular ``username`` to ``usernames`` list.
        Uses :func:`parse_config` to auto-map kebab-case YAML keys
        to snake_case dataclass fields.  Override in subclasses
        that need custom parsing or cross-field validation.
        """
        return parse_config(cls, normalize_usernames(raw))


C = TypeVar("C", bound=BotConfigBase)


class BotBase(ABC, Generic[C]):
    """
    Minimal bot contract.

    A bot updates its view of the world, then optionally executes actions.
    """

    name: str
    CONFIG_CLASS: ClassVar[type[C]]
    init_before: ClassVar[list[str]] = []  # UUIDs this bot must init BEFORE

    @property
    def poll_interval(self) -> float:
        """Poll interval in seconds."""
        return self._poll_interval

    def __init__(
        self,
        ctx: "RunnerContext",
        config: C,
        tool_uuid: str = "",
        tool_version: str = "0.0.0",
        poll_interval: float = 1.0,
    ) -> None:
        """
        :param ctx: Runner context.
        :param config: Parsed, typed bot config.
        :param tool_uuid: UUID from the tool's __init__.py.
        :param tool_version: Semantic version from the tool's __init__.py.
        :param poll_interval: Seconds between poll cycles.
        """
        self._ctx = ctx
        self.config: C = config
        self.tool_uuid: str = tool_uuid
        self.tool_version: str = tool_version
        self._poll_interval: float = poll_interval
        self._get_client_index: int = 0
        # Runtime state, observed by the TUI
        self.enabled: bool = True
        self.last_run_at: float | None = None
        self.last_error: str = ""

    def _log(self, msg: str, overwrite: bool = False) -> None:
        """Log a bot action in color, with a neutral status variant.

        If *overwrite* is True the message updates the gray INFO status line.
        """
        # Local cooldown rejections are expected while an account is paused;
        # the initial 429 is logged, then these would flood logs every poll.
        if "[backoff]" in msg:
            return
        prefixed = f"[{self.name}] {msg}"
        if overwrite:
            self._set_status(f"[INFO] {prefixed}")
            return
        log_print(f"[ACTION] {prefixed}")

    def _info(self, msg: str) -> None:
        """Log a neutral bot notice with the standard INFO prefix."""
        if "[backoff]" not in msg:
            log_event(f"[{self.name}] {msg}", level="INFO")

    def _warn(self, msg: str) -> None:
        """Log a recoverable problem with the standard WARN prefix."""
        if "[backoff]" not in msg:
            log_event(f"[{self.name}] {msg}", level="WARN")

    def _error(self, msg: str) -> None:
        """Log a failed operation with the standard ERROR prefix."""
        if "[backoff]" not in msg:
            log_event(f"[{self.name}] {msg}", level="ERROR")

    def _set_status(self, text: str) -> None:
        """Update this bot's live status line in the dashboard."""
        set_status(self.name, text)

    # ------------------------------------------------------------------
    # Shared client helpers
    # ------------------------------------------------------------------

    def _next_get_client(self) -> Any:
        """Round-robin through the configured read accounts for GET requests."""
        usernames = self._ctx.config.read_usernames
        clients = [
            self._ctx.clients[name]
            for name in (usernames or sorted(self._ctx.clients))
            if name in self._ctx.clients
        ]
        if not clients:
            raise RuntimeError("No API clients available for read requests.")
        client = clients[self._get_client_index % len(clients)]
        self._get_client_index += 1
        return client

    @property
    def _write_username(self) -> str | None:
        """First username from config, used for write operations."""
        if self.config.usernames:
            return self.config.usernames[0]
        return None

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
    # Shared wallet helpers (balances are shared by all bots via ctx.wallets)
    # ------------------------------------------------------------------

    @property
    def _write_account(self) -> str:
        """Username of the account this bot writes to (raises if not configured)."""
        username = self._write_username
        if username is None:
            raise ValueError(f"Bot '{self.name}' has no write username configured.")
        return username

    def _get_wallet(self, force: bool = False) -> dict[str, int]:
        """Cached balances for the write account, refreshed if stale or *force*."""
        return self._ctx.wallets.get(self._write_account, force)

    def _refresh_wallet(self) -> dict[str, int]:
        """Re-read the write account's balances from the API."""
        return self._ctx.wallets.refresh(self._write_account)

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
