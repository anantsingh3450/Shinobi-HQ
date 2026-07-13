# Hokage Handover Document

## 1. SYSTEM OVERVIEW
Hokage is an autonomous, AI-driven quantitative trading bot that currently executes automated paper trading on Zerodha Kite for Nifty futures/options and Crude Oil MCX (capped at 1 lot each). Its primary goal is to safely identify, size, and execute trading opportunities while strictly adhering to asset-class lot caps, session boundaries, and dynamic Kelly-criterion position sizing models.
**Architecture Diagram:**
[Data Providers (Mock/Live)] --> [Strategy Engine (Generators/ML)] --> [Autonomous Bot (Core Loop)] --> [Risk Engine (Rules, Caps)] --> [Execution Venue (Paper/Kite)]
The `Orchestrator` coordinates the lifecycle, while the `Persistence` layer (SQLite/JSON) tracks state, `Dashboard/API` serves UI, and Telegram provides realtime alerts. The `LLM (Gemini)` acts as a reasoning engine for conviction scoring.

## 2. MODULE MAP
- `src/bots/autonomous/`: The core execution loop (`autonomous_bot.py`), market intelligence, and conviction scoring.
- `src/bots/backtest/`: Historical simulation engine.
- `src/bots/execution/`: Order routing, trade lifecycle management, and venue adapters.
- `src/bots/improvement/`: Automated self-correction and parameter tuning.
- `src/bots/portfolio/`: Ledger and portfolio-level intelligence.
- `src/bots/research/`: Data fetching and analysis.
- `src/bots/risk/`: Capital preservation rules (`rules.py`) and threshold enforcements.
- `src/bots/strategy/`: Signal generation, ML engines, and feature extraction.
- `src/hokage/dashboard/`: FastAPI web interface and UI endpoints (`api.py`).
- `src/hokage/orchestrator/`: System boot, event bus, and subsystem coordination (`pipeline.py`).
- `src/integrations/`: Brokers (Kite), Data providers, LLM (Gemini), and Telegram wrappers.
- `src/shared/`: SQLite database (`sqlite_engine.py`), watchdog, and statistics.

**Boot Path:** The app is typically launched via `Launch Hokage.bat`, which invokes the main entry point (often `src/hokage/orchestrator/pipeline.py` or a top-level runner). The orchestrator spins up the event bus, initializes subsystems (Autonomous Bot, Telegram, Dashboard), and `autonomous_bot.start()` begins the scanning/trading loop.

## 3. EXECUTION MODES & CONFIG
- **Execution Modes:** `PAPER` (default for now), `LIVE` (real Kite execution), `READ_ONLY` (scan without placing orders), `HYBRID`. Mode is selected via `HOKAGE_TEST_MODE` or explicit config passed to the orchestrator/venues.
- **Environment Variables:**
  - `HOKAGE_MARKET_DATA_MODE`: Determines if market data comes from live feeds or mock providers.
  - `HOKAGE_TEST_MODE`: Isolates execution from real networks; forces mock providers.
  - `HOKAGE_DISABLE_PUBLIC_FEED`: Disables broad market data subscriptions to save bandwidth/API calls.
  - `HOKAGE_DISABLE_LLM`: Skips Gemini API calls and uses fallback heuristics.
- **Profiles:** The commander profile, risk profile, and active universe are stored in the memory subsystem, accessible via `ProfileService` (`src/hokage/memory/profile.py`), and often persisted in `hokage.db` or legacy JSON.

## 4. INTEGRATIONS
- **Zerodha Kite:** Authentication requires the user to manually paste the `request_token` URL into the dashboard or CLI. Tokens are stored via `SecretManager` (OS Keyring or isolated memory dict). `kite_venue.py` and `kite_market_data_provider.py` handle broker interactions.
- **Telegram:** Realtime trade alerts and system warnings. Configured via API keys in the keyring.
- **LLM (Gemini):** Used via `processor.py` for evaluating trade conviction, parsing complex market signals, and logging. Keys are fetched from `.env` or keyring.
- **Other:** Minor integrations with mock providers for deterministic testing.

## 5. PERSISTENCE
- **SQLite vs JSON:** The system is transitioning to SQLite (`sqlite_engine.py`) as authoritative, but legacy JSON stores exist (383+ tests rely on JSON isolation).
- **Location:** DB is at `hokage.db` in the brain root. `sqlite_engine.py` handles schema initialization.

## 6. RISK & SIZING
- **HardLotCapRule:** Enforced at the order layer (`src/bots/risk/rules.py:876`); strictly limits trades to max allowed lots per asset (e.g., 1 lot for Nifty/Crude).
- **Position Sizing:** Handled dynamically via Kelly Criterion (`_calculate_dynamic_lot_size`), backed by the lot cap.
- **PCR Advisory:** Thresholds of CE entry < 1.15 and PE entry > 0.75 are soft warnings (`autonomous_bot.py`).
- **Spread Thresholds:** Currently under transition to be asset-class aware.

## 7. TEST SUITE STATE
- **Running:** `python -m pytest tests/`
- **Total Tests:** 538 tests.
- **Status:** 536 passed, 2 failed.
- **Failing Tests:**
  - `test_liquidity_engine` (Spread logic expects a failure on wide spread trap `0.25 <= 0.05`, but risk gates loosened).
  - `test_no_trade_generation` (VIX legacy threshold drift; expected "NO TRADE" but evaluated as "TRADE").
- **Warning:** 11 instances of "mock-sniffing" (e.g. `"pytest" in sys.modules`) were found in production code, artificially keeping tests green. This is actively being remedied in Phase 1.5.

## 8. KNOWN BUGS, LIMITATIONS, AND HALF-DONE WORK
- **Phase 1.5 De-mocking is incomplete:** While some `sys.modules` sniffs were removed (like the PCR advisory in `autonomous_bot.py:1988`), 10 others still exist in the working tree (or have been modified by Claude Code today and need verification). This includes bypasses for position sizing, opening bell blocks, and the SQLite DB init.
- **Test Integrity:** Due to the remaining mock-sniffs, a green test suite does not guarantee production safety.
- **Watchdog Warnings:** Subsystems like `orchestrator`, `surveillance_loop`, and `risk_engine` occasionally fail to publish heartbeats during test runs.

## 9. ROADMAP / PHASES
- **Current Phase:** Phase 1.5 (De-mock the Production Tree). The priority is removing all environment sniffs from `src/` to ensure tests execute actual production logic.
- **Frozen Phases:**
  - Phase 2 (Safety Gaps)
  - Phase 3 (Microstructure)
  - Phase 4 (Kelly Tuning)
  - VIX revert, asset-class spread updates, volume ratio investigation.
- **Design Decisions:** Production code must *never* detect or accommodate a test environment. Use explicit configuration seams instead of test-sniffing.

## 10. GIT & UNCOMMITTED STATE
**`git status` Summary:**
- Modified (staged): `autonomous_bot.py`, `capital_preservation.py`, `rules.py`, `pipeline.py`, `tests/conftest.py`, `test_predictive.py`, `test_shadow_mode_complete.py`, `test_data_provider_factory.py`.
- New (staged): `test_phase1_fixes.py`.
- Modified (unstaged): Includes overlap with files Claude Code has edited today (`autonomous_bot.py`, `portfolio_intelligence.py`, `sqlite_engine.py`, etc.).
- Untracked: `.pre-commit-config.yaml`, `COVERAGE_DEBT.md`, `C1_SQLITE_MIGRATION_PLAN.md`, `test_no_mock_sniffing_in_src.py`.

**`git log --oneline -20`:**
\`\`\`
6b57dc5 Automated Codebase Cleanup: Linting, removed unused imports/variables, updated state
7d70140 Sync: Refine core LLM system prompt structure to upgrade persona voice and trading bounds
5b0babc Sync: Enforce strict July 7 asset restrictions and opening bell observation protocol, expand global benchmark indicators on UI, and resolve chat router keyword hijacking
f739470 Sync: Core LLM pipeline alignment, pypdf document parsing engine, conversational halt protocol, and UI layout upgrades
4d9cdaa Fix ProviderFactory and complete Phase 3A tests
a38c9b1 Phase 3A Provider Factory and Tax Interfaces
a27daf9 Checkpoint before Phase 3 provides architecture
d422758 Research Bot Implemented
4d2bcc6 Merge branch 'main' of https://github.com/anantsingh3450/Shinobi-HQ
2b02695 initial AI Command Centre
6c74fc2 Update README.md
879c234 Initial commit
\`\`\`

### CONFLICTS FOR CLAUDE TO RECONCILE
My recent unstaged work overlaps with files you (Claude) have edited today. **Do not overwrite your changes.**
- `src/bots/autonomous/autonomous_bot.py`: I removed the `"pytest" in sys.modules` bypass for the PCR advisory around line 1988. I also previously removed a mock-sniff around line 2520 for `qty_filled`. Please ensure these sniffs are fully eradicated in your version.
- `tests/conftest.py`: I added factory fixtures for `OrderResponse` (`filled_order_response`, `rejected_order_response`, etc.).
- `tests/unit/bots/autonomous/test_shadow_mode_complete.py`: I injected `filled_order_response` to test shadow mode promotion without using a raw `MagicMock`.

## 11. FILE MANIFEST OF YOUR RECENT WORK
- `src/bots/autonomous/autonomous_bot.py`: Removed test-environment sniffs for PCR advisory and order fill checks.
- `tests/conftest.py`: Added `OrderResponse` fixtures for robust testing.
- `tests/unit/bots/autonomous/test_shadow_mode_complete.py`: Updated to use the new `OrderResponse` fixtures instead of `MagicMock`.
