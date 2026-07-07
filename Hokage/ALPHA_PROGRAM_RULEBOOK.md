# Hokage Alpha Program Rulebook
## Simulated Paper-Trading Governance & Operational Rulebook

This rulebook is the supreme governing document for Phase 5.0 of the HOKAGE trading system, establishing the rules, constraints, and audit protocols for the Alpha Program.

---

## 1. Governance Structure & Authority

Hokage operates as an autonomous system, governed by the following hierarchy:
1.  **Command Command Router (CLI):** Controls the system states (`OPEN_MARKET`, `NO_TRADE`) and monitors positions.
2.  **Investment Committee (7-Gate IC):** Evaluates opportunity candidates and applies strict vetoes prior to any order routing.
3.  **RiskBot:** Executes hard stops and exit sweeps.
4.  **Village Elder (User):** Monitors performance and compliance metrics via read-only dashboards and briefings. The Village Elder is prohibited from manual trade intervention, stop adjustments, or ordering changes on active paper assets.

---

## 2. Ingested Books & Doctrine Compliance

The read-only institutional knowledge modules define the core logic of the sizers and checkers:

### A. Margin of Safety & Intrinsic Value (*Benjamin Graham*)
*   The baseline Margin of Safety is locked at **$33.3\%$ required price discount** relative to the calculated intrinsic value.
*   The Graham Multiplier Screen ($PE \times PB \le 22.5$) is strictly enforced for defensive stock setups.
*   Projects 5-year average earnings capacity using multipliers capped between 8 and 20.

### B. Probabilistic Expectancy & Stops (*Mark Douglas*)
*   Risk-to-reward ratio for every technical setup must be $\ge 1.5$ at pre-entry.
*   Individual trade outcomes are treated as statistical noise; strategy parameters are evaluated only in blocks of $N \ge 30$ trades.
*   Positions hitting stops must be exited immediately by `RiskBot` sweeps. Discretionary hold-and-hope holds are forbidden.

### C. Execution Compliance & Cooldowns (*Brett Steenbarger*)
*   Execution compliance score ($CS \ge 95\%$) is tracked at EOD.
*   Autonomic Cooldown is triggered after $\ge 3$ consecutive losses, locking order entry for 60 minutes.
*   Dynamic risk scaling scales size up gradually (Elder Trust multiplier) but scales down rapidly.

### D. Qualitative Safeguards (*Philip Fisher & Peter Lynch*)
*   **Share Dilution Guard:** Vetoes stock entries if the company's annual share count increase $\ge 3\%$.
*   **Story Stock Veto:** Vetoes stock entries if revenue $\le 0$ or operational cash flow is negative.
*   **Sector Exposure Limit:** Total exposure to any single industry sector is capped at $25\%$ of account equity.

---

## 3. capital and Risk Sizing Specifications

*   **Alpha Capital:** `₹5,00,000.00` INR (simulated cash).
*   **Symbol Exposure Cap:** Capped at $5\%$ of total account equity per position (₹25,000.00 max risk size).
*   **Dynamic Asset Allocation:** Default split of 50-50 stock/bonds, adjusted between 25% and 75% at market valuation extremes.
*   **Speculative Allocation Limit:** Speculative "Mad Money" trades must run in a separate sub-portfolio capped at 10% of total equity, completely isolated from core cash.

---

## 4. Operational Protocols & Review Cadence

1.  **Morning Briefing (Pre-Market):** Executes to check capital balance, daily drawdown levels, active portfolio manager personality mode, and ATR limits.
2.  **Order Placement (Session):** Opportunities pass the 7 gates. If accepted, `ExecutionBot` routes orders to `PaperVenue`.
3.  **Position Review (Async post-exit):** Compiles entry, sizing, stop, and exit quality scores (0-100) and saves lessons in `position_reviews.jsonl`.
4.  **EOD Daily Review:** village Elder generates EOD report using [ALPHA_DAILY_REVIEW_TEMPLATE.md](file:///c:/Users/anant/OneDrive/Documents/AI%20PROJECT/AI%20COMMAND%20CENTRE/Hokage/ALPHA_DAILY_REVIEW_TEMPLATE.md).
5.  **Weekly Performance Review:** Runs performance rollups, Sharpe calculations, and regime audits using [ALPHA_WEEKLY_REVIEW_TEMPLATE.md](file:///c:/Users/anant/OneDrive/Documents/AI%20PROJECT/AI%20COMMAND%20CENTRE/Hokage/ALPHA_WEEKLY_REVIEW_TEMPLATE.md).

---

## 5. Failure & Emergency Procedures

*   **Emergency Mode:** Triggered if portfolio drawdown exceeds $8.0\%$ (loss of ₹40,000.00). System transitions to `NO_TRADE` mode, exits all open positions via market orders, and logs the event to the decision journal.
*   **Manual Intervention Lock:** Any discretionary cancel, stop modification, or IC gate bypass triggers program termination and revokes the Go status.
*   **Slippage Shock Quarantine:** If average slippage exceeds $2\%$ ATR over rolling 10 trades, execution is paused for spread calibration.
