# Portfolio Bot

The Portfolio Bot manages the account portfolio state. It is active in the unified pipeline.

## Role

- Tracks account balance, cash, realized PnL, and open position counts.
- Maintains and aggregates position details (market, direction, quantity, entry price, etc.).
- Persists and loads account details to/from local storage (`account_paper.json`).
- Updates portfolio state immediately after a trade executes, ensuring consistency.

## Integrations

| Module | Relationship |
|--------|--------------|
| Execution Bot | Updates portfolio holdings and cash balances on trade execution |
| Command Router | Feeds metrics for the interactive `portfolio` and `positions` CLI commands |
| Dashboard Service | Shares state via `account_paper.json` to serve Flask REST API queries |

## Implementation

The Portfolio Bot is implemented in `portfolio_bot.py`. The portfolio database model and storage management live in `models.py` and `store.py`.

