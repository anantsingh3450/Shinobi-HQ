# Interface

User-facing entry points. All channels normalize into Hokage commands.

Channels:

- `telegram/` — primary mobile interface
- `cli/` — local development and debugging
- `api/` — optional HTTP/WebSocket for automation

The user never bypasses Hokage to reach a bot directly.

## Implementation
The interactive CLI environment is implemented in `cli.py` which runs a REPL shell supporting system commands.
