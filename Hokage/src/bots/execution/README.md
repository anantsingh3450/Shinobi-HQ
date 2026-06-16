# Execution Bot

Runs strategies in paper or live mode using a **single shared strategy engine**.

## Pipeline position

```
Risk (pass) → **Execution** → Improvement
```

Hokage invokes Execution Bot only after Risk Bot returns a pass for the target mode.

## Structure

| Folder | Purpose |
|--------|---------|
| `engine/` | Strategy engine — signal generation, position sizing, risk rules (mode-agnostic) |
| `paper/` | Paper trading adapter — simulated fills and portfolio |
| `live/` | Live trading adapter — real broker orders via `integrations/brokers/` |

## Modes

- **Paper** — after Risk Bot paper gate pass; no real money
- **Live** — only when Hokage confirms all three live gates:
  1. User confirmation
  2. Risk validation (Risk Bot live re-check)
  3. Broker connectivity validation

The strategy logic in `engine/` is identical for both modes. Only the execution adapter differs.

No code yet.
