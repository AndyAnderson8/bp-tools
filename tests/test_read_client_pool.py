from bp_tools.core.config import AppConfig, UserToken
from bp_tools.core.contracts import BotBase, BotConfigBase
from bp_tools.core.runner import RunnerContext


class StubBot(BotBase[BotConfigBase]):
    name = "stub"
    CONFIG_CLASS = BotConfigBase

    def update(self) -> None:
        pass

    def execute(self) -> None:
        pass


def _context(read_usernames: list[str] | None) -> RunnerContext:
    users = [UserToken(name, name) for name in ("Main", "ReaderA", "ReaderB")]
    clients = {name: object() for name in ("Main", "ReaderA", "ReaderB")}
    config = AppConfig(users=users, tools={}, read_usernames=read_usernames)
    return RunnerContext(config=config, clients=clients)  # type: ignore[arg-type]


def test_get_client_rotates_only_through_read_pool() -> None:
    ctx = _context(["ReaderB", "ReaderA"])
    bot = StubBot(ctx, BotConfigBase())

    assert bot._next_get_client() is ctx.clients["ReaderB"]
    assert bot._next_get_client() is ctx.clients["ReaderA"]
    assert bot._next_get_client() is ctx.clients["ReaderB"]


def test_get_client_defaults_to_all_clients_in_stable_order() -> None:
    ctx = _context(None)
    bot = StubBot(ctx, BotConfigBase())

    assert bot._next_get_client() is ctx.clients["Main"]
    assert bot._next_get_client() is ctx.clients["ReaderA"]
    assert bot._next_get_client() is ctx.clients["ReaderB"]
