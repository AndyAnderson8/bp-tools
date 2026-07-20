from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar, Generic, TypeVar

from bp_tools.core.config_utils import parse_config
from bp_tools.core.utils import log_print, set_status

if TYPE_CHECKING:
    from bp_tools.core.runner import RunnerContext


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
        normalized = dict(raw)
        if "username" in normalized and "usernames" not in normalized:
            normalized["usernames"] = [normalized.pop("username")]

        return parse_config(cls, normalized)


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

    def _log(self, msg: str, overwrite: bool = False) -> None:
        """Print a scrolling log message with bot name prefix.

        If *overwrite* is True the message is routed to set_status instead
        (backward-compat shim – prefer ``_set_status`` for new code).
        """
        prefixed = f"[{self.name}] {msg}"
        if overwrite:
            self._set_status(prefixed)
            return
        log_print(prefixed)

    def _set_status(self, text: str) -> None:
        """Update this bot's live status line in the dashboard."""
        set_status(self.name, text)

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
