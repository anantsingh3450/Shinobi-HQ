# Strategy Engine

Shared core used by both paper and live execution.

Responsibilities (planned):

- Load strategy spec
- Generate signals on each bar/tick
- Apply position sizing and risk rules
- Emit order intents (not broker-specific)

Paper and live adapters in sibling folders consume these intents.

No code yet.
