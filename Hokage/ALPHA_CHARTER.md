# Hokage Alpha Program Charter
## Phase 5.0 — Simulation Governance Charter

This charter defines the scope, resources, boundaries, and non-negotiable parameters governing the Hokage Alpha Program.

---

## 1. Mission Statement
To empirically validate Hokage's autonomous capital allocation stack and qualitative/quantitative read-only knowledge modules under simulated live Indian equities market conditions. The objective is to verify execution compliance, sizer sanity, analytics tracking, and automated risk systems without capital risk, preparing Hokage for production readiness.

---

## 2. Program Parameters

*   **Duration:** 3 Calendar Months (approx. 90 calendar days / 60 active trading sessions).
*   **Starting Capital:** `₹5,00,000.00` INR (simulated cash).
*   **Asset Class:** Nifty 50 constituents and highly liquid Indian equities.
*   **Execution Mode:** `PAPER` mode (strictly executing on `PaperVenue` simulated engine).
*   **Live Writes Status:** **DISABLED** (Zerodha Kite connection set to `READ_ONLY`).

---

## 3. Strict Risk Limits

*   **Single-Symbol Exposure Cap:** Maximum of $5\%$ of total account equity per position (₹25,000.00 maximum entry size).
*   **Sector Exposure Cap:** Maximum of $25\%$ of total account equity per sector (₹1,25,000.00 maximum aggregate exposure).
*   **Daily Drawdown Limit:** $2.0\%$ of starting daily equity (Vetoes further entries for the session).
*   **Max Portfolio Drawdown Cap:** $8.0\%$ peak-to-trough account decay (Triggers automatic program termination).

---

## 4. Primary Metrics

*   **Success Target:** Compliance Score $\ge 95\%$, Profit Factor $\ge 1.30$, Sharpe Ratio $\ge 1.20$, and average Execution Quality Grade $\ge 80\%$.
*   **Failure Threshold:** Max Drawdown $\ge 8.0\%$, any manual parameter modification, or average execution slippage $> 2\%$ ATR.

---

## 5. Non-Negotiable Rules

1.  **Zero Discretionary Trading:** Order entries, exits, and ATR-based trailing stops are 100% automated. No human-in-the-loop decisions or order cancels are permitted during active sessions.
2.  **Stop-Loss Immutability:** Once a trade is open, its stop-loss can only be adjusted to lock in profit (trailing). Widening or deleting stops is strictly prohibited.
3.  **Mandatory Audit Trails:** Every trade must have a corresponding entry in `decision_journal.jsonl` containing the full 7-gate IC reasoning chain.
4.  **Decoupled Knowledge Layer:** Knowledge databases are read-only resources. Active execution parameters cannot be altered at runtime by the knowledge engine database.
