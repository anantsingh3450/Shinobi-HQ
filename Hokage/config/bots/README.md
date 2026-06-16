# Bot Configuration

One config file per bot (future):

- `research.yaml`
- `strategy.yaml`
- `backtest.yaml`
- `risk.yaml` — risk limits, drawdown thresholds, position caps
- `execution.yaml` — paper and live adapter settings
- `improvement.yaml`
- `portfolio.yaml` — future; allocation rules (disabled until implemented)

Each file overrides or extends `hokage.yaml` for that bot only.
