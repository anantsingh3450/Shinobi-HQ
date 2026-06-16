# Hokage Workflow

## Standard Pipeline

1. **Research** — gather market context, hypotheses, and constraints
2. **Strategy** — translate research into a concrete trading strategy spec
3. **Backtest** — validate the strategy on historical data
4. **Risk** — assess strategy against risk limits; produce pass/fail for execution
5. **Execution (Paper)** — run the shared strategy engine in simulated mode
6. **Improvement** — analyze results, propose changes, update knowledge
7. **Repeat** — cycle back through Research / Strategy / Backtest / Risk as needed
8. **Execution (Live)** — deploy to live trading only when all live gates pass

## Gate Rules

### Paper execution (post-Risk)

- Backtest must complete successfully
- Risk Bot must return a **pass** for paper deployment
- Hokage invokes Execution Bot in paper mode

### Live execution (promotion from paper)

Live mode requires **all three** checks. Hokage orchestrates and enforces; the user never bypasses Hokage.

| Gate | Owner | Requirement |
|------|-------|-------------|
| **User confirmation** | Hokage | Explicit user approval via Hokage interface (e.g. confirm command in Telegram) |
| **Risk validation** | Risk Bot | Re-assessment against live risk limits; must return **pass** |
| **Broker connectivity** | Hokage + `integrations/brokers/` | Active connection to configured broker verified before first live order |

Additional rules:

- Paper trading is mandatory before live promotion
- Strategy engine is identical for paper and live; only the execution adapter changes
- If any live gate fails, Hokage blocks live execution and reports the reason to the user

## State Transitions

```
DRAFT
  → RESEARCHED
  → STRATEGIZED
  → BACKTESTED
  → RISK_APPROVED          (Risk Bot pass — paper eligible)
  → PAPER_ACTIVE
  → IMPROVED
  → LIVE_PENDING           (user confirmation requested)
  → LIVE_RISK_VALIDATED    (Risk Bot live re-check pass)
  → LIVE_BROKER_READY      (broker connectivity verified)
  → LIVE_ACTIVE
```

A strategy may return to earlier states (e.g. `IMPROVED → STRATEGIZED`) via the improvement loop.

State definitions will live in `src/shared/contracts/`.
