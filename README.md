# bp-tools

An extensible automation framework for [BrickPlanet](https://www.brickplanet.com). Build, configure, and run multiple bots from a single unified runner, each as its own self-contained plugin.

## Architecture

```
bp_tools/
├── core/               # framework engine
│   ├── api.py          # rate-limited API client
│   ├── config.py       # YAML config loader
│   ├── contracts.py    # BotBase ABC - implement update() + execute()
│   ├── runner.py       # discovery, scheduling, lifecycle
│   └── utils.py        # shared utilities
└── tools/              # drop-in bot plugins
    └── item_sniper/    # sample bot - auto-buy new shop items
```

The framework handles discovery, authentication, per-user API clients, rate limiting, and a cooperative polling loop. You write a bot - the framework runs it.

## Getting Started

### Prerequisites

- Python 3.12+
- A BrickPlanet API token ([Settings → API Tokens](https://www.brickplanet.com/account/settings))
- Membership in the [bp-tools authorization group](https://www.brickplanet.com/groups/2213) with **L2+ access** - request it in the group wall, DM **Revolt** on Discord (`Revolt8500`), or... learn Python and modify as you please! The code is open-source after all, lol.

### Installation

```bash
git clone https://github.com/AndyAnderson8/bp-tools.git
cd bp-tools
python -m venv .venv
.venv/Scripts/activate      # Windows
# source .venv/bin/activate  # macOS/Linux
pip install .
```

### Configuration

Copy the example config and fill in your tokens:

```yaml
# config.yaml
api_tokens:
  - username: "YourUsername"
    token: "your_api_token_here"

tools:
  - name: item_sniper
    enabled: true
    config:
      users:
        - username: "YourUsername"
          rares-only: true          # only buy rare/limited items
          # max-credits: 10000      # optional per-user spending cap
          # max-bits: 50000
      credit-to-bits-ratio: 50     # used to pick cheapest currency
```

### Running

```bash
python -m bp_tools --config config.yaml
```

**Options:**

| Flag | Description |
|------|-------------|
| `--config PATH` | Path to `config.yaml` (default: `./config.yaml`) |
| `--sleep N` | Seconds between polling cycles (default: `0.1`) |
| `--dry-run` | Print mutating requests instead of sending them |
| `--list` | List enabled tools and exit |

## Writing Your Own Bot

Create a new package under `bp_tools/tools/`:

```
bp_tools/tools/my_bot/
├── __init__.py     # TOOL_NAME, TOOL_UUID, BOT_CLASS
├── bot.py          # your bot class
└── models.py       # config dataclass
```

**`__init__.py`** - register your bot:

```python
from .bot import MyBot

TOOL_NAME = "my_bot"
TOOL_UUID = "generate-a-uuid-here"
TOOL_VERSION = "1.0.0"
BOT_CLASS = MyBot
```

**`bot.py`** - implement the contract:

```python
from bp_tools.core.contracts import BotBase
from .models import MyConfig

class MyBot(BotBase[MyConfig]):
    name = "my_bot"
    CONFIG_CLASS = MyConfig
    poll_interval = 5.0  # seconds between cycles

    def update(self) -> None:
        """Fetch latest state (read-only)."""
        ...

    def execute(self) -> None:
        """Act on what update() found."""
        ...
```

**`models.py`** - parse your config section:

```python
from dataclasses import dataclass
from typing import Any
from bp_tools.core.contracts import BotConfigBase

@dataclass(frozen=True, slots=True)
class MyConfig(BotConfigBase):
    username: str

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "MyConfig":
        return cls(username=raw["username"])
```

Add an entry in `config.yaml` under `tools:` and the runner picks it up automatically - zero framework changes needed.

## Rate Limiting

The framework ships with a tiered rate limiter configured via `rate_limits.yaml`. It supports per-route tier assignment with glob patterns and sliding-window enforcement. If no file is found, sensible defaults are used.

## Included Bots

| Bot | Description | README |
|-----|-------------|--------|
| `item_sniper` | Auto-buy new and restocked shop items | [README](bp_tools/tools/item_sniper/README.md) |

## Contributing

Contributions are welcome! Whether it's a new bot, a framework improvement, or a bug fix - open a PR or reach out on Discord.

Some ideas:
- New bot plugins (trading, inventory management, analytics)
- Proxy / session rotation support
- Webhook notifications (Discord, Telegram)
- Web dashboard for monitoring active bots

## Disclaimer

Use responsibly. Respect BrickPlanet's terms of service. The authors are not responsible for any actions taken against your account.

## License

[MIT](LICENSE)
