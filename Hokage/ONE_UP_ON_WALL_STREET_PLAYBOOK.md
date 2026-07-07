# Hokage One Up On Wall Street Playbook
## Algorithmic Ingestion of Peter Lynch's Fundamental Selection Frameworks

This playbook translates the core growth investing principles, company classification methods, PEG-based valuation ratios, and balance sheet screening criteria from Peter Lynch's *One Up On Wall Street* into structured guidelines for Hokage.

Rather than summarizing the book, this document establishes the mathematical rules, classification templates, and balance sheet validation gates designed to identify high-quality growth businesses, screen out speculative "story stocks," and evaluate business strength objectively.

---

## 1. Investor Doctrines

These eight doctrines represent the unified core investing philosophy of Peter Lynch, converted into programmatic assertions.

### [Doctrine 1] Invest In What You Understand
*   **Philosophy:** Local consumer or professional knowledge is a competitive edge. Do not allocate capital to businesses whose product cycle, revenue model, or customer base is opaque.
*   **Hokage Ingestion:** Setups discovered in sectors where the system has zero historical analog matching or low model training scores are vetoed.

### [Doctrine 2] Simplicity Beats Complexity
*   **Philosophy:** A great business is one that any fool can run—because sooner or later, some fool will. Avoid complex conglomerates or businesses with convoluted financial structures.
*   **Hokage Ingestion:** Simple, clean earnings models with high operating margins are prioritized over complex balance sheets.

### [Doctrine 3] Great Businesses Compound
*   **Philosophy:** Long-term wealth is built by holding businesses that compound their earnings over years, allowing share price to track business value.
*   **Hokage Ingestion:** The `EODLearningLoop` tags companies with consistent year-on-year earnings growth as primary compounders.

### [Doctrine 4] Growth Must Be Supported By Fundamentals
*   **Philosophy:** Price increases without earnings expansion are speculative. PE expansion must be justified by revenue and margin improvements.
*   **Hokage Ingestion:** Avoids companies where price growth outpaces earnings growth, keeping the PEG ratio within bounds.

### [Doctrine 5] Avoid Story Stocks
*   **Philosophy:** Avoid "the next big thing" or hot stocks with high promises but zero actual revenues or earnings.
*   **Hokage Ingestion:** The `NoTradeDecisionEngine` vetoes symbols where revenue $\le 0$ or operational cash flow is negative, regardless of social media sentiment.

### [Doctrine 6] Balance Opportunity With Financial Strength
*   **Philosophy:** A company with zero debt cannot go bankrupt. Growth is meaningless if the capital structure is fragile.
*   **Hokage Ingestion:** Balance sheet screening checks enforce strict debt-to-equity ratio limits.

### [Doctrine 7] Research Creates Edge
*   **Philosophy:** Doing basic fundamental scuttlebutt (checking inventory, visiting stores, talking to competitors) creates information asymmetry over institutional consensus.
*   **Hokage Ingestion:** Mapped to the `ResearchIntelligenceEngine` to pull data from diverse financial statements and sentiment caches.

### [Doctrine 8] Time Is A Competitive Advantage
*   **Philosophy:** Individual investors can ignore short-term quarterly noise. Holding a great business through volatility leads to outperformance.
*   **Hokage Ingestion:** Restricts execution churn. Long-term investment accounts bypass short-term stop-loss triggers that are based on macro noise, maintaining their focus on business health targets.

---

## 2. Playbook Sections

### Core Principles
1.  **Earnings-Price Tracking:** Over the long run, share price tracks earnings per share (EPS).
2.  **Size Matters:** It is mathematically easier for a \$100M company to grow tenfold than a \$10B company.
3.  **Wall Street Neglect:** Seek companies with low institutional ownership and zero analyst coverage.

### Company Classification System
Hokage implements Lynch's six-fold classification:
1.  **Fast Growers:** Small, aggressive new enterprises growing earnings by $20\%$ to $25\%$ annually.
2.  **Stalwarts:** Large, established companies growing earnings by $10\%$ to $12\%$ annually (e.g., steady cash flow, good defensive holds).
3.  **Slow Growers:** Mature companies growing slightly above GDP, usually offering high dividend yields.
4.  **Cyclicals:** Companies whose sales and profits rise and fall in regular, predictable patterns (autos, steel, chemical).
5.  **Turnarounds:** Battered companies undergoing restructuring. High risk, highly asymmetric returns.
6.  **Asset Plays:** Companies with overlooked assets (real estate, cash, patents) that exceed the current enterprise value.

### Financial Health & Valuation Frameworks
*   **The PEG Ratio (Price-to-Earnings-Growth):**
    $$PEG = \frac{PE}{\text{Earnings Growth Rate}}$$
    *   $PEG < 1.0$ indicates fair value.
    *   $PEG < 0.5$ indicates significant undervaluation.
    *   $PEG > 2.0$ indicates overvaluation.
*   **Net Cash Metric:** Adjusting the nominal share price for net cash on the balance sheet:
    $$\text{Adjusted Share Price} = \text{Current Price} - \left( \frac{\text{Cash} - \text{Total Debt}}{\text{Shares Outstanding}} \right)$$
*   **Inventory Red Flag:** Rising inventory percentage that outpaces sales growth is a primary warning of demand slowdown.

### Common Investor Mistakes
*   **The Breakeven Fallacy:** Holding a declining stock hoping to "get back to even" before selling.
*   **The Dollar Infallibility:** Thinking a stock that has fallen from \$50 to \$5 cannot fall any further.
*   **Premature Winner Pruning:** Selling winners early while holding onto losers ("watering the weeds and cutting the flowers").

---

## 3. Hokage Integration Mapping

This table maps the Lynch principles to Hokage's core subsystems.

| Fundamental Concept | Target Engine / Class | File Location | System Affected |
| :--- | :--- | :--- | :--- |
| **PEG Screen & Net Cash** | `ResearchIntelligenceEngine`| `src/bots/autonomous/research_intel.py`| Conviction |
| **Asset Play Discovery** | `OpportunityDiscoveryEngine` | `src/bots/autonomous/discovery.py` | Conviction |
| **Company Classification**| `ResearchIntelligenceEngine`| `src/bots/autonomous/research_intel.py`| Conviction |
| **Story Stock Veto** | `NoTradeDecisionEngine` | `src/bots/autonomous/conviction.py` | Conviction |
| **EOD Setup Verification** | `EODLearningLoop` | `src/bots/autonomous/learning.py` | Position Management |
| **Outlier Log Checks** | `TradeDnaEngine` | `src/bots/autonomous/trade_dna.py` | Conviction |
| **Compliance Tracking** | `PerformanceAnalytics` | `src/bots/autonomous/performance_analytics.py`| Capital Preservation |
| **Doctrines Search** | `KnowledgeManager` | `src/bots/autonomous/knowledge.py` | Conviction |

---

## 4. Machine-Readable Schema (Draft)

```json
{
  "module_id": "one_up_on_wall_street",
  "doctrines": [
    {
      "id": "LY_DOC_001",
      "name": "Avoid Story Stocks",
      "trigger_condition": "revenue <= 0 OR operating_cash_flow < 0",
      "expected_action": "Trigger absolute VETO; flag symbol in OpportunityDiscoveryEngine as speculative.",
      "success_metric": "Zero capital loss in speculative, non-revenue companies"
    },
    {
      "id": "LY_DOC_002",
      "name": "Simplicity Screen",
      "trigger_condition": "operating_margin >= 15.0 AND debt_to_equity <= 0.5",
      "expected_action": "Apply conviction score boost (+10 points); prioritize in portfolio allocation sizers.",
      "success_metric": "Outperformance of low-debt, high-margin asset baskets"
    }
  ]
}
```
