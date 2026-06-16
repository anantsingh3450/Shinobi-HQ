# Router

Maps user commands and orchestrator requests to the correct bot handler.

All user commands arrive via Hokage interface only. Router never exposes bot endpoints to the user.

Examples (planned):

- "Research NIFTY momentum" → Research Bot
- "Backtest my latest strategy" → Backtest Bot
- "Assess risk" → Risk Bot
- "Start paper trading" → Execution Bot (paper), only if Risk Bot paper gate passed
- "Go live" → Hokage live promotion flow (user confirmation → Risk Bot → broker check → Execution Bot live)

No code yet.
