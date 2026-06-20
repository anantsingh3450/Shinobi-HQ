# Hokage Project Status

## Active Phase: MVP Integration

### Completed
- Core architecture documented and planned.
- `ResearchBot` domain models and orchestration implemented.
- `DummyResearchSource` integrated for testing.
- Hokage Commander MVP:
  - `HokageOrchestrator` implemented (`src/hokage/orchestrator/`).
  - `CommandRouter` implemented (`src/hokage/router/`).
  - `HokageCLI` implemented (`src/hokage/interface/`).
  - Core pipeline `Research -> Strategy` connected.
- End-to-end local testing execution via CLI enabled.

### Pending
- Implement `BacktestBot`.
- Implement `RiskBot`.
- Implement `ExecutionBot` (Paper).
- Connect `StrategyBot` real output logic (currently using stub).
- Implement `ImprovementBot`.
- Expand user interface to Telegram / Web APIs.
