# Strategy Engine

Shared core used by both paper and live execution.

Responsibilities:

- Load strategy spec
- Generate signals on each bar/tick
- Apply position sizing and risk rules
- Emit order intents (not broker-specific)

Paper and live adapters in sibling folders consume these intents.

## Implementation
The Execution Engine is implemented in `paper_engine.py`. It obtains market quotes, executes fills, and records trades to the local JSON store (`trades.jsonl`).
