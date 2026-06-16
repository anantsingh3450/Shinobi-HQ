# Configuration

Central configuration for Hokage and all bots.

| File / Folder | Purpose |
|---------------|---------|
| `hokage.yaml` | Master settings — pipeline order, live gates, logging, default modes |
| `bots/` | Per-bot configuration overrides |
| `.env.example` | Secret placeholders (API keys, broker tokens) — copy to `.env` |

Secrets never committed. Use `.env` locally (gitignored).
