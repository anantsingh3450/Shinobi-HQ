# Integration Tests

End-to-end workflow tests:

- Research → Strategy → Backtest → Risk → Execution (paper) pipeline
- Risk gate blocks execution on fail
- Paper execution with shared engine
- Live gate enforcement — block live without:
  - user confirmation
  - risk validation pass
  - broker connectivity validation
- Paper-before-live promotion path

No tests yet.
