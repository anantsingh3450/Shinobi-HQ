# Hokage Tasks

Tracks all development tasks by phase.

## Phase 1: Core Bot Ecosystem (COMPLETE)
- [x] Implement core bots (`ResearchBot`, `StrategyBot`, `BacktestBot`, `RiskBot`, `ExecutionBot`, `PortfolioBot`).
- [x] Integrate `DummyResearchSource` for mock data.
- [x] Implement `HeuristicStrategyGenerator` and win-rate gating.
- [x] Create trade/portfolio JSON storage and `HokageOrchestrator`.
- [x] Build command router CLI REPL shell.

## Phase 2: Dashboard Foundation (COMPLETE)
- [x] Implement read-only `DashboardService` and Flask REST API under `/api/v1`.
- [x] Verify complete architecture isolation.

## Phase 3A: Provider & Tax Architecture (COMPLETE)
- [x] Define provider interfaces and models.
- [x] Create `ProviderFactory` and config loader.
- [x] Implement `MockMarketDataProvider` price feeds and daily candles.
- [x] Implement `HistoricalBacktestEngine` and `JsonPredictionLedger`.
- [x] Implement `SimulatedTaxProvider` and `JsonTaxLedger`.

## Phase 3B: Interactive CLI Commands & Sandbox Prep (COMPLETE)
- [x] Extend CLI command router for portfolio holdings and active positions.
- [x] Extend CLI commands for predictions and tax summaries.
- [x] Scaffold `config/kite_sandbox.json` credential templates.

## Phase 4: Production Broker Integration (PENDING)
- [ ] Implement Zerodha/Kite API connections for market data and order placement.
- [ ] Set up secure OAuth flows and token persistence.
- [ ] Enforce multi-factor Live Gates and broker capital checks.

## Phase 5: Self-Improving Loop (PENDING)
- [ ] Implement `ImprovementBot` analyzing logs to adjust strategy parameters.
