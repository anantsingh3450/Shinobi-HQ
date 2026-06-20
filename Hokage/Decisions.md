# Hokage Architectural Decisions

## Phase 1: Core Bot Ecosystem

### Decision 1: Pipeline Order
**Decision**: Research → Strategy → Backtest → Risk → Execution → Portfolio
**Rationale**: Validates strategy before risk evaluation, risk before execution, execution before portfolio update. Prevents invalid trades from reaching portfolio.
**Status**: IMPLEMENTED

### Decision 2: Risk Gating Before Execution
**Decision**: RiskBot validates proposal against account state AFTER backtest but BEFORE execution.
**Rationale**: Protects account from exceeding risk limits (max drawdown, position size) even if strategy passes backtest.
**Implementation**: `pipeline.execute_full_pipeline()` calls `risk_bot.check_proposal(account, proposal, entry_price)` after backtest.
**Status**: IMPLEMENTED

### Decision 3: Portfolio Persistence
**Decision**: Account state persists after EVERY trade execution via JsonPortfolioStore.
**Rationale**: Enables accurate risk checks in future trades by loading current account state.
**Implementation**: `PortfolioBot.apply_trade(trade)` updates account; `JsonPortfolioStore.save_account(account)` persists to `data/portfolio/account_{account_id}.json`.
**Status**: IMPLEMENTED

### Decision 4: Clean Architecture in Bots
**Decision**: Business logic belongs inside bots. Orchestrator only coordinates workflow.
**Rationale**: Maintains separation of concerns. Each bot is independently testable. Rules like MaxDrawdownRiskRule, MaxPositionSizeRiskRule live in RiskBot, not orchestrator.
**Status**: ENFORCED

### Decision 5: Dependency Injection
**Decision**: All bot dependencies (sources, engines, stores) passed to constructors, not instantiated inside bots.
**Rationale**: Enables testing with mock implementations. Production and test code can inject different adapters.
**Status**: ENFORCED

### Decision 6: Data Persistence Locations
**Decision**: 
- Trades: `data/paper_trades/trades.jsonl`
- Portfolio: `data/portfolio/account_{account_id}.json`
- Default Account ID: `"paper"`

**Status**: IMPLEMENTED

## Phase 2: Dashboard Foundation

### Decision 7: Dashboard as Read-Only Service
**Decision**: DashboardService is read-only, exposes no side effects, uses existing persistent stores.
**Rationale**: Maintains separation of concerns. Dashboard queries existing Account and TradeRecord state without modifying orchestrator or bots.
**Implementation**: `DashboardService` loads from `JsonPortfolioStore` and `JsonTradeStore`, exposes view models (PortfolioOverview, PositionSnapshot, etc).
**Status**: IMPLEMENTED

### Decision 8: Flask REST API for Dashboard
**Decision**: Dashboard exposes Flask REST API with 6 JSON endpoints under `/api/v1/portfolio/`.
**Rationale**: Extensible foundation for future web UI. Can be extended with WebSocket, auth, multi-account support without modifying dashboard service.
**Implementation**: `api.py` creates Flask app; `DashboardService` handles business logic.
**Status**: IMPLEMENTED

### Decision 9: Backward Compatible Architecture
**Decision**: Phase 2 dashboard adds zero dependencies to Phase 1 bots or orchestrator.
**Rationale**: Dashboard is optional; core trading pipeline functions with or without it.
**Status**: IMPLEMENTED (import optional, no circular deps)

## Phase 3: Real Market Data (Started)

### Decision 10: Provider-Agnostic Architecture
**Decision**: Create `MarketDataProvider` protocol (extends `PriceSource`). Support:
  - **MockMarketDataProvider** (Phase 1 extended, backward compatible)
  - **KiteMarketDataProvider** (Phase 4, PRIMARY)
  - **AlphaVantageProvider** (Phase 3, optional fallback)
**Rationale**: Kite is primary (Phase 4) but Phase 3 should remain functional with a fallback provider. Provider factory pattern allows swapping provider implementations at instantiation without changing orchestrator or bots.
**Phase 4 Integration**: Change single line in factory config: `market_data_mode="kite"`. Zero orchestrator changes.
**Status**: STARTED

### Decision 11: Factory Pattern for Provider Selection
**Decision**: `ProviderFactory` selects implementations via `ProviderConfig` (environment-based).
**Rationale**: Enables running in different modes:
  - `HOKAGE_MARKET_DATA_MODE=mock` (default, tests)
  - `HOKAGE_MARKET_DATA_MODE=alpha-vantage` (Phase 3 fallback)
  - `HOKAGE_MARKET_DATA_MODE=kite` (Phase 4, production)
**Implementation**: `factory.py` creates providers; orchestrator imports factory, not providers directly.
**Status**: STARTED

### Decision 12: Tax Architecture (Interfaces Only)
**Decision**: Create `TaxProvider`, `TaxEvent`, `TaxLedger` interfaces and models in Phase 3. NO implementation yet.
**Rationale**: All future trades must be tax-compatible; deferring implementation to Phase 4+ is acceptable, but interfaces prevent migration issues later.
**Implementation**:
  - TaxEvent: models each trade as taxable event
  - TaxProvider: converts TradeRecord → TaxEvent
  - TaxLedger: persists events for reporting
  - Integration point: After ExecutionBot → before PortfolioBot
**Status**: STARTED

### Decision 13: AlphaVantage Deprioritized
**Decision**: AlphaVantage is an optional fallback provider and not the primary integration path.
**Rationale**: Kite-first architecture is the priority; AlphaVantage may be used only for local testing or Phase 3 temporary data.
**Status**: APPROVED

---

## Known Blockers

**Phase 1-2**: NONE ✅
**Phase 3**: Kite API credentials needed for Phase 4 (acceptable, can test with AlphaVantage first)

## Known Limitations (Acceptable)

**Phase 1-2:**
- ResearchBot uses DummyResearchSource (mock data)
- StrategyBot uses HeuristicStrategyGenerator (rule-based)
- BacktestBot uses HeuristicBacktestEngine (deterministic, not real historical)
- PriceSource uses MockPriceSource (static hardcoded prices)
- No real broker connection (approved for Phase 4)
- No tax tracking (approved for Phase 3+)
- No improvement loop (approved for Phase 5)

**Phase 3:**
- AlphaVantage free tier: 5 calls/min rate limit (acceptable, add caching)
- Need API key (free, requires signup)

**Phase 4+:**
- Kite integration requires Zerodha account + broker credentials
- Live execution requires additional gates (user confirmation, risk validation)

---

Last updated: 2026-06-21 (Phase 1+2 completion, Phase 3 design finalized)
