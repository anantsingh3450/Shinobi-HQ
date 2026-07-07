# Bot Relationships

## Hokage (Commander)

- **Sole interface to the user** — all commands and responses flow through Hokage
- Routes commands to the correct bot
- Maintains session memory and mission context
- Enforces workflow gates (Risk pass before execution, paper before live)
- Orchestrates live promotion gates:
  1. Collects **user confirmation**
  2. Requests **risk validation** from Risk Bot
  3. Runs **broker connectivity validation** via broker integrations
- Blocks live execution if any gate fails; reports reason to user

## Research Bot

- Input: user questions (via Hokage), market topics, prior improvement notes
- Output: research reports, structured findings
- Feeds: Strategy Bot

## Strategy Bot

- Input: research artifacts, constraints, risk parameters
- Output: strategy specifications (rules, parameters, universe)
- Feeds: Backtest Bot

## Backtest Bot

- Input: strategy spec, historical data
- Output: backtest reports, metrics, equity curves
- Feeds: Risk Bot, Improvement Bot

## Risk Bot

- Input: strategy spec, backtest results, configured risk limits, current portfolio context (provided by Portfolio Bot)
- Output: risk assessment report, pass/fail verdict → `data/risk/`
- Feeds: Execution Bot (paper and live gates)
- **Paper gate** — must pass before paper execution begins
- **Live gate** — must re-validate before live execution; invoked by Hokage during live promotion

## Execution Bot

- Input: strategy spec, Risk Bot pass verdict, mode command from Hokage
- **Shared strategy engine** — one engine, two modes
- **Paper mode** — simulated fills, no real capital
- **Live mode** — real broker connection, same strategy logic; only after all three live gates pass
- Feeds: Improvement Bot

## Improvement Bot

- Input: backtest results, risk assessments, paper/live performance, logs
- Output: improvement proposals, parameter suggestions, lessons learned
- Feeds: Research Bot, Strategy Bot (closes the loop)

## Portfolio Bot

- **Active in the pipeline** — tracks real-time account balances, cash, realized/unrealized PnL, and open positions.
- Core role: updates and persists the account state (`account_paper.json`) after each trade executed by the Execution Bot.
- Integrates with the CLI command router to serve portfolio overview and holdings/positions details.
