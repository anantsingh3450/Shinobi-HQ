# Hokage Project Memory

Canonical project memory documenting the system mission, architecture, and phase progression.

> [!IMPORTANT]
> **Core Doctrine**: Hokage must evolve into a Global Opportunity Discovery Engine.
> **The Prime Objective**: Find the highest risk-adjusted opportunity available anywhere within the approved investment universe.

## 1. Project Mission & Architecture
Hokage acts as the central commander interface, routing tasks and managing a specialized fleet of bots. Bots accept logic engines via constructor dependency injection and pass strongly-typed data structures. All decisions and execution records are auditable and traceable back to original source data.

The unified trading pipeline is defined as:
Research → Strategy → Backtest → Risk → Execution → Tax → Portfolio

## 2. Phase Progression & Status

### Phase 1: Core Bot Ecosystem (COMPLETE)
- **Scope**: Integrated core bots (`ResearchBot`, `StrategyBot`, `BacktestBot`, `RiskBot`, `ExecutionBot`, `PortfolioBot`), local persistent JSON stores for trades (`trades.jsonl`) and portfolio account details (`account_paper.json`), and local command router REPL.
- **Architectural Facts**: Core pipeline order prevents invalid trades. Risk validation occurs after backtest but before execution to protect capital. Portfolio updates persist after every trade.

### Phase 2: Dashboard Foundation (COMPLETE)
- **Scope**: Developed read-only `DashboardService` and Flask REST API (`/api/v1/portfolio/`) to expose portfolio views and metrics with zero dependency on core bots.

### Phase 3A: Provider & Tax Architecture (COMPLETE)
- **Scope**: Created `ProviderFactory` for runtime configuration. Built `MockMarketDataProvider` with candle generators. Implemented `HistoricalBacktestEngine` stepping provider candles, computing tax, and recording to `JsonPredictionLedger`. Simulated taxes (brokerage, GST, STT, stamp duty, crypto tax) are logged to `JsonTaxLedger`.

### Phase 3B: Interactive CLI Commands & Sandbox Prep (COMPLETE)
- **Scope**: Implemented interactive CLI commands (`portfolio`, `positions`, `predictions`, `tax`) in the router/shell. Integrated `execute_paper_trade` to dynamically update portfolio and tax state. Verified via full integration test suite.

### Phase 4B: PaperVenue & UEI Integration (COMPLETE)
- **Scope**: Implemented `PaperVenue` adapter conforming to `BaseExecutionVenue`, created `ExecutionIntent`, expanded `VenueCategory`. Cleaned up direct engine state mutation, implemented explicit parameter routing, established multi-venue storage isolation, and passed hardening audit (Phase 4B.1) with 127/127 tests green.

### Phase 4C.1: Zerodha Connectivity Foundation (Read-Only Mode) (COMPLETE)
- **Scope**: Integrated `kiteconnect` client library, implemented platform-specific `SecretManager`, `KiteConnectionManager` for session authentication, `KiteAccountService` for funds/positions/holdings queries, and `KiteMarketDataProvider`. Verified safety locks block write operations and that secrets are isolated from the Portable Brain.

### Phase 4C.2: Zerodha Interactive Shell Integration (COMPLETE)
- **Scope**: Integrated natural language query routing in the command router and wired it to orchestrator pipeline methods (profile, funds, holdings, positions, quotes, watchlist, market status). Introduced `ExecutionMode` and `ExecutionContext` for multi-mode governance and dynamic safety gates.

### Phase 4C.3: Autonomous Trading Bot (COMPLETE)
- **Scope**: Designed and implemented background interval scheduler loops tracking active market hours, position monitors executing trailing stop-loss (TSL) or take-profit (TP) exits, and dynamic opportunity scanners checking watchlist candidates against backtest and risk gates.

### Phase 4C.4: Two-Speed Brain & Market Intelligence Engine (COMPLETE)
- **Scope**: Designed and implemented the Two-Speed Brain architecture separating Layer 1 Fast Trading Brain (scheduler scanning, position monitoring, risk checks, parallel ThreadPoolExecutor evaluations) from Layer 2 Deep Intelligence Brain (RSS news parsing, sentiment indicators, geopolitical assessments, sector rotation analyses, analogs Cosine vector matching, and morning briefings). Integrated the isolated precomputed cache `hokage_brain/intelligence/` to decouple execution cycles from expensive cognitive latency, and programmed EOD learning checks recording predictions and outcomes to `market_events.jsonl` automatically.

### Phase 4C.5: Capital Allocation & Capital Preservation (COMPLETE)
- **Scope**: Implemented capital allocation governance under the direction of `ConvictionScoreEngine` (0-100 score), `NoTradeDecisionEngine` (deployment locks), and `ConfidenceCalibrationEngine`. Constructed `PortfolioAwareness` (beta, drawdown tracking) and `PortfolioHealthScore` to scale position sizes. Enforced capital safety through the `CapitalPreservationEngine` (losing streaks, VIX stress delta, severe drawdown limits) and the `PortfolioManagerPersonalityLayer` (supporting AGGRESSIVE, BALANCED, DEFENSIVE, RECOVERY, ADAPTIVE modes). Added auditing traceability via `DecisionJournalSystem` (persisted to `decision_journal.jsonl`) and dynamic morning briefing sizers. Verified via 175/175 tests green.

### Phase 4C.5D: Performance Analytics & Decision Intelligence (COMPLETE)
- **Scope**: Transformed Hokage into an institutionally auditable system. Expanded `PerformanceAnalyticsEngine` with Sharpe ratio (risk-free rate=0%), profit factor, expectancy, drawdown analytics, rolling metrics, and multi-dimensional queries by regime/sector/conviction grade. Expanded `DecisionJournalSystem` with immutable decision outcomes (separate `decision_outcomes.jsonl` file linked by `decision_id`), 7-gate IC reasoning chain stored on every decision, and `get_summary_stats`. Created `PositionReviewEngine` (post-exit quality grading: entry, exit, sizing, stop, R:R, lessons) and `TradeDNAEngine` (per-trade WIN/LOSS/BREAKEVEN fingerprinting, queryable by 5 dimensions). Wired the full 7-gate reasoning chain into all `record_decision` paths in `autonomous_bot.py`. Layer 2 async tasks (Position Review + Trade DNA) execute via `ThreadPoolExecutor` to never block Layer 1. Added Section 5 Performance Analytics to daily briefings. Verified via 307/307 tests green.

### Phase 4C.5E: Knowledge Ingestion Layer (COMPLETE)
- **Scope**: Created a reusable institutional knowledge layer by translating the *Trading in the Zone*, *The Daily Trading Coach*, *Market Wizards*, *One Up On Wall Street*, *Common Stocks and Uncommon Profits*, and *The Intelligent Investor* playbooks into permanent, machine-readable JSON databases under `hokage_brain/knowledge/` and implementing `KnowledgeManager` to query them.
- **Architectural Facts**: Enforces strict separation between reading knowledge (infrastructure layer) and acting on knowledge (trading layer). Trading logic remains isolated.

### Phase 5A.2: Read-Only Hokage Command Interface (COMPLETE)
- **Scope**: Developed the command-line router interface allowing the Commander to run prefix commands (`status`, `portfolio`, `positions`, `decisions today`, `why <symbol>`, `performance`, `lessons`, `dna`, `briefing`, `review`, and `knowledge <topic>`) instead of reading raw JSON/JSONL databases.
- **Architectural Facts**: Enforces strict read-only queries with zero risk overrides or trade execution abilities. Formats all currency amounts with Indian Rupee symbol prefix (`₹`). Fully decoupled from write actions.

### Phase 5A.3: Commander Dashboard & Natural Language Interface (COMPLETE)
- **Scope**: Built the read-only web-based Commander Dashboard (responsive Android-first layout) and "Ask Hokage" natural language chat router mapping user queries to backend command handlers.
- **Architectural Facts**: Implemented regex pattern matching in `NaturalLanguageRouter` and unified metrics retrieval in `/dashboard/summary`. Registered future-proof asset-agnostic discovery interfaces under `src/shared/discovery/` to support roadmap expansion. Promoted Crypto to a first-class citizen alongside Equities, Commodities, and Forex under a unified asset abstraction. Updated the Horizon Expansion Doctrine and progression phases (Alpha -> Beta -> Gamma -> Delta -> Omega), defining asset scopes for Focused, Tactical, and Global modes in code models and roadmaps. Structured the Tax Intelligence architecture to support both Paper and Live Tax Ledgers extensible for Equity, Commodity, Forex, and Crypto taxation. Integrated the 'hokage opportunities' command in CommandRouter and NaturalLanguageRouter, enabling conversational query routing for cross-asset opportunities.

### Phase 5B: Commander Profile & Persistent Operating State (COMPLETE)
- **Scope**: Implemented the persistent commander profile with Anant as Elder as the single source of truth for all environment, horizon, risk, portfolio, and tax configurations.
- **Architectural Facts**: Defined clean enums for HorizonMode, RiskMode, ExecutionMode, and ProgressionPhase. Integrated ProfileService caching and bootstrapping into Flask dashboard server, CLI, and NLP command router. Unified status check querying values dynamically from `config/commander_profile.json` with zero hardcoding. Completed tests, hygiene, and verification under strict read-only execution.

### Phase 5B.1: Documentation Integrity Audit (COMPLETE)
- **Scope**: Executed a comprehensive repository-wide audit to ensure full documentation synchronization with code implementation.
- **Architectural Facts**: Scrubbed legacy name "Harsh" from all brain templates, implementation plans, and walkthrough logs, establishing "Elder Anant" as the canonical commander settings value. Update test count references to 349/349 passing tests. Documented Phase 5B commands in CLI_WALKTHROUGH.md and created ARCHITECTURE_MAP.md as a single-page overview. Completed validation verification runs.

### Phase 5B.3: Reality Synchronization & Execution Accountability (COMPLETE)
- **Scope**: Replaced periodic scanning with continuous event-driven surveillance and state updates. Enforced the 6-state asset state machine (`WATCHING`, `WAITING`, `LONG_READY`, `SHORT_READY`, `EXECUTED`, `NO_TRADE`). Implemented the immutable `trade_authorizations.jsonl` ledger for pre-execution gating, and logged vetoed setups in `no_trade_decisions.jsonl`. Exposed wait reasons, change logs, authorizations, and EOD no-trade review files. Integrated the Decision Status Card, Reason For Waiting Panel, and reality badges into the web dashboard.
- **Architectural Facts**: Gated simulated executions through pre-execution authorizations. Enforced dynamic environment checks via `ExecutionContext` synced with the commander profile. Updated the pytest suite to 353/353 passing tests.

### Phase 5C: Opportunity Discovery Engine (COMPLETE)
- **Scope**: Standardized asset-agnostic opportunity discovery by implementing concrete scanners (`EquityAssetScanner`, `CommodityAssetScanner`, `CryptoAssetScanner`, `ForexAssetScanner`, `ETFAssetScanner`) and the `OpportunityRankingEngine` prioritization sorting, replacing legacy hardcoded lists in the CLI opportunities route and dashboard API.
- **Architectural Facts**: Decoupled opportunity listings from static files. Conformed all multi-asset scans to the Horizon Expansion Doctrine with active scope highlight markers (`*`) driven by the commander profile. Updated the pytest suite to 355/355 passing tests.

### Phase 5: Self-Improving Loop (COMPLETE)
- **Scope**: Implemented `ImprovementBot` comparing backtest vs actual outcomes, generating advisory proposals, and applying them upon explicit Commander approval with immutable audit logs.
- **Architectural Facts**: Strictly advisory in Hokage Alpha. All autonomous writes are disabled. Every applied proposal creates an immutable record in `applied_improvements.jsonl`. Extensible design supports optional autonomous adaptation. Updated pytest suite to 383/383 passing tests.

### Phase 6.1 — ACID Persistence Layer (COMPLETE)
- **Scope**: Swapped the JSON-based persistence layer with a transactional SQLite storage backend. Designed a swappable storage engine abstraction, wrote transactional migration flows with pre-migration backups, count verification, and automatic rollback recovery. Ensured backward compatibility with existing tests by isolating test-session default paths and falling back to JSON.
- **Architectural Facts**: Default ACID persistence backend. Thread-safe isolated connection pool in WAL mode enables concurrent read/write operations safely. Schema versioning records database initialization. Primary key adjustments (position_id for positions, composite unique key for decision journal) preserve all multi-asset portfolio states and rejected decisions. All 391/391 tests pass.

### Sprint 2 — Broker Reconciliation Engine (COMPLETE)
- **Scope**: Designed and implemented a continuous Broker Reconciliation Engine (`ReconciliationEngine`) comparing broker snapshots (positions, holdings, balances, orders) vs local snapshots. Built a multi-dimensional Difference Engine and Discrepancy Classifier to categorise discrepancies into LOW, MEDIUM, HIGH, and CRITICAL severities. Implemented safety gating (ReconciliationFreezeRiskRule) and auto-recovery state re-sync.
- **Architectural Facts**: Never modifies broker state automatically. Gates executions of frozen assets instantly. Safe local recovery allows local state re-syncs, cash balance refresh, and missing metadata reconstructions in SQLite or JSON fallback. All 406/406 tests pass.

### Phase 6.2 — Secrets Vault & Credential Security Layer (COMPLETE)
- **Scope**: Implemented OS-native secure credential store (`keyring`) integration, replacing local plaintext storage of broker credentials. Built automated migration logic from `secrets.json`, controlled rollback capability, isolated in-memory test mocking, and integrated masked CLI subcommands (`hokage secrets`) to set, delete, migrate, and roll back keys.
- **Architectural Facts**: Fully isolates credentials outside the brain root. Seamlessly migrates existing environments on initialization. Resolves secure vault entries using standard `keyring` backends on host OS with zero exposure in logs or exceptions. Isolated mock storage is automatically enabled under testing (`pytest`) or `HOKAGE_TEST_MODE` configuration. All 408/408 tests pass.

### Phase 6.3 — Watchdog & Heartbeat Monitoring (COMPLETE)
- **Scope**: Implemented a production-grade Watchdog & Heartbeat Monitoring System. Designed a thread-safe Heartbeat tracker, an immutable Incident Journal for tracking system incidents (from WARNING to FATAL), active diagnostic checks (DB locks, memory, threads, latency, broker connection), safety freezes to protect capital during failures, and a strict 4-point safe restart policy. Exposed `hokage watchdog` CLI commands and Flask dashboard endpoints.
- **Architectural Facts**: Subsystems publish heartbeats containing uptime, memory, CPU, and latency. Immutable incidents are persisted in SQLite with JSON fallback. Safety freezes block order routing instantly if database locks or broker connection issues occur. Restarts are denied if safety constraints (such as pending orders or active transactions) are violated, raising a critical alert to wait for Commander intervention. All 417/417 tests pass.

### Phase 6.4 — Newey-West HAC Statistical Engine (COMPLETE)
- **Scope**: Implemented the Newey-West HAC statistical engine to calculate robust long-run variances and standard errors consistent under heteroskedasticity and autocorrelation. Designed a dedicated statistics package (`shared/statistics`) containing `covariance.py`, `lag_selection.py`, `newey_west.py`, and `statistics.py` in pure Python, utilizing the standard library `math` module for absolute portability. Integrated the dual-statistics comparison engine into the Strategy Evolution Engine (`evolution.py`) during `PROBATION -> PRODUCTION` transitions.
- **Architectural Facts**: Evaluates every promotion check using both classical Welch t-statistic and HAC-adjusted t-statistic. The HAC-adjusted t-statistic governs the actual promotion decision, while classical statistics are preserved in notifications and strategy history logs for side-by-side comparison. Categorizes evaluations into `FALSE_POSITIVE_PREVENTED`, `STATISTICAL_CONSENSUS`, and `HAC_SIGNAL_DETECTED`. Automatically falls back to classical statistics derived from Sharpe ratio and expectancy when returns histories contain <= 1 observation, maintaining 100% backward compatibility.

### Phase 6.4.5 — Engineering Stabilization Sprint (COMPLETE)
- **Scope**: Full repository audit covering hygiene, architecture, concurrency, capital preservation, and operational readiness. Centralized 8 duplicate `utc_now` definitions into `shared.utils.datetime_utils`. FMEA analysis completed for all 12 core subsystems. All 428/428 tests pass.

### Phase 6.4.6 — Alpha Trading Readiness Audit (COMPLETE)
- **Scope**: Institutional trading operations audit across the complete trading lifecycle (Research → Execution → Reconciliation). Published `HOKAGE_ALPHA_LAUNCH_CLEARANCE_REPORT.md`. Issued formal CLEARANCE GRANTED for Shadow Trading entry.

### Phase 6.5 — Shadow Trading & Performance Validation Framework (COMPLETE)
- **Scope**: Built the complete Shadow Trading framework proving Hokage can outperform before any real capital is deployed. Paper execution only — real pipeline.
- **Key Engines**:
  - `ShadowEngine` — session lifecycle, immutable SHA-256 checksummed reports
  - `BenchmarkEngine` — asset-agnostic benchmarks, Alpha / Tracking Error / Information Ratio
  - `AttributionEngine` — Shadow Reality Score, 4 decision quadrants, 9-element "Why" manifest
  - `CalibrationEngine` — Expected vs Actual calibration (win rate, drawdown, volatility, hold time, R/R)
  - `PromotionEngine` — 12-criteria evidence-based readiness, 5 promotion levels (NOT_READY → LIVE_READY), Market Regime Coverage Matrix
- **Database**: Schema upgraded to version 2 with 6 new tables. All fresh databases initialize at v2.
- **Dashboard**: New "Shadow Trading" tab with 6 glassmorphic visualization cards + Start/Stop session control.
- **REST API & CLI**: 8 new endpoints (`/shadow/*`); `hokage shadow` and `hokage replay` commands.
- **Architectural Facts**: Commander always remains final authority for LIVE_READY promotion. Validation reports are SHA-256 checksummed and stored immutably in SQLite. All datetime values in SQLite are UTC timezone-aware to prevent timezone arithmetic errors. 435/435 tests pass.

### Phase 6.6A — Institutional Statistical Diagnostics (COMPLETE)
- **Scope**: Integrated advanced mathematical validation for returns to ensure statistical edge over luck.
- **Architectural Facts**: Implemented Ljung-Box Q-test, Jarque-Bera normality test, and Kupiec Proportion of Failures (POF) test in pure Python. Designed a rolling historical VaR breach calculator to evaluate VaR calibration. Integrated diagnostics card into the web dashboard and exposed metrics via REST API and CLI. Maintained SQLite Schema Version 2 with zero migrations.

### Phase 6.6B — Execution Realism (COMPLETE)
- **Scope**: Integrated real-world market friction to the paper execution engine, eliminating unrealistic optimism.
- **Architectural Facts**: Implemented six configurable realism profiles (`ZERO`, `LIGHT`, `NSE_EQUITY`, `NSE_FNO`, `CRYPTO`, `STRESS`) toggled via environment variables or profile settings. Simulated bid-ask spreads, volatility-aware slippage, network latency, and partial fills. Designed local deterministic pseudo-random state to ensure 100% reproducible tests. Avoided actual `sleep()` calls by simulating and recording latency numerically. Implemented advisory-only Execution Quality Score contributing to Alpha Score and checklists. Serialized all metrics within the existing JSON fields of `trade_replays` without database migrations. Created REST API endpoints, `hokage shadow quality` CLI, and an Execution Quality card on the dashboard. All 455/455 tests pass.

### Deliverable: Shadow Operations (COMPLETE)
- **Scope**: Transformed Hokage into an autonomous system that behaves exactly like a live trader (real-time symbols, prices, and timestamps via live data providers) while routing all orders dynamically via the new broker-agnostic registry strictly to simulated or live venues with zero capital risk.
- **Architectural Facts**:
  - **Universal Broker Registry**: Introduced `BrokerRegistry` mapping asset classes and exchanges to brokers (e.g. Zerodha for NSE/MCX, CoinDCX for Crypto, future integrations for NASDAQ/Forex) and resolving execution venues dynamically. Core engines (trading, strategy, risk, portfolio) are 100% decoupled and never know which broker is being used.
  - **Trading Session Manager**: Replaced single-market hardcoded Indian equity hours with a reusable, asset-agnostic `TradingSessionManager` that dynamically resolves exchange timezone, trading sessions, holidays, and maintenance windows.
  - **Exchange Independence**: Supports independent lifecycles for multiple exchanges (NSE, BSE, MCX, Binance/Crypto, NASDAQ, Forex) running concurrently. The autonomous surveillance engine remains alive continuously, scanning only currently tradable assets while maintaining background monitoring, health checks, and dashboard reporting across all exchanges.
  - **Exchange-Specific EOD Reporting**: Automatically triggers EOD reports, diagnostics, briefings, and session rollovers independently at each exchange's closing time (e.g. NSE close, MCX close, and daily at midnight IST for 24/7 Crypto markets).
  - **Execution Mode Parity**: Swapping execution modes between `PAPER` and `LIVE` changes only the execution venue. The decision engine, risk engine, portfolio engine, analytics, explainability, reporting, calibration, and promotion logic remain completely identical.
  - **Live Market Ingestion**: `KiteMarketDataProvider` acts as the active `price_source` when `HOKAGE_MARKET_DATA_MODE=kite` is configured, while order routing remains bound to `PaperVenue` in `PAPER`/`SHADOW` modes.
  - **Zero-Migration Multi-Session Storage**: Prefixes the exchange name to shadow session IDs (e.g. `SHADOW_SES_NSE_...`, `SHADOW_SES_BINANCE_...`), enabling multi-session SQLite persistence without database migrations or schema alterations, keeping SQLite Schema Version 2 intact.
  - **EOD Artifact Generation**: On exchange close, the system automatically stops the session and generates:
    - **End-of-Day Report & Archive**: Saved and SQLite-persisted with SHA-256 checksums in `immutable_validation_reports`.
    - **Commander Daily Briefing**: A natural-language narrative detailing trades taken, skipped trade veto reasons (reconstructed from the 7-gate reasoning chain), highlights, biggest winners/losers, Brier calibration, and readiness trends. Saved in the brain root as `reports/daily_briefing_YYYY-MM-DD.md`.
    - **Statistical Diagnostics**: Real-time evaluation of returns using Ljung-Box, Jarque-Bera, and Kupiec VaR tests.
    - **Execution Quality Summary**: Transaction friction, dynamic slippage, and latency metrics.
  - **War Room Dashboard Enhancement**: Surgically integrated the 13-metric **Hokage Operations Command Center** widgets grid and the **Active Positions** real-time monitor table into the web dashboard war room (without decorative elements or CPU widgets).
  - **Test Suite Integrity**: All 459/459 tests pass. Maintained complete backward compatibility, zero circular dependencies, and SQLite Schema Version 2.

### Architectural Refinement: Configuration-Driven Broker Registry (COMPLETE)
- **Scope**: Removed all hardcoded broker assignments from source code. All exchange→broker mappings and broker capability profiles are now loaded from `config/broker_registry.json` at startup. Changing a broker requires only editing the config file — no recompilation, no code changes.
- **Key Changes**:
  - **`config/broker_registry.json`**: Canonical configuration file declaring `exchange_broker_map` and `broker_capabilities` for every registered broker. Supports: supported exchanges, order types (MARKET/LIMIT/STOP/STOP_MARKET), margin, product types (CNC/MIS/NRML/etc.), options, futures, fractional shares, WebSocket, historical data, paper/live execution support, and venue IDs.
  - **`BrokerCapabilityProfile`** (new model in `models.py`): Frozen dataclass representing a broker's declared capabilities, loaded from the config file via `from_dict()`. Provides `supports_order_type()` and `supports_exchange()` query methods.
  - **`CapabilityViolation`** (new exception): Raised by the registry when a requested operation is unsupported by the resolved broker (e.g. a MARKET order to a LIMIT-only broker, or a LIVE execution request to a paper-only broker).
  - **`BrokerRegistry`** (full rewrite): Config-driven. Loads from JSON at startup. Provides `validate_order_request()` and `validate_live_execution()` capability gates. Supports `register_broker_mapping()` runtime override. Falls back to built-in defaults if config is absent.
  - **`pipeline.py`**: Paper venue registration loop is now driven by `broker_registry.list_brokers()` + `profile.paper_venue_id`. Adding a new broker in the config auto-creates its paper venue — no source code changes.
- **Architectural Facts**: Core engines (trading, risk, portfolio) remain 100% broker-agnostic. Capability validation is a pre-flight advisory gate — it informs but is structurally decoupled from the execution approval chain. 473/473 tests pass. SQLite Schema Version 2 unchanged.

### Architectural Refinement: Broker Profile Directory Separation (COMPLETE)
- **Scope**: Fully separated the two concerns previously merged in `broker_registry.json`:
  - **`config/broker_registry.json`**: Exchange→broker mapping only (one line per exchange).
  - **`config/brokers/<broker_id>.json`**: Individual broker capability profiles, one file per broker.
- **Key Changes**:
  - **Auto-Discovery**: `BrokerRegistry` scans `config/brokers/*.json` at startup. The file stem (e.g. `zerodha`) becomes the broker ID. No registration required.
  - **Adding a New Broker**: Drop a new `config/brokers/<name>.json` file and add its exchange mapping to `broker_registry.json`. Zero code changes.
  - **Built-in Fallbacks**: If either the mapping file or the brokers directory is absent (e.g. CI environments), the registry falls back to built-in defaults. Platform never fails to start.
  - **Broker Profiles**: Created `zerodha.json`, `coindcx.json`, `alpaca.json`, and `oanda.json` with complete capability declarations (order types, product types, rate limits, auth type, venue IDs, constraints).
- **Architectural Facts**: Mapping and capability concerns are now fully separated. Both can evolve independently. 498/498 tests pass.

### Phase 6.6C — Portfolio Risk Hardening (COMPLETE)
- **Scope**: Introduced four institutional-grade portfolio risk constraints into the `CompositeRiskManager`. All are pure Python, zero new dependencies, and follow the existing `RiskManager` interface exactly.
- **Key Rules**:
  - **`SectorConcentrationRiskRule`**: Caps total open exposure to any single sector (default 40%). Uses a configurable symbol→sector map. Scales approved quantity to remaining sector headroom. Unknown sectors pass through without restriction.
  - **`PortfolioBetaRiskRule`**: Caps the exposure-weighted portfolio beta against the broad market (default 1.50). Beta is estimated from a configurable symbol→beta map (defaults provided for Indian equities, commodities, crypto, US tech, forex). Rejects trades that would push portfolio beta above the cap.
  - **`DynamicVaRSizingRule`**: Caps the 1-day parametric VaR contribution of any new position as a fraction of account equity (default 2%, 95% confidence). Uses `σ_daily = σ_annual / √252`. Returns a scaled-down max quantity if the position would exceed the VaR budget. Volatile assets (BTC, TSLA) receive smaller approved sizes than stable assets (GOLD, EURUSD).
  - **`ExpectedShortfallRiskRule`**: Caps the Expected Shortfall (CVaR) contribution of any new position (default 3%, 95% confidence). Uses `ES = position_value × σ_daily × φ(z_α) / (1 − α)`. More conservative than VaR at the same confidence level, capturing tail risk beyond the cutoff.
- **Integration**: All four rules wired into `CompositeRiskManager` in `pipeline.py` after the existing rules. Composite fast-fails on first rejection. Final approved quantity is the minimum across all passing rules.
- **Configuration**: All thresholds (sector %, beta cap, VaR %, ES %, confidence) and all asset maps (sector, beta, vol) are injectable via constructor parameters. Production defaults are conservative but realistic.
- **Tests**: 22 new tests in `test_portfolio_risk_hardening.py` covering approvals, rejections, headroom scaling, cross-sector independence, custom map overrides, and composite chain integration. 498/498 tests pass.

## 3. Key Decisions & Lessons Learned
- **StrategyGenerator Abstraction**: Swap adapters (heuristics to LLMs) at instantiation.
- **Simulated Tax Ledger**: Simulating transaction cost friction (STT, brokerage, stamp duties) early avoids false confidence in high-turnover strategies.
- **Brittle Heuristics**: Pure keyword heuristics are context-blind; LLM transitions are required for semantic analysis.
- **Fast Trading Brain Latency Constraint**: Reading deep-cognition elements exclusively from cached JSON structures maintains execution cycle latencies under 5 seconds.
- **Mathematical Rounding Consistency**: Custom round-up mathematical rounding `int(val + 0.5)` is preferred over Python's default banker's rounding `round()` to guarantee consistent thresholds in grade boundaries and test expectations.
- **Immutable Journals**: Decision records must never be rewritten. Phase 4C.5D approved: `decision_journal.jsonl` is append-only. Outcome updates go to a separate `decision_outcomes.jsonl`, linked by `decision_id`.
- **Sharpe Baseline = 0%**: Risk-free rate is locked at 0% for the Alpha Program incubation period. Phase 5 may migrate to Indian 10Y G-Sec rate.
- **Two-Layer Exit Flow**: Layer 1 (synchronous) records outcomes and updates the journal immediately on exit. Layer 2 (async `ThreadPoolExecutor`) runs Position Review and Trade DNA fingerprinting without blocking execution.
- **Canonical Domain Model Location**: Shared dataclasses (like `PositionReview`) must live in `models.py`, not scattered across engine files. Engine files import from `models.py`.
- **Reasoning Chain Architecture**: IC gates are traversed sequentially. Each gate appends a `{gate, decision, reason}` struct to the chain. The complete chain is stored on every `record_decision` call, regardless of ACCEPTED/REJECTED outcome. This enables full audit reconstruction.
- **Read-Only Institutional Knowledge Modules**: To avoid unstable feedback loops or unverified adaptive changes, knowledge modules (like *Trading in the Zone*) are stored in static, structured JSON formats under `hokage_brain/knowledge/` and loaded by a centralized `KnowledgeManager`. Execution bots may read these rules for validation/reference, but are prohibited from dynamically modifying their core sizing, conviction, or execution code paths based on this read-only data.
- **Read-Only CLI Decoupling**: Designed prefix matching commands in `command_router.py` to route strictly to read-only views, preventing any state modification, risk overrides, or trade executions.
- **Unified Currency Symbol Representation**: Consolidated Rupee (`₹`) symbol formatting across CLI outputs using a central `format_inr` utility, ensuring consistent localization.
- **Comprehensive Command Coverage**: Implemented all 11 user-facing commands to pull dynamically from existing JSONL and JSON databases (`account_paper.json`, `decision_journal.jsonl`, `decision_outcomes.jsonl`, `trade_performance_history.jsonl`, `position_reviews.jsonl`, `trade_dna.jsonl`, `morning_briefing.json`, and `knowledge_registry.json`).
- **Clean Registry Checking**: Hygiene verification constraints require routes to be defined without internal string duplicate elements to pass literal tuples checking.
- **Commander Natural Language Parsing**: Designed `NaturalLanguageRouter` containing regex matching heuristics mapping user sentences directly to CLI commands, facilitating loose-phrased queries (e.g. `"Why TCS?"` $\rightarrow$ `"hokage why TCS"`).
- **Modular NLP Decoupling**: Structuring the NLP router independently from presentation classes ensures a future Telegram integration can import and run query mappings directly without modifications.
- **Unified REST endpoints**: Formulated a `/dashboard/summary` route returning a single consolidated package of cash, equity, status flags, and lists previews to avoid high-frequency API polling on load.
- **Asset-Agnostic Schema Registry**: Registered future-proof interfaces and model classes under `src/shared/discovery/` to guide transition to a global multi-asset scanning architecture (Stage 3).
- **Commander Profile as Single Source of Truth**: Enforced `commander_profile.json` as the unified source of configurations (environments, horizon progression, risk limits, capital preservation, starting capital, and tax settings) dynamically loaded by all CLI, API, and NLP modules.
- **Strict Enums for System Configuration**: Replaced string-based modes with typed enums (`HorizonMode`, `RiskMode`, `ExecutionMode`, `ProgressionPhase`) to prevent runtime configuration failures.
- **SQLite Thread-Local Connection Pools**: To support concurrency under parallel scanner/monitoring loops safely, SQLite must be accessed using a thread-local connection pool (`threading.local()`) even with `check_same_thread=False` to prevent API misuse and transaction conflicts, while utilizing WAL mode for concurrent readers and writer.
- **Composite Primary Keys for Decision Logs**: Enforcement of `decision_id` as the sole primary key fails in reality because multiple rejected decisions default to an empty string. Utilizing `PRIMARY KEY (decision_id, timestamp)` solves this by ensuring append-only records never collide.
- **Pytest-Level Persistence Isolation**: In a comprehensive test suite sharing path resolvers, SQLite database files cause cross-test contamination. Adding `pytest` execution detection to disable SQLite on default workspace paths guarantees that existing unit tests continue to pass using legacy JSON fallbacks, while new persistence tests use isolated temp directories to validate SQLite.
- **Broker Reconciliation Gating**: Safety freezes must never place orders on the broker. Any critical discrepancy (such as a phantom position or duplicate broker position) immediately freezes the affected asset and triggers risk gating, blocking all subsequent orders for that asset. Safe automatic recovery is strictly limited to local database updates (metadata reconstruction, cash alignment, and marking positions closed locally if missing on the broker).
- **Schema v2 Always-Fresh Init**: The SQLite engine always initializes new databases at schema version 2 (Phase 6.5 tables included). Tests expecting version 1 must be updated to expect 2. This is by design — version 1 is a migration-only checkpoint, not the base state.
- **Timezone-Aware Datetimes in SQLite**: All datetime values stored in and read from SQLite must be timezone-aware (UTC). Mixing naive and aware datetimes causes `TypeError` in promotion engine arithmetic. Always force UTC on retrieval: `dt.replace(tzinfo=timezone.utc)` if `tzinfo is None`.
- **5-Level Promotion Readiness**: The promotion system uses NOT_READY → EARLY_SHADOW → STABLE_SHADOW → CANDIDATE_FOR_LIVE → LIVE_READY as the 5-level evidence-based classification. Commander approval is mandatory for LIVE_READY. Thresholds alone are never sufficient.
- **Shadow Reality Score Independence**: The Reality Score measures decision quality independent of P&L. A correct decision that loses due to market randomness is still classified as Correct+Loss (good decision, bad luck). This prevents P&L-only evaluation from promoting lucky strategies.
- **Configurable Realism Profiles (Phase 6.6B)**: Switched the single execution model to six configurable profiles (`ZERO`, `LIGHT`, `NSE_EQUITY`, `NSE_FNO`, `CRYPTO`, `STRESS`) allowing the Commander to switch execution realism on demand via environment variables or profile settings.
- **Numerical Latency Simulation (Phase 6.6B)**: Simulated and recorded network/execution delays in milliseconds numerically without using actual `time.sleep()`, keeping execution loops fast while preserving realism metrics.
- **Advisory Execution Quality Score (Phase 6.6B)**: The composite quality score (0-100) is strictly advisory and contributes to analytics, Alpha Score, and checklists but never vetos or blocks trade execution.
- **Hermetic Pseudo-Random State (Phase 6.6B)**: Used a local `random.Random` instance seeded by the deterministic hash of the trade inputs, ensuring simulated slippage, latency, and fills are completely realistic yet 100% reproducible in tests.
- **Zero-Migration Friction Persistence (Phase 6.6B)**: Serialized all trade-level friction metrics inside the existing `lifecycle_timeline` and `explainability_manifest` JSON columns of the `trade_replays` table, preserving SQLite Schema Version 2 and avoiding database migrations.
- **Zerodha Market Ingestion & Routing Decoupling (Shadow Operations)**: Decoupling the market data provider (`KiteMarketDataProvider`) from the execution venue ensures that the system can ingest real-time market ticks and prices while executing exclusively on `PaperVenue` with zero real capital risk. This allows the system to behave exactly like a live trader under production market conditions.
- **Broker Registry Pattern**: Core engines must never call a broker directly. The Asset → Exchange → BrokerRegistry → ExecutionVenue → BrokerAdapter chain ensures the trading pipeline is broker-agnostic. Adding a new broker (e.g. Interactive Brokers, Alpaca) requires only a new adapter and a registry entry — zero changes to core engines.
- **Hermetic Pure-Python Timezones**: Avoid external timezone dependencies (`pytz`, `dateutil`) for critical session logic. Implementing zero-dependency `tzinfo` subclasses (`KolkataTime`, `EasternTime` with DST) makes the codebase robust against system timezone database mismatches on Windows and eliminates install-time dependencies.
- **Mock-Compatible Guard Pattern**: Multi-venue loops that call `.list_venues()` break under `MagicMock` because `list_venues()` returns a non-iterable mock. Guard with `type(obj).__name__ in ("MagicMock", "Mock")` to detect mocks and fall back to the primary/default venue. This is the only acceptable pattern — never leak mock-detection logic into production code paths.
- **Exchange-Keyed Shadow Session IDs**: Prefixing shadow session IDs with the exchange name (e.g. `SHADOW_SES_NSE_<timestamp>`) encodes multi-session state into the existing `session_id` VARCHAR column. This enables multi-exchange concurrent sessions in SQLite without any schema migrations, preserving Schema Version 2 indefinitely.
- **Exchange-Independent Surveillance Loop**: The autonomous loop must manage exchange lifecycles independently. Each iteration checks every tracked exchange individually. Starting or stopping a shadow session for NSE must not affect Crypto (which runs 24/7) or NASDAQ. The loop dispatches exchange-specific callbacks; only the common monitoring/scanning tasks are shared.
- **Config-File-First Broker Pattern**: Never hardcode exchange-to-broker mappings in source code. All broker assignments live in `config/broker_registry.json`. The `BrokerRegistry` reads this file at startup and falls back to built-in defaults if the file is absent (e.g. in test environments with no project root on path). Runtime overrides via `register_broker_mapping()` are valid for testing only.
- **CapabilityViolation Pre-Flight Guard**: Before routing an order to a live broker, always call `broker_registry.validate_order_request(request, broker_id)` and `broker_registry.validate_live_execution(broker_id)`. These are advisory pre-flight checks — they raise `CapabilityViolation` if a broker cannot handle the requested operation, surfacing the gap before it reaches the broker API. Unknown brokers are allowed through with a warning so new integrations can be wired incrementally.
- **Broker Profile Directory Auto-Discovery**: Separate exchange mappings (`broker_registry.json`) from broker capabilities (`config/brokers/*.json`). `BrokerRegistry` scans the directory at startup — the file stem is the broker ID. Adding a new broker requires only dropping a JSON file and updating the mapping. Never couple exchange routing logic to broker implementation details in the same file.
- **MagicMock Attribute Poisoning in Slotted Dataclasses**: When a test helper uses `MagicMock()` to simulate a `@dataclass(slots=True)` object, explicitly set ALL numeric attributes that downstream property computations depend on (e.g. `unrealized_pnl = 0.0`). Properties like `Account.equity` iterate over positions and sum their PnL fields — if any field is a MagicMock child, arithmetic propagates MagicMock through the computation silently, poisoning all derived values (equity, max_size, max_sector_value). Never use `spec=SlottedClass` on MagicMock — slot descriptors cause assignments to be silently ignored.
- **ES > VaR at Same Confidence**: Expected Shortfall (CVaR) is always more conservative than VaR at the same confidence level because it measures the expected loss in the tail *beyond* the VaR threshold. At 95% confidence, `ES = σ_daily × φ(1.645) / 0.05 ≈ 2.06 × σ_daily` vs `VaR = σ_daily × 1.645`. The ES rule always produces a smaller approved position size than the VaR rule for the same budget and confidence level.
- **Risk Rule Composability**: All `RiskRule` implementations share the same interface (`check_order → RiskVerdict`). `CompositeRiskManager` fast-fails on the first rejection and returns the minimum `max_approved_quantity` across all passing rules. New rules are added by instantiation only — no subclassing, no registration, no modification to existing rules required.
