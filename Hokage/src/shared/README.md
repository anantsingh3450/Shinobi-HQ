# Shared

Cross-cutting code used by Hokage and all bots.

## Submodules

| Folder | Purpose |
|--------|---------|
| `contracts/` | Data schemas — strategy spec, backtest result, order intent, pipeline state |
| `types/` | Shared type definitions |
| `utils/` | Logging helpers, date/time, file I/O |
| `events/` | Internal event bus for bot-to-bot messaging |

## Implementation
Shared structures and utility packages are defined under their respective subdirectories. The schemas inside `contracts` outline key structures used for research, risk, and backtesting.
