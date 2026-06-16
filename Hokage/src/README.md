# Source Code

All Hokage application code lives here. No implementation yet — folders define module boundaries.

```
src/
├── hokage/          Commander core — sole user interface
├── bots/            Specialist bots (research, strategy, backtest, risk, execution, improvement, portfolio)
├── shared/          Contracts, types, utilities shared across bots
└── integrations/    External service adapters (brokers, data, Telegram)
```

Pipeline: `Research → Strategy → Backtest → Risk → Execution → Improvement`
