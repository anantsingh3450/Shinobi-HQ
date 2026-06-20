from __future__ import annotations

import sys

from hokage.interface.cli import HokageCLI


def main() -> None:
    """Entry point for the Hokage Commander application."""
    cli = HokageCLI()
    try:
        cli.run()
    except Exception as e:
        print(f"Fatal error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
