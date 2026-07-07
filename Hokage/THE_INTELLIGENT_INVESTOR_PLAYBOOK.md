# Hokage The Intelligent Investor Playbook
## Algorithmic Ingestion of Benjamin Graham's Value Investing Doctrines

This playbook distills the core value investing principles, risk frameworks, and quantitative asset screening models from Benjamin Graham's *The Intelligent Investor* into structured specifications for Hokage.

Rather than summarizing the book, this document establishes the mathematical rules, balance sheet screens, and valuation margins designed to implement Graham's Margin of Safety doctrine and distinguish speculative price fluctuations from fundamental business value.

---

## 1. Investor Doctrines

These eight doctrines represent the unified value investing philosophy of Benjamin Graham, converted into programmatic assertions.

### [Doctrine 1] Investment vs. Speculation
*   **Philosophy:** An investment operation is one which, upon thorough analysis, promises safety of principal and an adequate return. Operations not meeting these requirements are speculative.
*   **Hokage Ingestion:** The system restricts speculative allocations (e.g. high-beta, no-history instruments) to a separate "Mad Money" sub-portfolio capped at a maximum of $10\%$ of total equity. Speculative cash flows are never mingled with core portfolio cash.

### [Doctrine 2] Margin of Safety
*   **Philosophy:** The difference between the intrinsic value of a company and the price paid to purchase it. The larger the margin, the greater the buffer against inaccurate forecasts and market adversity.
*   **Hokage Ingestion:** Capital is allocated only if:
    $$\text{Executed Price} \le \text{Intrinsic Value} \times (1 - \text{Required Margin of Safety})$$
    where the baseline Margin of Safety is set to $33.3\%$ (a one-third discount to intrinsic value).

### [Doctrine 3] Mr. Market as an Obliging Partner
*   **Philosophy:** The stock market fluctuates wildly, presenting irrational buy/sell prices daily. The investor ignores Mr. Market's mood swings and capitalizes on them only when prices are ridiculously high (to sell) or low (to buy).
*   **Hokage Ingestion:** `RiskBot` ignores daily price fluctuations unless price reaches predefined entry target or trailing exit zones, avoiding panic exits during unjustified market declines.

### [Doctrine 4] Risk vs. Price Distinction
*   **Philosophy:** A stock is not inherently risky because its price is declining; in fact, the risk of a high-quality stock *decreases* as its price falls, while its margin of safety *increases*.
*   **Hokage Ingestion:** The `NoTradeDecisionEngine` prevents marking an asset as "high risk" solely due to downward price momentum, provided fundamental balance sheet metrics remain sound.

### [Doctrine 5] The Defensive Investor Asset Allocation
*   **Philosophy:** A passive investor should maintain a simple, balanced portfolio split between high-grade bonds and high-grade stocks, adjusting the ratio dynamically between $25\%$ and $75\%$ based on market extremes.
*   **Hokage Ingestion:** The standard allocation defaults to $50\text{-}50$. Sizing scales stocks up to $75\%$ during bear markets (high bargains) and down to $25\%$ during bull market extremes.

### [Doctrine 6] Earnings Capacity and Appraisal
*   **Philosophy:** Intrinsic value is estimated by projecting average earning capacity over the next 5 years, adjusted for capitalization shifts and asset values, using conservative multipliers.
*   **Hokage Ingestion:** Calculations restrict multiplier limits to a maximum of 20 and a minimum of 8.

### [Doctrine 7] Diversification as a Safety Multiplier
*   **Philosophy:** Individual stock selection is imperfect. Diversification is necessary to amplify the safety margins across a basket of assets.
*   **Hokage Ingestion:** Maximum portfolio exposure to a single stock is capped at $5\%$ of total equity.

### [Doctrine 8] Business-Like Investing
*   **Philosophy:** Investing is most intelligent when it is most business-like. When buying a stock, the investor becomes a partial owner of the underlying business, not a participant in a price-betting game.
*   **Hokage Ingestion:** Outlines that every trade logged in the `DecisionJournalSystem` must document the core business earnings stability and balance sheet strength.

---

## 2. Playbook Sections

### The Mr. Market Framework
*   *Concept:* The market is a daily partner proposing prices.
*   *Hokage Translation:* Price is an input, not a guide. The system calculates intrinsic value independently using historical earnings stability and balance sheet assets, ignoring temporary sentiment variables.

### The Margin of Safety Doctrine
*   *Formula:*
    $$\text{Margin of Safety (\%)} = \left( 1 - \frac{\text{Market Price}}{\text{Intrinsic Value}} \right) \times 100$$
*   *Rule:* A larger margin of safety is required for companies with higher earnings volatility.

### Stock Selection: The Defensive Investor
Hokage implements Graham's 7-point defensive screen:
1.  **Adequate Size:** Exclude small, volatile micro-caps.
2.  **Strong Financial Condition:** Current assets must be at least twice current liabilities ($CurrentRatio \ge 2.0$). Long-term debt must not exceed net current assets (working capital).
3.  **Earnings Stability:** Positive earnings (no deficits) for each of the past 10 years.
4.  **Dividend Record:** Uninterrupted dividend payments for the past 20 years.
5.  **Earnings Growth:** A minimum increase of at least one-third ($33.3\%$) in EPS over the past 10 years, using 3-year averages at the beginning and end.
6.  **Moderate PE Ratio:** Price-to-earnings ratio must not exceed 15 times the average earnings of the past 3 years.
7.  **Moderate PB Ratio:** Price-to-book ratio must not exceed 1.5.
    *   *Graham Multiplier Rule:*
        $$\text{PE Ratio} \times \text{PB Ratio} \le 22.5$$
        A low PE ratio (below 15) can justify a higher PB ratio (above 1.5), provided their product does not exceed $22.5$.

### Stock Selection: The Enterprising Investor
Hokage implements Graham's 5-point enterprising screen:
1.  **Financial Condition:**
    *   Current assets $\ge 1.5 \times$ current liabilities.
    *   Long-term debt $\le 110\%$ of net current assets.
2.  **Earnings Stability:** No earnings deficits (losses) in the last 5 years.
3.  **Dividend Record:** Some current dividend payout.
4.  **Earnings Growth:** Consistent earnings growth (positive slope over the past 5 years).
5.  **Moderate Price:** Purchase price must be less than $120\%$ of net tangible assets.

---

## 3. Hokage Integration Mapping

This table maps the Graham philosophies to Hokage's core subsystems.

| Value Investing Concept | Target Subsystem / Class | File Location | System Affected |
| :--- | :--- | :--- | :--- |
| **PEG / Multiplier Screens** | `ResearchIntelligenceEngine`| `src/bots/autonomous/research_intel.py`| Conviction |
| **Graham 22.5 Multiplier** | `ResearchIntelligenceEngine`| `src/bots/autonomous/research_intel.py`| Conviction |
| **Asset vs. Earning Valuation**| `ResearchIntelligenceEngine`| `src/bots/autonomous/research_intel.py`| Conviction |
| **Speculative Sub-Portfolio** | `PositionAllocationEngine` | `src/bots/autonomous/portfolio_intelligence.py`| Allocation |
| **50-50 Bond/Stock Scaling** | `PositionAllocationEngine` | `src/bots/autonomous/portfolio_intelligence.py`| Allocation |
| **Margin of Safety Limits** | `NoTradeDecisionEngine` | `src/bots/autonomous/conviction.py` | Conviction |
| **Speculation Veto Gate** | `NoTradeDecisionEngine` | `src/bots/autonomous/conviction.py` | Conviction |
| **Risk vs Price Invariant** | `RiskBot` / `RiskRules` | `src/bots/risk/rules.py` | Risk |
| **Doctrines Search** | `KnowledgeManager` | `src/bots/autonomous/knowledge.py` | Conviction |

---

## 4. Machine-Readable Schema (Draft)

```json
{
  "module_id": "the_intelligent_investor",
  "doctrines": [
    {
      "id": "GR_DOC_001",
      "name": "Margin of Safety Gate",
      "trigger_condition": "market_price > intrinsic_value * 0.667",
      "expected_action": "Trigger absolute VETO; reject purchase if the asset does not offer a 33.3% margin of safety.",
      "success_metric": "Protection of capital base during market corrections"
    },
    {
      "id": "GR_DOC_002",
      "name": "Graham Multiplier Screen",
      "trigger_condition": "pe_ratio * pb_ratio > 22.5",
      "expected_action": "Trigger absolute VETO; reject valuation for defensive investor profile.",
      "success_metric": "Capping defensive portfolio exposure to high-valuation assets"
    }
  ]
}
```
