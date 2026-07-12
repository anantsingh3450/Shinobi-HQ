from __future__ import annotations


from hokage.orchestrator.pipeline import HokageOrchestrator
from hokage.router.command_router import CommandRouter


class HokageCLI:
    """Command-line interface for the Hokage Commander."""

    def __init__(self) -> None:
        """Initialize CLI with router and orchestrator."""
        self.orchestrator = HokageOrchestrator()
        self.router = CommandRouter(self.orchestrator)

    def run(self) -> None:
        """Start the REPL loop."""
        print(self.router.handle_hokage_greet())
        print("Type 'help' for commands, 'exit' or 'quit' to leave.\n")

        while True:
            try:
                user_input = input("hokage> ")
            except (KeyboardInterrupt, EOFError):
                print("\nExiting Hokage Commander.")
                break

            cmd = user_input.strip()
            if cmd.lower() in ("exit", "quit"):
                print("Exiting Hokage Commander.")
                break

            if not cmd:
                continue

            result = self.router.handle_command(cmd)

            if isinstance(result, str):
                print(result)
            elif isinstance(result, dict):
                # Format output depending on type
                if "trade_id" in result:
                    print("\n--- Executed Paper Trade ---")
                else:
                    print("\n--- Strategy Proposal ---")
                for key, value in result.items():
                    print(f"{key.replace('_', ' ').title()}: {value}")
                print("-------------------------\n")
            else:
                print(f"Unexpected result: {result}")

if __name__ == "__main__":
    cli = HokageCLI()
    cli.run()
