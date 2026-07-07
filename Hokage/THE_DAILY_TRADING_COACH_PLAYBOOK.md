# Hokage The Daily Trading Coach Playbook
## Algorithmic Ingestion of Brett N. Steenbarger's Self-Coaching Frameworks

This playbook translates the core self-coaching principles, cognitive-behavioral techniques, deliberate practice methodologies, and continuous improvement loops from Brett N. Steenbarger's *The Daily Trading Coach* into structured specifications for Hokage.

The objective of this document is to establish a rigorous framework for performance tracking, post-exit quality audits, and regime-based learning loops. This turns Hokage into a self-monitoring system that tracks its own execution compliance, identifies performance degradation, and recommends structural adjustments.

---

## 1. Principles

The following core principles represent the foundational self-coaching tenets, structured for systemic implementation.

### [Principle 1] The Self-Coaching Split (Observer vs. Executer)
*   **Description:** A trader must separate their active, executing self from an objective, monitoring observer self to evaluate behavior without bias.
*   **Hokage Ingestion:** This split is mapped directly into Hokage's architecture: Layer 1 (Fast Execution) acts as the executer, while Layer 2 (Deep Intelligence, Position Review, and Performance Analytics) acts as the objective observer/coach.
*   **Logical Formulation:**
    $$\text{Audit}(\text{Layer}_1 \text{ Action}) = \text{Layer}_2 \text{ Quality Score} \quad \text{where} \quad \text{Layer}_2 \cap \text{Execution State} = \emptyset$$

### [Principle 2] Process Over Outcome
*   **Description:** Long-term success is determined by the quality of execution and rule compliance, not by the PnL of individual trades.
*   **Hokage Ingestion:** The system evaluates itself based on its **Execution Quality Grade** (entry, sizing, stop, and exit efficiency) rather than raw PnL. A trade that loses money but complies perfectly with risk rules receives a higher coaching grade than a trade that violates rules but ends up profitable by chance.

### [Principle 3] Cognitive Restructuring (Negative Schema Mitigation)
*   **Description:** Identifying automatic negative thoughts and replacing them with objective, rational reframing statements.
*   **Hokage Ingestion:** When the system encounters execution drag or a series of vetoes, it logs the root cause in the `NoTradeDecisionEngine` and reviews it against the active regime. It prevents the system from entering a "paralysis by analysis" state by recalibrating conviction based on historical edge maps.

### [Principle 4] Solution-Focused Exception Analysis
*   **Description:** Focusing coaching energy on identifying and magnifying what works (success patterns) rather than only analyzing failures.
*   **Hokage Ingestion:** The system uses the `TradeDNAEngine` to group wins. By identifying the common parameters (regime, sector, ATR volatility, analog score) of successful trades, it feeds positive setups back into the `StrategyBot` for optimization.

---

## 2. Mental Models

These cognitive frameworks govern how Hokage analyzes performance anomalies and structures feedback loops.

### [Model 1] The Behavioral Loop (CBT Model)
```
       [ Trigger / Stimulus ] (Market Volatility / Drawdown)
                 │
                 ▼
       [ Cognitive Schema ] (Hokage Trust Score Calibrator)
                 │
                 ▼
       [ Emotional Reaction ] (Sizing Decelerator / Mode Toggle)
                 │
                 ▼
      [ Behavioral Output ] (Order Placement / Veto Action)
```
*   **Systemic Action:** By intercepting the *Cognitive Schema* layer, the `ElderTrustEngine` scales position sizes programmatically, bypassing emotional hesitation.

### [Model 2] The Solution-Focused "Exception" Framework
*   **Framework:** Isolating historical outliers where performance exceeded benchmarks to extract replication rules.
*   **Systemic Action:** When `PerformanceAnalyticsEngine` detects a win rate $> 70\%$ in a specific sector/regime block, it triggers a `SaveSetupException` call in the EOD Learning Loop, locking the parameters of that specific market DNA.

### [Model 3] The Performance Zone Split (Peak vs. Panic)
*   **Framework:** Categorizing execution states into Peak Performance (high trust, high compliance), Average Performance (medium trust, standard compliance), and Panic/Tilt Performance (high drawdown, erratic patterns).
*   **Systemic Action:** This is mapped to the `PortfolioManagerPersonalityLayer` modes:
    *   *Peak Performance:* `AGGRESSIVE` / `BALANCED` modes.
    *   *Panic/Tilt Prevention:* `DEFENSIVE` / `RECOVERY` modes.

---

## 3. Coaching Frameworks & Deliberate Practice

These frameworks guide the daily preparation, execution reviews, and pattern training systems.

### [Framework 1] Daily Briefing and Debriefing Structure
*   **Daily Briefing:** Executes pre-market to scan market regime parameters, check capital preservation state, calculate ATR volatility, and set max exposure ceilings.
*   **Daily Debriefing:** Executes post-session to calculate daily PnL, verify rule compliance, identify any slippage variances, and run Layer 2 analytics updates.

### [Framework 2] Deliberate Practice: Mental Rehearsal
*   **Framework:** Simulating high-stress scenarios (e.g., severe slippage, consecutive stop hits, sudden gap downs) to build execution resilience.
*   **Systemic Action:** Runs automated backtest stress-tests on historical analog vectors with simulated order delays and increased venue fee configurations.

### [Framework 3] Self-Review & Quality Grading
*   **Systemic Action:** Executed by `PositionReviewEngine` post-exit. Calculates four quality scores (0-100 scale):
    *   *Entry Quality:* Slippage between signal trigger price and executed price.
    *   *Sizing Quality:* Match between allocation sizer guidelines and executed quantity.
    *   *Stop Quality:* Adherence to predefined invalidation level without stop modifications.
    *   *Exit Quality:* Percentage of the maximum available move captured before trend reversal.

---

## 4. Emotional Regulation & Habit Systems

Translating psychological self-regulation mechanisms into automated system safeguards.

### [System 1] Physiological Regulation: The Autonomic Cooldown
*   **Concept:** Controlling heart rate variability and breathing under stress.
*   **Hokage Ingestion (The Cooldown Timer):** Triggered after $N$ consecutive losses. The system enters a cooling-off lock state, preventing new orders for a minimum of 60 minutes. This replicates a trader walking away from the desk to reset their physical state.

### [System 2] Systematic Desensitization: Risk Laddering
*   **Concept:** Gradually exposing oneself to stress-inducing size increases.
*   **Hokage Ingestion:** The `ElderTrustEngine` scales sizing up *gradually* (e.g., incrementing the risk multiplier by 0.1 per block of 5 successful trades) but scales down *rapidly* (e.g., dropping the risk multiplier by 0.5 upon a preservation gate breach).

### [System 3] Habit Anchor Systems
*   **Concept:** Linking new behavioral actions to existing triggers.
*   **Hokage Ingestion:** Every order trigger event is hardcoded to force a `RecordDecision` journal entry. Execution is physically impossible without passing through the audit trail gate.

---

## 5. Performance Metrics & Failure Modes

These analytical dimensions track system performance and trigger corrective processes.

### Performance Metrics
1.  **Compliance Score ($CS$):** Percentage of trades executed without a single gate veto or manual adjustment.
    $$CS = \frac{\text{Compliant Trades}}{\text{Total Executed Trades}} \times 100$$
2.  **Expectancy per Trade ($Ex$):** Expectation of net profit over time.
    $$Ex = (WR \times AvgWin) - ((1 - WR) \times AvgLoss)$$
3.  **Profit Factor ($PF$):** Ratio of gross profits to gross losses.
4.  **Max Peak-to-Trough Drawdown ($DD$):** Depth of capital decay.
5.  **Average Slip ($AS$):** Latency and execution drag.

### Common Failure Modes & Anti-Patterns
*   **Anti-Pattern 1: Boredom Overtrading (Seeking Stimulus)**
    *   *Detection:* Increased trade frequency during low-volatility regimes or sideways markets.
    *   *Mitigation:* `NoTradeDecisionEngine` enforces higher conviction thresholds during bracketed or low-ATR regimes.
*   **Anti-Pattern 2: The Bracket Drift (Failing to Adapt)**
    *   *Detection:* Trend-following strategies executing repeatedly in sideways channels.
    *   *Mitigation:* `MarketScanner` regime updates switch personality mode to `DEFENSIVE` when ADX < 20.
*   **Anti-Pattern 3: Profit Protection (Anxiety Exits)**
    *   *Detection:* Exiting positions manually before the take-profit target is reached, with no technical trigger.
    *   *Mitigation:* `RiskBot` blocks discretionary exit requests unless backed by indicator criteria (e.g., trailing stop breach).

---

## 6. Corrective Processes & Continuous Improvement Loops

How Hokage repairs and optimizes its systems dynamically.

```
       [ EOD Review ] ──> [ Calculate Execution Compliance ]
             │
             ├──> [ Check: Drawdown > Threshold? ]
             │         ├── YES ──> [ Scale Sizing Down / Trigger Cooldown ]
             │         └── NO  ──> [ Maintain / Increment Sizing Scale ]
             │
             └──> [ Log Outliers & Exception Trades into TradeDNA ]
```

### [Loop 1] The EOD Learning Loop
*   **Task:** Runs at close of session. Loads `decision_journal.jsonl`, calculates win rates and slippage profiles, compiles new `TradeDNA` fingerprints, and saves regime metrics.

### [Loop 2] The Solution-Focused Recovery Protocol
*   **Task:** Triggered when the bot is in `RECOVERY` mode. Sizing scales down to $20\%$ of baseline. Sizing increases are only permitted after a block of 10 consecutive trades with an average Execution Quality Grade $\ge 85$, regardless of profitability.

---

## 7. Machine-Readable Mappings

This database structures the Steenbarger rules for ingestion by the `KnowledgeManager`.

```json
[
  {
    "principle_id": "ST_PR_001",
    "name": "Process Over Outcome",
    "trigger_condition": "post_trade_review_trigger",
    "expected_action": "Calculate ExecutionQualityGrade; log in DecisionJournal; flag trades with grade < 80 for review.",
    "success_metric": "Average execution compliance score >= 90%"
  },
  {
    "principle_id": "ST_PR_002",
    "name": "Autonomic Cooldown",
    "trigger_condition": "consecutive_losses_count >= 3",
    "expected_action": "Scale down risk_multiplier; set bot state to COOLDOWN; reject entries for 60 minutes.",
    "success_metric": "Prevention of revenge trades during stress periods"
  },
  {
    "principle_id": "ST_PR_003",
    "name": "Exception Reinforcement",
    "trigger_condition": "win_rate_sector_regime >= 75%",
    "expected_action": "Record TradeDNA fingerprint; tag setup as EXCEPTION_SETUP; output positive bias weights to strategy engine.",
    "success_metric": "Incremental increase in strategy expectancy"
  }
]
```

---

## 8. Hokage Integration Mapping

This table details the integration interface between the Steenbarger self-coaching models and Hokage's active sub-systems.

| Self-Coaching Concept | Hokage Subsystem | File Target | System Affected |
| :--- | :--- | :--- | :--- |
| **Daily Briefing & Debriefing** | `BriefingGenerator` | `src/bots/autonomous/briefings.py` | Position Management, Capital Preservation |
| **Self-Review & Quality Grading**| `PositionReviewEngine`| `src/bots/autonomous/position_review.py`| Performance Analytics |
| **Exception Setup Recording** | `TradeDnaEngine` | `src/bots/autonomous/trade_dna.py` | Conviction |
| **Compliance & Slip Tracking** | `PerformanceAnalytics`| `src/bots/autonomous/performance_analytics.py`| Position Management, Capital Preservation |
| **EOD Parameter Refinements** | `EODLearningLoop` | `src/bots/autonomous/learning.py` | Conviction, Allocation |
| **Rules Ingestion & Retrieval** | `KnowledgeManager` | `src/bots/autonomous/knowledge.py` | Conviction |
| **Cooldown Enforcements** | `CapitalPreservation`| `src/bots/autonomous/capital_preservation.py`| Capital Preservation, Allocation |
