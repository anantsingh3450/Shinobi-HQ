# Strategy Bot

Translates research into executable strategy specifications.

## Inputs

- Research Bot artifacts
- Risk and constraint parameters from Hokage / user

## Outputs

- Strategy spec (rules, parameters, universe, timeframe)
- Consumed by Backtest Bot; reaches Execution Bot after Risk gate pass

## Implementation
The Strategy Bot is implemented in `strategy_bot.py`. It uses a strategy generator interface (`interfaces.py`, `generators.py`) to formulate a structured `StrategyProposal`.
