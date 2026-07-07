# Hokage Architectural Decisions

This document maintains the canonical log of architectural decisions made throughout the Hokage project.

---

## Phase 1: Core Bot Ecosystem

### Decision 1: Pipeline Order
* **Decision**: Research → Strategy → Backtest → Risk → Execution → Portfolio
* **Rationale**: Validates strategy before risk evaluation, risk before execution, execution before portfolio update. Prevents invalid trades from reaching portfolio.
* **Status**: IMPLEMENTED

### Decision 2: Risk Gating Before Execution
* **Decision**: RiskBot validates proposal against account state AFTER backtest but BEFORE execution.
* **Rationale**: Protects account from exceeding risk limits (max drawdown, position size) even if strategy passes backtest.
* **Status**: IMPLEMENTED

### Decision 3: Portfolio Persistence
* **Decision**: Account state persists after EVERY trade execution via JsonPortfolioStore.
* **Rationale**: Enables accurate risk checks in future trades by loading current account state.
* **Status**: IMPLEMENTED

### Decision 4: Clean Architecture in Bots
* **Decision**: Business logic belongs inside bots. Orchestrator only coordinates workflow.
* **Rationale**: Maintains separation of concerns. Each bot is independently testable. Rules like MaxDrawdownRiskRule, MaxPositionSizeRiskRule live in RiskBot, not orchestrator.
* **Status**: ENFORCED

### Decision 5: Dependency Injection
* **Decision**: All bot dependencies (sources, engines, stores) passed to constructors, not instantiated inside bots.
* **Rationale**: Enables testing with mock implementations. Production and test code can inject different adapters.
* **Status**: ENFORCED

---

## Phase 2: Dashboard Foundation

### Decision 6: Dashboard as Read-Only Service
* **Decision**: DashboardService is read-only, exposes no side effects, and uses existing persistent stores.
* **Rationale**: Maintains separation of concerns. Dashboard queries existing Account and TradeRecord state without modifying orchestrator or bots.
* **Status**: IMPLEMENTED

### Decision 7: Flask REST API for Dashboard
* **Decision**: Dashboard exposes Flask REST API with JSON endpoints under `/api/v1/portfolio/`.
* **Rationale**: Extensible foundation for future web UI. Can be extended with WebSocket, auth, multi-account support without modifying dashboard service.
* **Status**: IMPLEMENTED

---

## Phase 3A: Provider & Tax Architecture

### Decision 8: Provider-Agnostic Architecture
* **Decision**: Create `MarketDataProvider` protocol (extends `PriceSource`) and a `ProviderFactory` pattern to swap providers (Mock, Kite, AlphaVantage) at instantiation.
* **Rationale**: Enables switching between paper-trading mock data and real live market data dynamically via config.
* **Status**: IMPLEMENTED

### Decision 9: Tax Architecture
* **Decision**: Implement a simulated tax provider (`SimulatedTaxProvider`) and tax ledger (`JsonTaxLedger`) to calculate and persist transaction costs (brokerage, GST, STT, stamp duty) after execution but before portfolio updates.
* **Rationale**: Simulating real-world transaction friction early prevents false confidence in high-turnover strategies.
* **Status**: IMPLEMENTED

---

## Phase 4A & 4B: Universal Execution Infrastructure (UEI)

### Decision 10: Swappable Execution Venues
* **Decision**: Wrote abstract `BaseExecutionVenue` interface and `ExecutionVenueRegistry` to support multi-venue routing.
* **Rationale**: Decouples the strategy execution bot from platform-specific APIs. Swapping between Paper and Live Zerodha accounts requires zero changes to core trading logic.
* **Status**: IMPLEMENTED

---

## Phase 4C: Zerodha Connectivity & Autonomous Trading

### Decision 11: Read-Only Broker Constraints
* **Decision**: All live Zerodha broker connections (`KiteVenue`) are strictly locked in `READ_ONLY` mode by active context checks, while paper trading (`PaperVenue`) is permitted to write.
* **Rationale**: Prevents accidental live order placement during testing and initial deployment phases.
* **Status**: IMPLEMENTED

### Decision 12: Two-Speed Brain Architecture
* **Decision**: Separate the trading pipeline into Layer 1 Fast Trading Brain (synchronous scheduler scanning, position monitoring, and risk checks under 5-second latency targets) and Layer 2 Deep Intelligence Brain (asynchronous news parsing, sentiment indicators, cosine vector analogues matching, and briefings).
* **Rationale**: Prevents expensive cognitive and data retrieval latency from blocking execution sweeps.
* **Status**: IMPLEMENTED

### Decision 13: Capital Preservation Engine & Personality Layer
* **Decision**: Scale position sizing and trade availability based on the `CapitalPreservationEngine` (losing streaks, VIX volatility delta, severe drawdown limits) and the `PortfolioManagerPersonalityLayer` (supporting AGGRESSIVE, BALANCED, DEFENSIVE, RECOVERY, ADAPTIVE modes).
* **Rationale**: Prioritizes capital preservation over execution frequency.
* **Status**: IMPLEMENTED

### Decision 14: 7-Gate Investment Committee Reasoning Chain
* **Decision**: Every trade decision must traverse 7 IC gates (Preservation, Health, Conviction, Calibration, Veto, Allocation, Risk) and save the complete reasoning chain to the transaction-safe SQLite database `decision_journal` table (with legacy records archived in [decision_journal.jsonl.migrated](file:///c:/Users/anant/OneDrive/Documents/AI%20PROJECT/AI%20COMMAND%20CENTRE/Hokage/hokage_brain/journal/decision_journal.jsonl.migrated)).
* **Rationale**: Ensures complete institutional traceability and auditable explainability.
* **Status**: IMPLEMENTED

### Decision 15: Post-Exit Quality Review & Trade DNA
* **Decision**: Run the `PositionReviewEngine` (grading entry, exit, sizing, and stop quality) and `TradeDNAEngine` (fingerprinting wins and losses across 5 dimensions) asynchronously in a Layer 2 `ThreadPoolExecutor` after a position is closed.
* **Rationale**: Audits trading execution quality without blocking Layer 1 latency targets.
* **Status**: IMPLEMENTED

---

## Phase 4C.5E: Knowledge Ingestion Layer

### Decision 16: Read-Only Knowledge Modules
* **Decision**: Formalize trading playbooks into static JSON databases under `knowledge/` and load them via a read-only `KnowledgeManager`.
* **Rationale**: Restricts execution bots from dynamically modifying their core code paths based on unverified psychological or market principles.
* **Status**: IMPLEMENTED

---

## Phase 5: Self-Improving Loop

### Decision 17: Strictly Advisory Optimization
* **Decision**: In Hokage Alpha, `ImprovementBot` is strictly advisory. Proposals for parameter updates are ranked and presented, but require explicit Commander approval before being applied to configuration files.
* **Rationale**: Prevents uncontrolled, autonomous system adaptation during early live operations.
* **Status**: IMPLEMENTED

---

## Phase 6.1: ACID Persistence Layer

### Decision 18: SQLite Backend with JSON Fallback
* **Decision**: Swap the JSON-based storage layer with transactional SQLite. Wrote automatic JSON migration, thread-local WAL connection pools, and automatic rollback recovery.
* **Rationale**: Provides ACID transaction guarantees for trades, accounts, and journals while maintaining complete backward compatibility via JSON fallback.
* **Status**: IMPLEMENTED

---

## Sprint 2: Broker Reconciliation Engine

### Decision 19: Discrepancy Classification & Freezes
* **Decision**: The `ReconciliationEngine` continuously compares broker and local state. It categorizes discrepancies (LOW to CRITICAL) and instantly freezes trading on the affected asset if a position mismatch occurs, while limiting recovery to local database adjustments.
* **Rationale**: Restricts automatic broker modifications to preserve capital and prevent compounding trade errors.
* **Status**: IMPLEMENTED

---

## Phase 6.2: Secrets Vault

### Decision 20: OS-Native Keyring Integration
* **Decision**: Store all broker credentials and API tokens inside the OS-native credential vault (`keyring`), with automatic migration and secure value masking in logs.
* **Rationale**: Eliminates plaintext secrets from the repository.
* **Status**: IMPLEMENTED

---

## Phase 6.3: Watchdog & Heartbeat Monitoring

### Decision 21: Subsystem Heartbeats and Safe Restart Policy
* **Decision**: Track heartbeats from all active subsystems and enforce a strict 4-point safe restart policy (no live orders, no active reconciliation, database transaction complete, broker session stable) prior to executing restarts.
* **Rationale**: Detects operational anomalies and executes recovery runs only when safe.
* **Status**: IMPLEMENTED

---

## Phase 6.4: Newey-West HAC Statistical Engine

### Decision 22: Dual-Statistics Strategy Promotion
* **Decision**: Compute both classical Welch and HAC-adjusted statistics during strategy promotion evaluations. Use the HAC-adjusted t-statistic as the final authority, while logging classical statistics side by side for historical comparison and explainability.
* **Rationale**: Accounts for serial correlation and heteroskedasticity in financial returns to prevent false-positive promotions.
* **Status**: IMPLEMENTED

---

## Phase 6.4.5 & 6.4.6: Stabilization & Readiness Audits

### Decision 23: Centralization of Shared Utilities
* **Decision**: Extract duplicate `utc_now()` local helper functions across 8 production model and ledger files into a centralized utility module `shared.utils.datetime_utils`.
* **Rationale**: Enforces code dry principles, simplifies imports, and achieves 100% clean repository hygiene.
* **Status**: IMPLEMENTED

---

Last updated: 2026-06-26 (Phase 6.4.6 completion, Alpha Trading Readiness Audit passed)
