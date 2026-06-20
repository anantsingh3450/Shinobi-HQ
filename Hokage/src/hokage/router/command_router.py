"""Hokage command router — parses user intent and dispatches to the orchestrator.

Supports:
  help / ?              — list available commands
  research <topic>      — Research → Strategy pipeline (no execution)
  trade <topic>         — Research → Strategy → PaperExecution pipeline
  full-trade <topic>    — Research → Strategy → Backtest → PaperExecution pipeline
"""
from __future__ import annotations

from hokage.orchestrator.pipeline import HokageOrchestrator

_HELP_TEXT = """\
Available commands:
  research <topic>      — Run Research and Strategy pipeline, display StrategyProposal
  trade <topic>         — Run pipeline: Research → Strategy → Paper Trade execution
  full-trade <topic>    — Run full pipeline: Research → Strategy → Backtest → Paper Trade
  help / ?              — Show this help message
  exit / quit           — Exit Hokage Commander"""


class CommandRouter:
    """Parses user intent and routes commands to the appropriate orchestrator."""

    def __init__(self, orchestrator: HokageOrchestrator) -> None:
        """Initialize the router with an orchestrator instance."""
        self.orchestrator = orchestrator

    def handle_command(self, raw_input: str) -> str | dict:
        """Process a raw user command.

        Args:
            raw_input: Text entered by the user.

        Returns:
            A string message (for help/errors) or a dictionary for display.
        """
        cmd = raw_input.strip()
        if not cmd:
            return ""

        lower_cmd = cmd.lower()

        # Help
        if lower_cmd in ("help", "?"):
            return _HELP_TEXT

        # research <topic> — Research → Strategy only
        if lower_cmd == "research" or lower_cmd.startswith("research "):
            query = cmd[len("research"):].strip()
            if not query:
                return "Error: Please specify a topic. Usage: research <topic>"
            try:
                return self.orchestrator.execute_research_to_strategy(query)
            except Exception as exc:
                return f"Pipeline failed: {exc}"

        # trade <topic> — Research → Strategy → PaperExecution
        if lower_cmd == "trade" or lower_cmd.startswith("trade "):
            query = cmd[len("trade"):].strip()
            if not query:
                return "Error: Please specify a topic. Usage: trade <topic>"
            try:
                return self.orchestrator.execute_paper_trade(query)
            except Exception as exc:
                return f"Pipeline failed: {exc}"

        # full-trade <topic> — Research → Strategy → Backtest → PaperExecution
        if lower_cmd == "full-trade" or lower_cmd.startswith("full-trade "):
            query = cmd[len("full-trade"):].strip()
            if not query:
                return "Error: Please specify a topic. Usage: full-trade <topic>"
            try:
                return self.orchestrator.execute_full_pipeline(query)
            except Exception as exc:
                return f"Pipeline failed: {exc}"

        return f"Unknown command: '{cmd}'. Type 'help' for available commands."
