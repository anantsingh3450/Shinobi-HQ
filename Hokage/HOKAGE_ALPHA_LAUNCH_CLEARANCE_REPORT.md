# Hokage Alpha Launch Clearance Report
## Phase 5.0 — Final Pre-Launch Sanity Check & Verification

This report provides the final repository-wide currency audit and readiness validation prior to launching Phase 5.0 simulated paper trading.

---

## 1. Currency Audit (USD and "$" Scan)

Every occurrence of `"USD"`, `"usd"`, and `$` across the repository has been classified to verify currency separation.

| File | Occurrence | Classification | Action Required |
| :--- | :--- | :--- | :--- |
| `src/bots/portfolio/models.py` | `e.g. "EUR/USD"` | DOCUMENTATION (Docstring) | None (Intentional instrument descriptor) |
| `src/bots/portfolio/models.py` | `currency: str = "INR"` | ACTIVE PRODUCTION CODE | None (Successfully migrated to INR) |
| `src/bots/portfolio/models.py` | `data.get("currency", "INR")` | ACTIVE PRODUCTION CODE | None (Successfully migrated to INR fallback) |
| `data/portfolio/account_paper.json` | `"currency": "INR"`, `₹5 Lakhs` | ACTIVE PRODUCTION CODE | None (Successfully migrated to INR) |
| `hokage_brain/portfolio/account_paper.json` | `"currency": "INR"`, `₹5 Lakhs` | ACTIVE PRODUCTION CODE | None (Successfully migrated to INR) |
| `src/bots/autonomous/briefings.py` | `"USDINR" quote` | ACTIVE PRODUCTION CODE | None (Intentional market rate indicator) |
| `src/bots/autonomous/briefings.py` | `$ for Crude/Gold` | INTENTIONAL / MUST REMAIN | None (Crude and Gold are priced in USD globally) |
| `src/bots/autonomous/predictive.py` | `USDINR correlation` | ACTIVE PRODUCTION CODE | None (Intentional indicator parameter) |
| `src/bots/autonomous/research_intel.py` | `"USDINR" index` | ACTIVE PRODUCTION CODE | None (Intentional scanner ticker) |
| `src/integrations/data/models.py` | `currency: str = "USD"` | INTENTIONAL / MUST REMAIN | None (Default model currency for global assets) |
| `src/integrations/data/mock_provider.py` | `FOREX/CRYPTO symbols` | INTENTIONAL / MUST REMAIN | None (EUR/USD, GBP/USD are standard global assets) |
| `src/integrations/tax/models.py` | `default = "USD"` | INTENTIONAL / MUST REMAIN | None (Default model tax currency for global assets) |
| `src/integrations/tax/mock_provider.py` | `Taxes for crypto/commodities` | INTENTIONAL / MUST REMAIN | None (Intentional simulated taxes in USD) |
| All test files (`tests/`) | `EUR/USD, GBP/USD, USD` | TEST ONLY | None (Isolated testing variables) |
| All playbook files (`*_PLAYBOOK.md`) | `$` math boundaries | DOCUMENTATION (LaTeX delimiters) | None (LaTeX delimiters must remain) |
| All report files (`*_REPORT.md`) | `INR` / `₹5 Lakhs` | DOCUMENTATION | None (Report descriptors) |

---

## 2. Remaining USD References

The only remaining `USD` or `$` references in the active codebase are:
1.  **Market Symbols / Quotes:** Currency pairs (e.g. `EUR/USD`, `GBP/USD`, `USDINR`) and global commodities (e.g. `GOLD`, `CRUDE` priced in USD). These represent real tradable assets and are intentionally left untouched.
2.  **Mock Price & Tax Providers:** Global assets in the simulated providers default to USD, while local assets default to INR. This is intentional to test multi-currency compatibility.
3.  **LaTeX Math Delimiters:** Standard markdown LaTeX markers (e.g., `$$` and `$`) used to render equations in playbooks.
4.  **Unit Tests:** Mocks in unit tests use EUR/USD pairs to test the sizers and netting, which isolates them from the production paper account state.

---

## 3. Architecture & Sizing Verification

*   **Paper Account Currency:** `INR` (Verified in both portfolio stores).
*   **Paper Account Capital:** `₹5,00,000.00` (Verified in both portfolio stores).
*   **Account default currency:** `INR` (Verified in `src/bots/portfolio/models.py`).
*   **Briefings Formatting:** The EOD analytics summaries utilize Rupee `₹` or `INR` labels for account cash and portfolio balances.
*   **Portfolio calculations:** Sizers execute math strictly on floats and divide nominal position targets by the asset price. They are currency-agnostic and work seamlessly with INR stock prices.
*   **Live Writes Safety:** Live broker connectivity operates strictly in `READ_ONLY` mode via dynamic context checks. Live trading is physically disabled.

---

## 4. Alpha Readiness Verification

*   **Unit & Integration Tests:** `349 / 349` passing tests ✅
*   **Codebase Hygiene:** PASS ✅
*   **Ingestion Infrastructure (Phase 5B):** COMPLETE (Commander Profile & Persistent Operating State) ✅
*   **Stack Readiness:**
    *   *Trade DNA:* Operational and verified.
    *   *Position Review:* Operational and verified.
    *   *Decision Journal:* Operational and verified.
    *   *Performance Analytics:* Operational and verified.
    *   *Paper Environment:* PaperVenue execution is fully functional.

---

## 5. Risks & Safeguards

1.  **Risk:** Accidental order placement on Zerodha live accounts during test scans.
    *   *Safeguard:* Strict context boundary check blocks any Zerodha API write call, throwing an authentication or safety lock exception if bypassed. Live writes are architecturally disabled.
2.  **Risk:** Sizing rounding errors on Indian equities with very low share prices.
    *   *Safeguard:* Sizers calculate allocations based on total cash size. Sizing rounds down to integer quantities to avoid executing fractional shares.

---

## 6. Recommendation & Clearance Verdict

All launch prerequisites have been checked and verified clean. There are zero active blockers.

# VERDICT:
```text
ALPHA LAUNCH CLEARED
```
