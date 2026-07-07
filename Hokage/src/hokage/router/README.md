# Router

Maps user commands and orchestrator requests to the correct bot handler.

All user commands arrive via Hokage interface only. Router never exposes bot endpoints to the user.

Examples:

- "Research NIFTY momentum" → Research Bot
- "Backtest my latest strategy" → Backtest Bot
- "Assess risk" → Risk Bot
- "Start paper trading" → Execution Bot (paper), only if Risk Bot paper gate passed
- "Go live" → Hokage live promotion flow (user confirmation → Risk Bot → broker check → Execution Bot live)

## Implementation
The Command Router is implemented in `command_router.py`. It parses user commands and dispatches them to correct bot or orchestrator flows. It supports interactive CLI shell commands (`portfolio`, `positions`, `predictions`, `tax`, `trade`, `full-trade`).
