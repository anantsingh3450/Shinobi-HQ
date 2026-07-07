# Hokage Market Wizards Playbook
## Algorithmic Ingestion of Jack D. Schwager's Elite Trader Interviews

This playbook distills the core trading principles, risk management doctrines, and position-sizing philosophies from Jack D. Schwager's *Market Wizards* series into structured guidelines for Hokage.

Rather than summarizing the book or listing individual trader anecdotes, this playbook extracts **timeless, style-independent, and regime-resistant methodologies** shared by elite traders (e.g., Paul Tudor Jones, Ed Seykota, Bruce Kovner, Richard Dennis, and Michael Marcus). These concepts are mapped directly into Hokage's modular execution and risk boundaries.

---

## 1. Elite Trader Doctrines

These eight foundational doctrines represent the unified core philosophy of the world's most successful traders, converted into algorithmic assertions.

### [Doctrine 1] Preserve Capital First
*   **Philosophy:** Survival is the prerequisite for performance. Protecting the capital base takes precedence over generating alpha.
*   **Hokage Assertion:** Active drawdown caps and daily loss limits are managed by the `CapitalPreservationEngine`. If breached, new entries are blocked.

### [Doctrine 2] Cut Losses Fast
*   **Philosophy:** Invalidation must be acknowledged instantly. Ed Seykota's primary rule: "(1) Cut losses. (2) Cut losses. (3) Cut losses."
*   **Hokage Assertion:** `RiskBot` enforces hard stop losses. Stops can never be widened or canceled.

### [Doctrine 3] Let Winners Run
*   **Philosophy:** Profit accumulation is driven by outlier moves. The strategy must capture asymmetric extensions.
*   **Hokage Assertion:** Use trailing stops (e.g., ATR-based) to capture trend expansions, rather than exiting prematurely.

### [Doctrine 4] Size by Conviction
*   **Philosophy:** Sizing must scale dynamically based on edge confidence and current portfolio drawdown. Sizing should be small during losing streaks and standard during winning regimes.
*   **Hokage Assertion:** Sizing is adjusted using the `ElderTrustEngine` multiplier and recent win-rate feedback.

### [Doctrine 5] Avoid Emotional Trading
*   **Philosophy:** Intuition is often masked emotion. Trading must be systemic, disciplined, and rule-based.
*   **Hokage Assertion:** Automated order execution via the 7-gate Investment Committee cannot be overridden by human-in-the-loop hope.

### [Doctrine 6] Wait for Asymmetric Opportunities
*   **Philosophy:** Only enter setups with high reward-to-risk ratios (e.g., $\ge 1:2$ or $1:3$).
*   **Hokage Assertion:** The `NoTradeDecisionEngine` vetoes proposals with an expected reward-to-risk ratio below $1.5$.

### [Doctrine 7] Adapt to Market Regimes
*   **Philosophy:** A single trading strategy will not work in all environments. One must recognize when a regime changes and stand aside or adjust logic.
*   **Hokage Assertion:** The `MarketScanner` changes active modes (Balanced, Defensive, Recovery) based on regime parameters.

### [Doctrine 8] Survive Long Enough to Compound
*   **Philosophy:** Consistent compounding requires avoiding catastrophic drawdown outliers.
*   **Hokage Assertion:** The system caps maximum symbol exposure at $5\%$ of total equity and sector exposure at $25\%$.

---

## 2. Playbook Sections

### Core Principles
1.  **Strict Risk Control:** The absolute necessity of knowing where you are getting out *before* you get in.
2.  **Edge Understanding:** Knowing exactly what your edge is and executing only when that edge is present.
3.  **Statistical Horizon:** Evaluating results over a large sample size of independent trials.

### Common Traits of Elite Traders
*   **Rigid Risk Discipline:** Uncompromising adherence to stop-loss guidelines.
*   **Patience:** The ability to sit on cash and do nothing when the market does not offer high-probability setups.
*   **Self-Analysis:** Continual monitoring of execution slippage and compliance errors.
*   **Emotional Resilience:** Treating wins and losses with equal detachment.

### Risk Management Philosophies
*   **Pre-defined Risk Limits:** Risking a fixed, small percentage of total equity per trade (typically $1\%$ to $2\%$).
*   **Max Portfolio Correlation Constraints:** Limiting total open risk across correlated symbols. If multiple symbols in the same sector trigger, position sizes must be scaled down to prevent high sector exposure.

### Position Sizing Philosophies
*   **Equity-Based Sizing:** Sizing is calculated based on total account equity, never on nominal contract values.
*   **Volatility-Adjusted Sizing:** Using ATR (Average True Range) to adjust share size, ensuring that high-volatility instruments are sized smaller, keeping the absolute dollar risk equal.

### Trend Following Concepts
*   **Ride the Outliers:** Capturing major market movements through breakout entries and trailing stops.
*   **Accept Low Win Rates:** Recognizing that trend-following often yields win rates of $35\%$ to $45\%$, but makes up for it with large average win sizes (asymmetric returns).

### Contrarian Concepts
*   **Fading Extremes:** Entering mean-reversion trades only when price stretches beyond standard deviation bands (e.g., Bollinger Bands or historical analog extremes).
*   **Predefined Invalidation:** Mean-reversion entries must have tight stops, as fading a strong trend carries high tail risk.

### Failure Recovery & Drawdown Management Methods
*   **The Sizing Step-Down:** Scaling down trade size by $50\%$ to $80\%$ when portfolio drawdown reaches a threshold.
*   **The Stand-Aside Protocol:** Transitioning to `NO_TRADE` or `READ_ONLY` mode when consecutive losses exceed a threshold, allowing the system to rest until the market regime stabilizes.

### Opportunity Selection & Portfolio Construction
*   **Selection Quality:** Filtering out mediocre trades. Only setups with conviction scores $\ge 75$ are permitted.
*   **Diversification Guard:** Restricting symbol concentration to avoid systemic sector correlations.

---

## 3. Hokage Integration Mapping

This table maps the *Market Wizards* doctrines to Hokage's software modules.

| Ingested Philosophy | Target Engine / Class | File Location | System Affected |
| :--- | :--- | :--- | :--- |
| **Preserve Capital First** | `CapitalPreservationEngine`| `src/bots/autonomous/capital_preservation.py`| Capital Preservation |
| **Cut Losses Fast** | `RiskBot` / `RiskRules` | `src/bots/risk/risk_bot.py` | Risk |
| **Let Winners Run** | `RiskBot` / `RiskRules` | `src/bots/risk/rules.py` | Position Management |
| **Size by Conviction** | `PositionAllocationEngine` | `src/bots/autonomous/portfolio_intelligence.py`| Allocation |
| **Avoid Emotional Trades**| `NoTradeDecisionEngine` | `src/bots/autonomous/conviction.py` | Conviction |
| **Asymmetric Opportunities**| `NoTradeDecisionEngine` | `src/bots/autonomous/conviction.py` | Conviction |
| **Adapt to Regimes** | `PortfolioManagerPersonalityLayer` | `src/bots/autonomous/personality_engine.py` | Allocation |
| **Compounding / Sizing** | `ElderTrustEngine` | `src/bots/autonomous/trust_engine.py` | Allocation |

---

## 4. Machine-Readable Schema (Draft)

```json
{
  "module_id": "market_wizards",
  "doctrines": [
    {
      "id": "MW_DOC_001",
      "name": "Preserve Capital First",
      "trigger_condition": "daily_drawdown_pct >= 2.0 OR total_drawdown_pct >= 10.0",
      "expected_action": "Set system state to NO_TRADE; reject all new orders; lock sizing at zero.",
      "success_metric": "Absolute capital drawdowns capped below 10% target limit"
    },
    {
      "id": "MW_DOC_002",
      "name": "Cut Losses Fast",
      "trigger_condition": "current_price <= stop_loss_price",
      "expected_action": "Trigger immediate market order exit; block discretionary cancellations.",
      "success_metric": "Zero stop-loss cancellations or stop widening events"
    }
  ]
}
```
