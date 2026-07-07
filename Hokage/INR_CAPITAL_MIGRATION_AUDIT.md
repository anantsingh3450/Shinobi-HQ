# Hokage INR Capital Migration Audit
## Phase 5.0 — Paper Account Currency Migration & Sizing Audit

This audit evaluates the requirements, locations, and verification steps necessary to migrate the paper-trading account's base currency from USD to INR, and recommends starting capital sizing for Indian equities.

---

## 1. INR Capital Migration Audit (Locations & Scope)

A codebase scan identified the following locations where currency denominations or hardcoded USD values are defined:

### Core Configuration Files
1.  **`hokage_brain/portfolio/account_paper.json`**
    *   *Current:* `"currency": "USD"`, `"initial_balance": 10000.0`, `"cash": 10000.0`.
    *   *Proposed:* Change to `"currency": "INR"`, `"initial_balance": 1000000.0`, `"cash": 1000000.0`.
2.  **`hokage_brain/intelligence/market_snapshot.json` & `morning_briefing.json`**
    *   *Current:* Display USD denominations and indices (e.g., Oil, Gold).
    *   *Proposed:* Reference Indian index indicators (NIFTY 50, BANKNIFTY) and USD/INR rates.

### Source Code Files
1.  **`src/bots/portfolio/models.py`**
    *   *Current:* Line 147: `currency: str = "USD"`, Line 245: `currency=data.get("currency", "USD")`.
    *   *Proposed:* Change defaults to `"INR"`.
2.  **`src/integrations/data/mock_provider.py`**
    *   *Current:* Default currency in `dummy_source` models defaults to `"USD"`.
    *   *Proposed:* Change mock instrument configurations for Indian assets (e.g., RELIANCE, TCS, NIFTY) to `"INR"`.
3.  **`src/integrations/tax/mock_provider.py`**
    *   *Current:* Injects `"USD"` for taxes on non-Indian assets.
    *   *Proposed:* Maintain `"INR"` for local brokerage, GST, and stamp duty on Indian equites.
4.  **`src/bots/autonomous/briefings.py`**
    *   *Current:* Formats metrics and rolling drawdowns using `$` signs.
    *   *Proposed:* Replace formatting strings with `₹` or `INR`.

### Test Files
1.  **`tests/unit/bots/portfolio/test_models.py`**
    *   *Current:* Checks default accounts for `"USD"` currency keys.
    *   *Proposed:* Update assertions to expect `"INR"`.
2.  **`tests/unit/bots/execution/test_paper_engine.py` & `test_execution_bot.py`**
    *   *Current:* Tests pass trade inputs expecting USD netting.
    *   *Proposed:* Align mock parameters to utilize INR.

---

## 2. Recommended Alpha Starting Capital

We evaluated three potential starting capital configurations for paper trading Indian equities:

### Option A: ₹1,00,000 (INR 1 Lakh)
*   **Analysis:** Extremely constrained. Hokage’s single-stock exposure cap is limited to $5\%$ of total equity (₹5,000). A single share of TCS (approx. ₹3,800) or Reliance (approx. ₹2,900) would consume almost the entire allocation budget for that stock. Buying higher priced equities like Maruti or MRF is mathematically impossible. Sizing and rebalancing sizers would experience severe round-off errors.
*   **Verdict:** **REJECTED** (Insufficient buffer for diversified portfolio sizers).

### Option B: ₹5,00,000 (INR 5 Lakhs)
*   **Analysis:** Moderate buffer. The $5\%$ single-position cap allows ₹25,000 per symbol, permitting the purchase of 6-8 shares of TCS or Reliance. This size is suitable for basic trades but remains restrictive for multi-sector rotation models or concurrent options hedging.
*   **Verdict:** **FEASIBLE** (Acceptable, but constraints remain for liquid baskets).

### Option C: ₹10,00,000 (INR 10 Lakhs)
*   **Analysis:** Ideal institutional paper-trading starting capital. The $5\%$ single-stock cap allows ₹50,000 per position, ensuring that the ATR-based volatility sizing models can allocate shares smoothly for high-priced blue-chip equities without executing fractional shares. Allows robust diversification across a standard basket of 15-20 stocks under the $25\%$ sector caps, leaving a cash buffer for dynamic stock-bond asset allocation rebalancing.
*   **Verdict:** **RECOMMENDED** (Optimal size for simulated Indian equities).

---

## 3. Verification & Impact Report

*   **Logic Integrity:** No trading, risk, or conviction logic will break because Hokage’s engines perform math on raw floats (`float`). The currency label is purely a string descriptor.
*   **Test Failures (Anticipated):** If the change is made blindly:
    *   `tests/unit/bots/portfolio/test_models.py` will fail on lines asserting default account attributes are `"USD"`.
    *   `tests/integration/test_phase3b_commands.py` will fail on test commands matching formatted strings.
*   **Remediation Plan:**
    1.  Update the default currency attribute in the `Account` constructor in `src/bots/portfolio/models.py` to `"INR"`.
    2.  Update the default value in `from_dict` to fallback to `"INR"`.
    3.  Update the test cases in `test_models.py` and integration pipelines to specify `"INR"` or expect `"INR"` in default outputs.
    4.  Verify that all 317 tests pass successfully with the new currency defaults.

---

## 4. Go/No-Go Recommendation

*   **Go/No-Go Verdict:** **GO ON AUDIT** ✅
*   **Recommendation:** Approve this audit report, and proceed to modify the capital configuration from USD to INR (using ₹10,00,000 as starting capital) during the next session setup.
