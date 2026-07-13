# COVERAGE DEBT

Production logic that has **no test exercising it**. Discovered during Phase 1.5
(De-Mock the Production Tree): when a `pytest`/`Mock` sniff was removed and ZERO
tests broke, that proves the real branch was never under test — a coverage hole,
not a pass. Ranked by money-at-risk.

Legend: 🔴 high (can move real money wrong) · 🟠 medium (safety gate untested) · 🟢 low (advisory/reporting).

---

## 🟠 A3 — Opening Bell Observation Protocol block (untested + wall-clock flaky)
- **File:** `src/bots/autonomous/autonomous_bot.py` (`_scan_and_enter_opportunities`, ~line 1619)
- **Logic:** blocks NSE/BSE entry orders during 09:15–09:30 IST (first 15 min, high-volatility open).
- **Hole:** the removed sniff forced `is_observation_window = False` under pytest, so the
  block was NEVER executed by any test. No test asserts NSE symbols are blocked in-window,
  nor that they pass outside it.
- **Added risk (latent):** value now derives from the real session clock with no injectable
  seam. A test run (or CI) between 09:15–09:30 IST would block NSE test symbols (e.g. the
  TCS entry test) and fail intermittently. Needs a clock seam to be deterministically testable.
- **Fix owed:** inject a clock / `now_ist` seam (production default = real time); add tests for
  in-window block + out-of-window pass.

## 🟠 B1 — Volume breakout check is non-functional (fabricated average)
- **File:** `src/bots/autonomous/autonomous_bot.py` (main entry ~line 2012, shadow path ~line 2700)
- **Sniff removed:** `isinstance(quote, Mock)` → hardcoded `current_vol=10000, avg_vol=5000`.
- **Deeper defect (NOT a mock issue):** even on the real path, `avg_vol = current_vol / 2.0`.
  So the breakout ratio is ALWAYS `current/avg = 2.0`, which always clears the 1.2x threshold.
  The volume-breakout gate can never reject anything — it is decorative.
- **Hole:** no test exercises volume rejection with real quote data (Mock quotes fall through
  to the exception fallback `10000/5000`, same always-pass result).
- **Fix owed:** source a real average volume (historical N-day avg via price_source), then add
  tests for both breakout-pass and breakout-reject.

## 🟠 B2 — Liquidity bid/ask ratio is fabricated from a hash
- **File:** `src/bots/autonomous/autonomous_bot.py` (main entry ~line 2044, shadow path ~line 2724)
- **Sniff removed:** `isinstance(quote, Mock)` → hardcoded `spread_pct=0.05, bid_ask_ratio=1.0`.
- **Deeper defect:** `bid_ask_ratio` is derived from `sha256(symbol)` — a deterministic
  pseudo-random number, NOT real order-book depth. The liquidity check runs on fiction.
  (spread_pct itself IS real when a real quote is present.)
- **Hole:** no test exercises liquidity rejection with real order-book data.
- **Fix owed:** use real bid/ask sizes from the quote; add pass/reject tests.
- **Related:** interacts with the frozen spread threshold (`intelligence.py:88`, 1.5 vs 0.20).

## 🔴 C1b — SQLite persistence path untested (durability layer)
- **File:** `src/shared/persistence/sqlite_engine.py` + 20+ store call sites.
- **State:** C1a removed the `pytest` sniff in `is_active()`; backend now selected on
  real DB existence. But no normal test builds a migrated `hokage.db`, so every store's
  SQLite branch is still exercised only by `test_sqlite_persistence`.
- **Money-at-risk:** HIGH — this is the durability layer for live trading (trades,
  positions, ledger, journal). JSON and SQLite stores are not proven to agree.
- **Fix owed:** Stage C1b in `C1_SQLITE_MIGRATION_PLAN.md` — a `sqlite_brain` fixture +
  dual-backend store tests, one store at a time.

## 🟢 A1 — PCR advisory sniff
- **File:** `src/bots/autonomous/autonomous_bot.py` (~line 1988, PCR advisory path)
- **Logic:** Put/Call-ratio advisory signal. Removed sniff; 0 tests broke.
- **Hole:** advisory-only output has no test. Low money-at-risk (informational, does not size or gate orders).
- **Fix owed:** unit test for the advisory computation.
