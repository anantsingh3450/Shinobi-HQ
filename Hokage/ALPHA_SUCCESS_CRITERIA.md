# Hokage Alpha Success Criteria
## Phase 5.0 — Performance & Compliance Targets

This document defines the quantitative benchmarks Hokage must satisfy during the 3-month simulated Alpha Program to be eligible for production promotion.

---

## 1. Compliance and Execution Targets
*   **Compliance Score ($CS$):** $\ge 95\%$
    *   *Definition:* The percentage of trades executed in full compliance with the 7-gate Investment Committee parameters, without any manual cancel, veto bypass, or parameter override.
    *   *Formula:*
        $$CS = \frac{\text{Compliant Trades}}{\text{Total Executed Trades}} \times 100$$
*   **Execution Quality Grade ($EQG$):** Average $\ge 80 / 100$
    *   *Entry Quality:* Average slippage between the calculated trigger price and the execution fill price must remain below $1.5\%$ of the ATR.
    *   *Sizing Quality:* 100% compliance with position sizing constraints based on the ATR and the active personality mode multiplier.
    *   *Stop Quality:* Zero stop-loss modifications that widen exposure.
    *   *Exit Quality:* Average capture efficiency of on-target exits $\ge 75\%$ of the available trend range.

---

## 2. Quantitative Performance Metrics
*   **Expectancy ($Ex$):** $> 0.0$ per trade
    *   *Definition:* The net mathematical expectation of profit per trade, ensuring the strategy possesses a positive edge under live spreads.
    *   *Formula:*
        $$Ex = (WR \times AvgWin) - ((1 - WR) \times AvgLoss)$$
*   **Profit Factor ($PF$):** $\ge 1.30$
    *   *Definition:* The ratio of gross profits to gross losses.
    *   *Formula:*
        $$PF = \frac{\sum \text{Profits}}{\sum \text{Losses}}$$
*   **Sharpe Ratio ($SR$):** $\ge 1.20$
    *   *Definition:* Risk-adjusted return metric. Locked at 0% risk-free rate baseline for the Alpha Program.
    *   *Formula:*
        $$SR = \frac{\text{Mean Daily Return}}{\text{Standard Deviation of Daily Returns}}$$

---

## 3. Risk and Drawdown Constraints
*   **Maximum Session Drawdown:** $\le 2.0\%$ (daily equity decay cap).
*   **Maximum Portfolio Drawdown:** $\le 8.0\%$ peak-to-trough (cumulative equity decay cap).
*   **Maximum Sector Exposure:** $\le 25\%$ of total account equity.
*   **Maximum Symbol Exposure:** $\le 5\%$ of total account equity.

---

## 4. Learning and Database Coverage
*   **Trade DNA Profiles:** 100% of closed trades must have complete fingerprints (regime, sector, conviction grade, holding period, result) logged in `trade_dna.jsonl`.
*   **Position Reviews:** 100% of closed trades must run through the Layer 2 `PositionReviewEngine` asynchronously, compiling quality grades and post-exit lessons in `position_reviews.jsonl`.
