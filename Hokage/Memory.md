# Hokage Project Memory

**Purpose**: This is the canonical long-term project memory document. It ensures session continuity by providing all the necessary context, architectural boundaries, and historical decisions required for a completely new AI agent to seamlessly resume development on the Hokage project.

---

## 1. Project Mission
Build a self-improving AI command system capable of orchestrating autonomous research, trading intelligence, and execution. 
**Hokage** acts as the central commander and sole user interface. It manages a specialized fleet of bots, routes tasks, tracks project progress, and maintains the overall memory structure. 

## 2. Architectural Principles
1. **Centralized Commander**: Users interact *only* with the Hokage Commander (via CLI, Telegram, or Web APIs). Specialist bots do not talk to the user.
2. **Clean Architecture & Dependency Inversion**: Core business logic (like heuristic parsing or LLM prompting) must be decoupled from the bot classes themselves. Bots should accept their logic engines via constructor injection (e.g., injecting a `StrategyGenerator` into `StrategyBot`).
3. **Data Structure Handoffs**: Bots communicate by passing pure, strongly-typed data models (e.g., `ResearchReport`, `StrategyProposal`).
4. **Provenance & Auditability**: Every decision, rule, and strategy must be traceable back to its source intelligence. Models explicitly track `sources_cited`.

## 3. Current Implementation Status
- **Hokage Commander MVP**: Live and functional. Contains `HokageOrchestrator`, `CommandRouter`, and a `HokageCLI` REPL interface.
- **ResearchBot**: Implemented. Queries sources and synthesizes a structured `ResearchReport`. Currently wired to a mock `DummyResearchSource`.
- **StrategyBot**: Upgraded and functional. Uses a dynamically injected `HeuristicStrategyGenerator` to formulate trading rules directly from `ResearchReport` findings.

## 4. Completed Phases
- **Foundation Phase**: GitHub, Obsidian, and folder structure scaffolded.
- **Research Bot Implementation**: Interfaces and domain models established.
- **Commander MVP**: Local end-to-end pipeline orchestration verified via CLI.
- **StrategyBot Upgrade**: Hardcoded stubs removed; dependency injection and provenance tracking introduced.
- **Execution Bot (Paper Trading)**: Complete simulated trading loop, local persistence, command router updates (`trade` command), and robust unit & integration tests.

## 5. Pending Phases
- **Backtest Bot**: Validate generated strategies against historical data.
- **Risk Bot**: Pre-execution risk assessment and strict gate enforcement.
- **Execution Bot (Paper)**: Execute validated strategies in simulated markets.
- **Execution Bot (Live)**: Execute strategies with real capital, protected by Hokage-enforced Live Gates (User confirmation, Risk check, Broker check).
- **Improvement Bot**: Analyze execution/backtest logs to refine future research and strategies.
- **LLM Integrations**: Upgrade heuristic adapters to use actual LLMs for deep semantic parsing.

## 6. Key Decisions Taken
- **Pipeline Flow**: The explicit pipeline order is rigidly defined as: `Research -> Strategy -> Backtest -> Risk -> Execution -> Improvement`.
- **StrategyGenerator Abstraction**: We explicitly decided not to place LLM or heuristic logic inside `StrategyBot`. By abstracting it to `StrategyGenerator`, we can easily swap test adapters for production LLMs later.
- **Portfolio Manager Deferred**: Portfolio Manager is categorized as a future enhancement and intentionally removed from the v1 active pipeline to maintain focus on single-strategy loop completion.

## 7. Candidate Future Domain Models
As the intelligence engine scales, we have identified the need to split `StrategyProposal` generation into finer domain objects:
- **`MarketAssessment`**: To structure raw text analysis (trend, sentiment, volatility scores).
- **`TradeIdea`**: A simple precursor hypothesis before full strategy rule formulation.
- **`RiskProfile`**: A structured risk object (`max_drawdown_pct`, `r_multiple`) replacing arbitrary string rules for Backtest/Risk bot consumption.
- **`Signal`**: Discrete machine-readable commands (timestamp, asset, direction, magnitude) consumed directly by the `ExecutionBot`.

## 8. Important Lessons Learned
- **Brittle Heuristics**: Pure keyword-matching heuristics (e.g., identifying "volatility") are context-blind and fragile. An eventual transition to `LLMStrategyGenerator` is mandatory for robust semantic intelligence.
- **Pipeline Testing**: Injecting dummy data sources (`DummyResearchSource`) is highly effective for building and verifying the orchestrator pipeline without incurring API costs or dealing with external latency.

## 9. Constraints and Non-Goals
- **Constraints**: 
  - Must preserve backward compatibility when swapping out injected generators.
  - All outputs must maintain strict traceability back to the original source.
- **Non-Goals**: 
  - Building proprietary charting UIs (we rely on existing interfaces).
  - Building the Portfolio Manager prior to completing the core pipeline.
  - Allowing bots to independently solicit user input bypassing the Hokage router.

## 10. Future Roadmap
1. **Next Immediate Target**: Implement the **Backtest Bot** to close the loop on Strategy validation.
2. **Followed by**: Implement Risk Bot.
3. **Followed by**: Implement Execution Bot (Paper mode).
4. **Followed by**: Upgrade `HeuristicStrategyGenerator` to `LLMStrategyGenerator`.
5. **Final v1 Steps**: Enable Live Execution and Improvement Bot feedback loop.
