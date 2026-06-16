# Orchestrator

Runs the Hokage workflow pipeline:

1. Accept user intent from `interface/`
2. Determine current pipeline stage
3. Invoke the correct bot via `router/`
4. Enforce gates:
   - Risk Bot pass before any execution
   - Paper before live promotion
   - Live gates: user confirmation → risk validation → broker connectivity
5. Persist state via `memory/`

## Pipeline

```
Research → Strategy → Backtest → Risk → Execution → Improvement
```

No code yet.
