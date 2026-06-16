# Live Trading Adapter

Executes real orders through a broker integration.

- Receives order intents from `engine/` (same engine as paper)
- Routes to broker via `integrations/brokers/`
- Logs all fills and positions → `data/execution/live/`

## Live activation prerequisites

Hokage must verify **all three** gates before this adapter is activated. The user never enables live mode directly — only via Hokage.

| Gate | Enforced by | Requirement |
|------|-------------|-------------|
| User confirmation | Hokage | Explicit user approval through Hokage interface |
| Risk validation | Risk Bot (via Hokage) | Live re-assessment returns **pass** |
| Broker connectivity | Hokage + `integrations/brokers/` | Connection to configured broker verified successfully |

If any gate fails, Hokage blocks activation and reports the failure reason to the user.

No code yet.
