# Specialist Bots

Each bot is a self-contained module invoked by Hokage. **Bots do not talk to the user directly.**

| Bot | Folder | Output | Status |
|-----|--------|--------|--------|
| Research | `research/` | Findings, reports | **Implemented** |
| Strategy | `strategy/` | Strategy specifications | **Implemented** |
| Backtest | `backtest/` | Validation reports | **Implemented** |
| Risk | `risk/` | Risk assessments, pass/fail verdicts | **Implemented** |
| Execution | `execution/` | Paper and live trades | **Implemented** |
| Portfolio | `portfolio/` | Account state, FIFO position tracking | **Implemented** |
| Improvement | `improvement/` | Feedback and iteration proposals | Placeholder |

## Pipeline order

```
Research → Strategy → Backtest → Risk → Execution → Tax → Portfolio
```
