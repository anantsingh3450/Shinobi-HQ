# Autonomous Trading Bot Submodule

The `autonomous` bot submodule implements Hokage's background scheduler, exit monitor, entry scanner, and daily briefings compiler.

## Configuration Parameters

Parameters are configured in `brain.json` under the `"autonomous"` config object or passed directly during instantiation:

*   `scan_interval_seconds`: Number of seconds between scan loops (default: `60` seconds).
*   `tsl_percent`: Percentage threshold for trailing stop-loss exits (e.g. `0.05` for 5%).
*   `tp_percent`: Percentage threshold for take-profit exits (e.g. `0.10` for 10%).

## Active Positions Tracking

Active position trailing thresholds are dynamically persisted inside `hokage_brain/autonomous/active_positions.json` to prevent state loss on system restarts.

## Briefing Reports

Reports are stored inside the brain root:
- `hokage_brain/reports/daily_YYYY-MM-DD.json`
