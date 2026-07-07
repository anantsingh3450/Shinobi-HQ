# Hokage Architecture Overview

## Principle

One commander, many specialists. **Hokage is the only user-facing interface.** The user never talks to individual bots directly.

## Layer Model

```
┌─────────────────────────────────────────┐
│              User Interface             │
│         (Telegram / CLI / API)          │
└─────────────────┬───────────────────────┘
                  │  user talks to Hokage only
┌─────────────────▼───────────────────────┐
│                 HOKAGE                  │
│   Orchestrator · Router · Memory        │
│   Live gates: confirm · risk · broker   │
└─────────────────┬───────────────────────┘
                  │
    ┌─────────────┼─────────────┬─────────────┐
    ▼             ▼             ▼             ▼
 Research    Strategy      Backtest        Risk
    │             │             │             │
    └─────────────┼─────────────┴─────────────┘
                  ▼
            Execution Bot
           (Paper ←→ Live)
                  │
                  ▼
            Tax Simulation
                  │
                  ▼
            Portfolio Bot
                  │
                  ▼
         Improvement Bot (future)
```

## Standard Pipeline

```
Research → Strategy → Backtest → Risk → Execution → Tax → Portfolio
```

## Folder Map

| Path | Purpose |
|------|---------|
| `src/hokage/` | Commander core — sole user interface |
| `src/bots/` | Specialist bot modules |
| `src/bots/risk/` | Pre-execution risk assessment |
| `src/bots/portfolio/` | Portfolio management (balances, cash, positions, realized PnL) |
| `src/shared/` | Cross-bot contracts and utilities |
| `src/integrations/` | External systems (brokers, data feeds) |
| `config/` | Configuration templates |
| `data/` | Runtime artifacts (gitignored) |
| `docs/` | Architecture and operational docs |
| `tests/` | Unit and integration test suites (106 tests passing) |
| `scripts/` | Dev and ops scripts (future) |
