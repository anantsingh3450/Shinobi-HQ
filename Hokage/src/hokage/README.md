# Hokage Commander

**The only module the user interacts with.** Routes intent to bots and enforces workflow gates.

## Submodules (planned)

| Folder | Responsibility |
|--------|----------------|
| `orchestrator/` | Workflow engine — drives Research → Strategy → Backtest → Risk → Execution → Improvement |
| `router/` | Command parsing and bot dispatch |
| `memory/` | Session state, mission context, conversation history |
| `interface/` | User channels — Telegram, CLI, HTTP API |

## Live promotion (Hokage-owned)

When the user requests live execution, Hokage sequentially enforces:

1. **User confirmation** — capture explicit approval
2. **Risk validation** — invoke Risk Bot live gate
3. **Broker connectivity validation** — verify broker integration before first order

Only then does Hokage activate Execution Bot in live mode.
