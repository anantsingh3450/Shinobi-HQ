# Hokage Common Stocks and Uncommon Profits Playbook
## Qualitative Ingestion of Philip A. Fisher's Research Doctrines

This playbook distills the qualitative business-analysis models, the Scuttlebutt ecosystem inquiry method, and the "15 Points of Stock Selection" from Philip A. Fisher's *Common Stocks and Uncommon Profits* into structural specifications for Hokage.

Rather than summarizing the book, this playbook establishes qualitative gates, labor/management relations audits, R&D efficacy metrics, and dilution controls designed to separate temporary operational setbacks from permanent structural declines.

---

## 1. Research Doctrines

These eight doctrines represent the unified core inquiry and research philosophy of Philip Fisher, converted into programmatic assertions.

### [Doctrine 1] Talk To The Ecosystem (Scuttlebutt)
*   **Philosophy:** Real edge is found by gathering intelligence from a company's competitors, customers, suppliers, and former employees, rather than relying solely on official corporate filings.
*   **Hokage Ingestion:** Structured sentiment crawlers and database queries target external ecosystem indicators (customer review trends, supplier order bookings, competitor growth comparisons).

### [Doctrine 2] Verify Before Investing
*   **Philosophy:** Never assume a management story is true without cross-referencing it against ecosystem realities.
*   **Hokage Ingestion:** Qualitative statements are cross-checked against hard financial results (operating margins, cost analysis controls) before scoring conviction.

### [Doctrine 3] Management Matters
*   **Philosophy:** The capabilities, integrity, and depth of a company's management determine its long-term viability. Look for depth in executive talent and outstanding labor relations.
*   **Hokage Ingestion:** Enforces a qualitative management depth gate, tracking executive retention metrics in the `ResearchIntelligenceEngine`.

### [Doctrine 4] Great Businesses Create Optionality
*   **Philosophy:** Dominant businesses continuously seed future growth by developing new products and expanding their addressable markets.
*   **Hokage Ingestion:** Innovation assessment checks reward companies that maintain high R&D efficacy relative to sales.

### [Doctrine 5] Growth Must Be Sustainable
*   **Philosophy:** Avoid short-term spikes in revenue. Growth must be sustainable, backed by an above-average sales organization and cost controls.
*   **Hokage Ingestion:** The `EODLearningLoop` validates consistency in long-range profit outlook metrics.

### [Doctrine 6] Innovation Creates Longevity
*   **Philosophy:** A company that does not innovate eventually dies. Effective R&D is the engine of compounding.
*   **Hokage Ingestion:** The system tracks research and development expense-to-sales ratios, prioritizing high-efficiency product developers.

### [Doctrine 7] Competitive Advantage Must Be Durable
*   **Philosophy:** High margins attract competition. Look for durable competitive barriers, such as proprietary tech, cost leadership, or strong brand affinity.
*   **Hokage Ingestion:** Evaluates structural margin durability across a rolling multi-year window.

### [Doctrine 8] Research Is A Continuous Process
*   **Philosophy:** Stock analysis does not end at purchase. Continuous monitoring is required to verify that the core thesis remains valid.
*   **Hokage Ingestion:** Mapped to the EOD checks, updating active `TradeDNA` and analog patterns dynamically.

---

## 2. Playbook Sections

### Core Principles
1.  **Indefinite Compounding:** Fisher's rule: "If the job has been correctly done when a common stock is purchased, the time to sell it is almost never."
2.  **15 Points Framework:** A 15-point qualitative checklist screening products, sales, R&D, margins, labor, cost accounting, and integrity.
3.  **Temporary Setbacks as Bargains:** Purchasing high-quality compounders when temporary operational difficulties depress the price.

### The Scuttlebutt Method
A systematic process for investigating a business from the outside:
*   *Competitor Interviews:* What does the competition fear most about the target?
*   *Customer Feedback:* Why do customers choose this product over alternatives?
*   *Supplier Insights:* Are orders expanding, stable, or contracting?
*   *Employee Relations:* Is employee turnover low, and is there a deep bench of executive talent?

### Business Quality & Competitive Advantage Frameworks
*   **R&D Efficiency:**
    $$\text{R&D Efficiency} = \frac{\text{New Product Sales}}{\text{Cumulative R&D Spend}}$$
*   **Margin Durability:** Track if a company can maintain above-average profit margins during industry downturns.
*   **Dilution Guard:** Rejecting companies that frequently issue shares to fund operations, diluting long-term shareholder value.

### Investor Anti-Patterns
*   **Over-Diversification:** Holding too many stocks due to fear of individual company risk, which dilutes focus and overall returns.
*   **The PE Fallacy:** Buying a mediocre business simply because its PE looks cheap, while passing on a great business because its PE looks temporarily high.
*   **Focusing on Dividends First:** Prioritizing yield over compounding potential, often leading to low-growth trap investments.

---

## 3. Hokage Integration Mapping

This table maps the Fisher principles to Hokage's core subsystems.

| Qualitative Concept | Target Engine / Class | File Location | System Affected |
| :--- | :--- | :--- | :--- |
| **R&D & Sales Efficiency** | `ResearchIntelligenceEngine`| `src/bots/autonomous/research_intel.py`| Conviction |
| **Scuttlebutt Sentiment** | `ResearchIntelligenceEngine`| `src/bots/autonomous/research_intel.py`| Conviction |
| **Dilution Check** | `OpportunityDiscoveryEngine` | `src/bots/autonomous/discovery.py` | Conviction |
| **Over-diversification Guard**| `PositionAllocationEngine` | `src/bots/autonomous/portfolio_intelligence.py`| Allocation |
| **PE Misalignment Veto** | `NoTradeDecisionEngine` | `src/bots/autonomous/conviction.py` | Conviction |
| **Outlier DNA Tracking** | `TradeDnaEngine` | `src/bots/autonomous/trade_dna.py` | Conviction |
| **Continuous Review** | `EODLearningLoop` | `src/bots/autonomous/learning.py` | Position Management |
| **Doctrines Search** | `KnowledgeManager` | `src/bots/autonomous/knowledge.py` | Conviction |

---

## 4. Machine-Readable Schema (Draft)

```json
{
  "module_id": "common_stocks_and_uncommon_profits",
  "doctrines": [
    {
      "id": "FI_DOC_001",
      "name": "Dilution Guard",
      "trigger_condition": "annual_share_increase_pct >= 3.0",
      "expected_action": "Trigger absolute VETO; flag symbol in OpportunityDiscoveryEngine as capital diluter.",
      "success_metric": "Capital allocation scores protected from shareholder dilution"
    },
    {
      "id": "FI_DOC_002",
      "name": "Margin Durability Check",
      "trigger_condition": "net_margin_change_pct < -10.0 AND industry_margin_change_pct >= -5.0",
      "expected_action": "Apply conviction score reduction (-15 points); notify EOD Learning Loop of structural margin decay.",
      "success_metric": "Early exits from structurally declining margin bases"
    }
  ]
}
```
