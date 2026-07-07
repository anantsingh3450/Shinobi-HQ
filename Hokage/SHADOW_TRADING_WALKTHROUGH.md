# Shadow Trading & Performance Validation Framework (Phase 6.5)

This document provides a comprehensive operational and technical walkthrough of the **Phase 6.5 — Shadow Trading & Performance Validation Framework** in Hokage. 

The primary objective of the Shadow Trading framework is to prove that Hokage can consistently outperform market benchmarks under real-world conditions prior to any live capital deployment, executing the exact same decision and risk pipelines as production, but routing orders exclusively through `PaperVenue`.

---

## 1. Architectural Architecture

The validation framework is designed with modular, single-responsibility engines located in the `src/bots/autonomous/` directory:

1. **`ShadowEngine`**: The central orchestrator that manages shadow session lifecycles, daily performance tracking, and archives immutable validation reports.
2. **`BenchmarkEngine`**: Tracks generic, asset-agnostic benchmark prices and returns, and calculates active returns (Alpha), Tracking Error (TE), and Information Ratio (IR).
3. **`AttributionEngine`**: Grades completed trade decisions and outcomes, categorizes trades into 4 quadrants, computes the **Shadow Reality Score**, and compiles the 9-Why Explainability Manifest.
4. **`CalibrationEngine`**: Evaluates confidence calibration curves (calibration error) and aligns expected vs actual metrics (win rates, holding periods, drawdowns, and reward/risk ratios).
5. **`PromotionEngine`**: Audits the **12 evidence-based readiness criteria**, determines the **5 Promotion Readiness Levels**, and validates environment exposure using the **Market Regime Coverage Matrix**.

---

## 2. Mathematical Formulations & Metrics

All statistics are hand-coded in pure Python using the standard `math` library for complete portability.

### 2.1 Active Return & Tracking Error
Active return (Alpha) on any day \(t\) is:
\[\alpha_t = R_{p, t} - R_{b, t}\]
where \(R_{p, t}\) is the daily portfolio return and \(R_{b, t}\) is the daily benchmark return.

Tracking Error is the sample standard deviation of active returns:
\[TE = \sqrt{\frac{1}{N-1} \sum_{t=1}^N (\alpha_t - \bar{\alpha})^2}\]

### 2.2 Information Ratio
The Information Ratio measures active risk-adjusted return:
\[IR = \frac{\bar{\alpha}}{TE}\]
Annualized: \(IR_{\text{ann}} = IR \times \sqrt{252}\)

### 2.3 Rolling Sortino Ratio
The Sortino ratio evaluates downside risk-adjusted returns:
\[Sortino = \frac{\bar{R}_p - R_f}{\sigma_{pd}}\]
where \(\sigma_{pd}\) is the downside semi-deviation, calculating variance exclusively on negative portfolio returns:
\[\sigma_{pd} = \sqrt{\frac{1}{N_d - 1} \sum_{R_{p,t} < 0} R_{p,t}^2}\]

### 2.4 Shadow Reality Score (0–100)
Measures decision quality independent of P&L to account for market randomness. Completed trades are classified into four quadrants:
1. **`CORRECT_DECISION_PROFITABLE`**: Favorable Expected Edge (\(EE \ge 1.0\)), trade was structurally sound (conviction \(\ge 60\)), resulting in a profit.
2. **`CORRECT_DECISION_LOSS`**: Favorable Expected Edge (\(EE \ge 1.0\)), trade was structurally sound (conviction \(\ge 60\)), but resulted in a loss due to normal market randomness.
3. **`INCORRECT_DECISION_PROFIT`**: Unfavorable Expected Edge (\(EE < 1.0\)) or poor structure (conviction < 60), resulting in a profit due to luck.
4. **`INCORRECT_DECISION_LOSS`**: Unfavorable Expected Edge or poor structure, resulting in a loss.

Metrics generated:
* **Decision Accuracy**: Percentage of Correct Decisions (Quadrants 1 + 2).
* **Luck Index**: Percentage of Lucky trades (Quadrant 3).
* **Edge Realization**: Ratio of realized edge to expected edge.
* **Reality Score (0–100)**:
  \[\text{Reality Score} = 0.50 \cdot \text{Decision Accuracy} + 0.30 \cdot \text{Edge Realization} + 0.20 \cdot (100 - \text{Luck Index})\]

### 2.5 Hokage Alpha Score (0–100)
A weighted composite index aggregating operational, trading, and decision quality:
\[\text{Alpha Score} = 0.20 \cdot \text{Outperformance} + 0.15 \cdot \text{Sharpe} + 0.15 \cdot \text{Drawdown} + 0.15 \cdot \text{Reality} + 0.15 \cdot \text{Consistency} + 0.10 \cdot \text{Decision Quality} + 0.05 \cdot \text{Execution} + 0.05 \cdot \text{Calibration}\]

---

## 3. Evidence-Based Promotion Readiness

The Promotion Engine classifies readiness into **5 Promotion Readiness Levels**:
* **`NOT_READY`**: Thresholds not met, or critical system failures active.
* **`EARLY_SHADOW`**: Initial trading cycle. Active monitoring is ongoing.
* **`STABLE_SHADOW`**: Stable metrics, moderate duration, but lacks diverse environment validation.
* **`CANDIDATE_FOR_LIVE`**: Fully validated across all statistical and operational thresholds. Ready for Commander review.
* **`LIVE_READY`**: Explicitly approved by the Commander (Anant). This is the only state that permits live routing toggling.

### 3.1 The 12-Point Checklist
1. **Minimum Shadow Duration**: \(\ge 30\) calendar days.
2. **Minimum Trade Count**: \(\ge 50\) fully closed trades.
3. **Market Regime Diversity**: \(\ge 3\) distinct market environments validated.
4. **Drawdown Stability**: Actual maximum drawdown is within expected limits and has not drifted by \(\ge 15\%\).
5. **Benchmark Outperformance**: Active Alpha return is positive (\(\alpha \ge 0\)).
6. **Reality Score**: Composite reality score \(\ge 70\).
7. **Calibration Stability**: Rolling calibration error remains \(\le 15\%\).
8. **Statistical Confidence**: HAC t-statistic for strategy returns is significant at the 95% level.
9. **Watchdog Health**: Zero active high/critical severity incidents in the Watchdog Incident Journal.
10. **Reconciliation History**: Zero unresolved critical/high severity discrepancies in the reconciliation logs.
11. **Incident History**: No system restarts or unexpected failures in the past 14 days.
12. **Operational Uptime**: Watchdog heartbeats confirm overall uptime \(\ge 99.5\%\).

### 3.2 Market Regime Coverage Matrix
Exposure and performance are tracked across 9 environments:
* **Bull**, **Bear**, **Sideways**, **High Volatility**, **Low Volatility**, **Gap Up**, **Gap Down**, **Earnings Events**, **Macro News Events**.

**Sufficiency Rule**: To progress to `CANDIDATE_FOR_LIVE`, the system must have executed at least **5 trades** or spent at least **5 trading days** exposed to each major environment (Bull, Bear, Sideways, High Volatility, Low Volatility). If any major environment is under-represented, the promotion engine flags it as **UNDER_TESTED** and blocks promotion to `CANDIDATE_FOR_LIVE` or `LIVE_READY`.

---

## 4. Cryptographic Report Immutability

Every daily, weekly, or monthly report is archived as a structured JSON document. Before it is saved to the `immutable_validation_reports` table:
1. The JSON object is serialized to a canonical string (with sorted keys).
2. A SHA-256 hash is computed from the serialized string and stored in the `checksum` column.
3. The report is written transactionally.

Whenever a report is retrieved (either via the API, Dashboard, or CLI), the system recalculates the SHA-256 hash of `content_json` and compares it to the stored `checksum`. If they do not match, the system raises a critical operational warning (`INTEGRITY_VIOLATION`), flagging that the historical record has been altered. This ensures absolute auditability and tamper-evidence.

---

## 5. Operations Guide

### 5.1 CLI Commands
```powershell
# Start shadow trading session
hokage shadow start 100000.0

# View current session status and returns
hokage shadow status

# Check relative benchmark metrics (Alpha, Tracking Error, Information Ratio)
hokage shadow benchmark

# Audit the 12-point checklist and promotion readiness levels
hokage shadow readiness

# Check the composite Alpha Score breakdown
hokage shadow alpha

# Replay a specific trade in detail, answering the 9 Whys and showing step-by-step timeline
hokage replay TRADE_ID

# Generate and archive an EOD daily validation report
hokage shadow report daily

# Stop shadow trading session
hokage shadow stop
```

### 5.2 REST API Endpoints
* `GET /api/v1/shadow/performance?benchmark=NIFTY_50`
* `GET /api/v1/shadow/attribution`
* `GET /api/v1/shadow/calibration`
* `GET /api/v1/shadow/alpha-score`
* `GET /api/v1/shadow/readiness`
* `GET /api/v1/shadow/reports`
* `GET /api/v1/shadow/reports/<report_id>`
* `GET /api/v1/replay/<trade_id>`
* `POST /api/v1/shadow/session/start`
* `POST /api/v1/shadow/session/stop`
