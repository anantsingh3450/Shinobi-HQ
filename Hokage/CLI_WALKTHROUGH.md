# Hokage CLI Command Walkthrough — Phase 5A.2

This document provides a comprehensive command walkthrough and user guide for interacting with **Hokage** using the read-only Command Interface.

---

## 1. Safety & Guarantees
*   **Strict Read-Only Mode**: None of the command router commands can place orders, modify configuration states, or override risk rules.
*   **INR Currency Conformity**: All monetary metrics are formatted using the Indian Rupee symbol prefix (`₹`).
*   **Decoupled Intelligence Caches**: Commands query local JSON and JSONL ledger databases (`account_paper.json`, `decision_journal.jsonl`, `decision_outcomes.jsonl`, `trade_performance_history.jsonl`, `position_reviews.jsonl`, `trade_dna.jsonl`, `morning_briefing.json`, and `knowledge_registry.json`) directly without activating live API requests.

---

## 2. Command Index

The CLI supports the following 14 commands:

| Command | Description | Source Files / Caches |
| :--- | :--- | :--- |
| `hokage status` | Prints operational variables, trust score, and capital preservation mode. | `account_paper.json`, `decision_journal.jsonl` |
| `hokage portfolio` | Renders a summary of initial capital, current cash, realized/unrealized P&L, and equity. | `account_paper.json` |
| `hokage positions` | Formats all active open positions in an aligned table. | `account_paper.json` |
| `hokage decisions today` | Lists accepted/rejected trade decisions today. | `decision_journal.jsonl` |
| `hokage why <symbol>` | Audits the 7-gate reasoning chain for the latest decision of a ticker. | `decision_journal.jsonl` |
| `hokage performance` | Calculates Sharpe ratio, profit factor, expectancy, max drawdown, and holding times. | `trade_performance_history.jsonl` |
| `hokage lessons` | Outputs recent post-exit quality reviews and lessons. | `position_reviews.jsonl` |
| `hokage dna` | Breaks down win/loss metrics by conviction, sector, and market regime. | `trade_dna.jsonl` |
| `hokage briefing` | Renders the latest generated morning briefing markdown. | `morning_briefing.json` |
| `hokage review` | Outputs a pre-populated Markdown EOD daily review template. | `account_paper.json`, `decision_journal.jsonl` |
| `hokage knowledge <topic>` | Searches the institutional playbook registry for specific concepts. | `knowledge_registry.json` |
| `hokage chat "<query>"` | Queries Hokage naturally using the natural language explainability engine. | `CommanderConversationEngine` |
| `hokage voice-status` | Displays the status of the Voice Commander session. | CLI Static State |
| `hokage doctor` | Runs comprehensive system health, performance, and security diagnostics. | `HokageDoctor` |

---

## 3. Command Usage & Examples

### 1. `hokage status`
Displays the active execution mode, autonomous scan status, active venue, trust scores, and current portfolio balances.
*   **Command**: `python -m src.hokage.main status` (or `hokage status` via shell wrapper)
*   **Output Example**:
    ```text
    === Hokage System Status ===
    Execution Mode:             READ_ONLY
    Autonomous Loop:            INACTIVE
    Active Venue:               paper_main
    Capital Preservation State: NORMAL
    Elder Trust Score:          95/100 (Grade: A)
    Portfolio Health:           90/100 (Grade: STRONG)
    Paper Account Balance:      ₹500,000.00
    Current Cash:               ₹490,000.00
    Open Positions:             1
    ============================
    ```

### 2. `hokage portfolio`
Renders a clear summary of capital allocations and current gains/losses.
*   **Command**: `python -m src.hokage.main portfolio`
*   **Output Example**:
    ```text
    === Hokage Paper Portfolio ===
    Account ID:         paper
    Initial Balance:    ₹500,000.00
    Current Cash:       ₹490,000.00
    Realized P&L:       ₹500.00
    Unrealized P&L:     ₹1,000.00
    Total Equity:       ₹521,000.00
    Open Positions:     1
    ==============================
    ```

### 3. `hokage positions`
Lists open paper positions with entry prices, current prices, and unrealized returns.
*   **Command**: `python -m src.hokage.main positions`
*   **Output Example**:
    ```text
    === Hokage Open Positions ===
    Symbol      Direction  Quantity  Entry Price   Current Price  Unrealized P&L  Opened At
    -------------------------------------------------------------------------------------------------
    TCS         LONG       10.00     ₹3,000.00     ₹3,100.00      ₹1,000.00       2026-06-23 12:00:00
    =============================
    ```

### 4. `hokage decisions today`
Lists the strategy scanner's decisions (accepted or rejected) for today.
*   **Command**: `python -m src.hokage.main decisions today`
*   **Output Example**:
    ```text
    === Hokage Decisions Today (2026-06-23) ===
    [12:00:00] TCS | ACCEPTED | Conviction: 86 (ELITE)
               Reason: Authorized deployment of 2% capital.
    [12:05:00] INFY | REJECTED | Conviction: 40 (WATCH)
               Veto Gate: RiskBot | Reason: Exceeded maximum position size.
    ```

### 5. `hokage why <symbol>`
Traces the 7-gate Investment Committee chain audit trail for the selected symbol's last scanned decision.
*   **Command**: `python -m src.hokage.main why TCS`
*   **Output Example**:
    ```text
    === Hokage Decision Audit: TCS ===
    Timestamp:       2026-06-23 12:00:00
    Decision:        ACCEPTED
    Conviction:      86 (ELITE)
    Summary Reason:  Authorized deployment of 2% capital.

    Reasoning Chain Audit Trail (7-Gate Analysis):
      1. Gate: CapitalPreservation -> Verdict: NORMAL
         Reason: Safe conditions
      2. Gate: PortfolioHealth -> Verdict: STRONG
         Reason: No drawdown
      3. Gate: ConvictionScore -> Verdict: 86
         Reason: High score
      4. Gate: ConfidenceCalibration -> Verdict: 86
         Reason: Calibrated
      5. Gate: NoTradeDecisionEngine -> Verdict: BUY
         Reason: Trade approved
      6. Gate: PositionAllocation -> Verdict: 2.00%
         Reason: Allocated
      7. Gate: RiskBot -> Verdict: APPROVED
         Reason: Risk checks passed
      8. Gate: Execute -> Verdict: ACCEPTED
         Reason: Executed trade
    ```

### 6. `hokage performance`
Displays core trading performance stats calculated from closed trades history.
*   **Command**: `python -m src.hokage.main performance`
*   **Output Example**:
    ```text
    === Hokage Trading Performance ===
    Total Trades:    1
    Win Rate:        100.00% (1 Wins, 0 Losses)
    Profit Factor:   1.0
    Expectancy:      ₹1,000.00
    Sharpe Ratio:    0.0

    Drawdown Metrics:
      - Max Drawdown (%):   0.00%
      - Max Drawdown (INR): ₹0.00
      - Worst Session PnL:  ₹1,000.00 (TCS)
      - Max Consecutive Losses: 0

    Holding Periods:
      - Avg Hold (All):     1.00 days
      - Avg Hold (Winners): 1.00 days
      - Avg Hold (Losers):  0.00 days
      ==============================
    ```

### 7. `hokage lessons`
Displays structured entry/exit reviews and learning takeaways compiled post-exit.
*   **Command**: `python -m src.hokage.main lessons`
*   **Output Example**:
    ```text
    === Hokage Lessons Learned (Recent) ===
    --------------------------------------------------------------------------------
    [2026-06-23] TCS (PnL: ₹1,000.00):
          Excellent R:R achieved: 2.0 — replicate strategy.
    --------------------------------------------------------------------------------
    ```

### 8. `hokage dna`
Shows fingerprints of historical successes and failures categorised by conviction level, sectors, and market environments.
*   **Command**: `python -m src.hokage.main dna`
*   **Output Example**:
    ```text
    === Hokage Trade DNA Analysis ===
    Total DNA Records: 1

    By Conviction Grade:
      - ELITE: 1 trades (1 Wins, 0 Losses, 0 Breakeven) | Win Rate: 100.00%

    By Market Regime:
      - BULL_RISK-ON: 15 trades (10 Wins, 5 Losses, 0 Breakeven) | Win Rate: 66.67%

    By Sector:
      - IT: 8 trades (6 Wins, 2 Losses, 0 Breakeven) | Win Rate: 75.00%
    ==============================
    ```

### 9. `hokage briefing`
Prints the most recent cached pre-market morning briefing.
*   **Command**: `python -m src.hokage.main briefing`

### 10. `hokage review`
Prints out a fully pre-populated Markdown EOD daily review template that the Commander can paste into his journaling system.
*   **Command**: `python -m src.hokage.main review`

### 11. `hokage knowledge <topic>`
Runs a case-insensitive search across the ingested trading playbooks for rules, doctrines, and psychological guideposts.
*   **Command**: `python -m src.hokage.main knowledge risk`
*   **Output Example**:
    ```text
    === Hokage Knowledge Search: "risk" ===

    --- Rules & Frameworks ---
    [trading_in_the_zone] [risk] Risk Acceptance Rule
      Description: Pre-define risk before every entry...
    ```

### 12. `hokage profile`
Prints the active Commander Profile settings.
*   **Command**: `python -m src.hokage.main profile`
*   **Output Example**:
    ```text
    === Hokage Commander Profile ===
    Commander:             Elder Anant
    Risk Mode:             DEFENSIVE
    Execution Mode:        PAPER
    Base Currency:         INR
    Preservation State:    ACTIVE
    Starting Capital:      ₹500,000.00
    Tax-Aware Routing:     True
    ```

### 13. `hokage horizon`
Prints the current horizon controls and progression details.
*   **Command**: `python -m src.hokage.main horizon`
*   **Output Example**:
    ```text
    === Hokage Horizon State ===
    Progression Phase:     ALPHA
    Active Horizon Mode:   FOCUSED
    Universe Size:         1
    Primary Asset:         CRUDE_OIL
    ```

### 14. `hokage universe`
Lists all asset symbols currently monitored under the active scan scope.
*   **Command**: `python -m src.hokage.main universe`
*   **Output Example**:
    ```text
    === Hokage Active Monitor Universe ===
    Phase:                 ALPHA
    Mode:                  FOCUSED
    Assets (1):
      - CRUDE_OIL
    ```

### 15. `hokage chat "<query>"`
Queries Hokage using natural language and retrieves an explanation derived from Hokage's specialized engines.
*   **Command**: `python -m src.hokage.main chat "Why did we reject INFY today?"`
*   **Output Example**:
    ```text
    Hokage: INFY was rejected today by RiskBot because it exceeded the maximum position size threshold.
    ```

### 16. `hokage voice-status`
Displays the current state and provider configuration of the Voice Commander session.
*   **Command**: `python -m src.hokage.main voice-status`
*   **Output Example**:
    ```text
    Voice Commander Session: INACTIVE | Wake Phrase: 'Hokage' | Provider: MockVoiceProvider
    ```

### 17. `hokage doctor`
Runs the system diagnostics suite, checking the environment, database, configuration, performance, and security.
*   **Command**: `python -m src.hokage.main doctor`
*   **Output Example**:
    ```text
    ==================================================
                  HOKAGE SYSTEM DOCTOR                
    ==================================================
    OVERALL HEALTH SCORE: 98.0/100 (EXCELLENT)
    
    --- 1. Environment ---
      Python Version:     3.14.6
      OS Platform:        Windows-10-10.0.22631-SP0
      Supported:          YES
    ...
    ```

---

## 4. Verification Check

To run CLI tests locally:
```bash
python -m pytest tests/unit/bots/autonomous/test_cli_commands.py
```
To run the full test suite and verify hygiene:
```bash
python -m pytest
python scripts/verify_hygiene.py
```
