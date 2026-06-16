# Runbooks

Operational guides for running Hokage in development and production.

Planned runbooks:

- Starting and stopping Hokage
- Promoting Execution Bot from paper to live (three-gate checklist)
- Risk limit review and override policy
- Recovery after failure
- Rotating API keys and broker credentials

## Live promotion checklist (planned)

All steps go through Hokage. User never contacts Execution Bot or broker directly.

1. Confirm paper trading period completed and Improvement loop satisfied
2. Request live mode via Hokage
3. Provide **user confirmation** when prompted
4. Verify **Risk Bot** returns live pass
5. Verify **broker connectivity** check succeeds
6. Hokage activates live adapter; monitor via Hokage status commands

No runbooks written yet.
