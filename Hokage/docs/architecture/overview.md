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
           Improvement Bot
                  │
                  └──► loop back to Research / Strategy

    ┌─────────────────────────────────────┐
    │  Portfolio Manager  (future)        │
    │  placeholder — not in active pipe   │
    └─────────────────────────────────────┘
```

## Standard Pipeline

```
Research → Strategy → Backtest → Risk → Execution → Improvement
```

## Folder Map

| Path | Purpose |
|------|---------|
| `src/hokage/` | Commander core — sole user interface |
| `src/bots/` | Specialist bot modules |
| `src/bots/risk/` | Pre-execution risk assessment |
| `src/bots/portfolio/` | Future placeholder — portfolio management |
| `src/shared/` | Cross-bot contracts and utilities |
| `src/integrations/` | External systems (brokers, data feeds) |
| `config/` | Configuration templates |
| `data/` | Runtime artifacts (gitignored) |
| `docs/` | Architecture and operational docs |
| `tests/` | Test suites (future) |
| `scripts/` | Dev and ops scripts (future) |
