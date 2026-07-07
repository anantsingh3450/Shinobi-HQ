"""Conversation simulation script.

Demonstrates Step 5 of Phase 9.3:
Runs 5 consecutive queries from Elder Anant and prints Hokage's natural replies.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Add src/ to python path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from hokage.orchestrator.pipeline import HokageOrchestrator
from hokage.router.command_router import CommandRouter


def run_conversation() -> None:
    orchestrator = HokageOrchestrator()
    router = CommandRouter(orchestrator)

    conversation = [
        "Hokage, good morning.",
        "Hokage, what's today's market outlook?",
        "Hokage, scan today's opportunities.",
        "Hokage, explain your best recommendation.",
        "Hokage, why did the committee approve it?"
    ]

    for query in conversation:
        print(f"\nCommander: {query}")
        result = router.handle_command(query)
        print("Hokage:")
        if isinstance(result, str):
            print(result)
        elif isinstance(result, dict):
            for k, v in result.items():
                print(f"  {k.replace('_', ' ').title()}: {v}")
        elif isinstance(result, list):
            for item in result:
                print(f"  {item}")
        else:
            print(result)


if __name__ == "__main__":
    run_conversation()
