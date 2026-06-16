# Risk Bot

Pre-execution risk assessment. Sits between Backtest and Execution in the pipeline.

## Pipeline position

```
Backtest → **Risk** → Execution
```

## Inputs

- Strategy spec from Strategy Bot
- Backtest results from Backtest Bot
- Configured risk limits from `config/bots/risk.yaml` (future)
- Portfolio context from Portfolio Manager (future — not required for v1)

## Outputs

- Risk assessment report → `data/risk/`
- Pass/fail verdict consumed by Hokage before invoking Execution Bot

## Gates

| Gate | When | Result |
|------|------|--------|
| **Paper gate** | After backtest, before paper execution | Must **pass** for paper mode |
| **Live gate** | During live promotion, after user confirmation | Must **pass** for live mode |

Hokage enforces verdicts. Risk Bot does not communicate with the user directly.

No code yet.
