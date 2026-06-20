# Hokage Dashboard

Foundation for portfolio visualization and monitoring.

## Architecture

The dashboard module provides read-only access to portfolio data without modifying core bot logic.

```
DashboardService (read-only)
├── PortfolioOverview (equity, cash, positions count, returns)
├── OpenPositions (LONG/SHORT, entry price, PnL)
├── TradeHistory (execution details, strategy names)
└── AccountMetrics (return %, margin usage, win rate)

REST API (Flask)
├── GET /api/v1/portfolio/{account_id}/overview
├── GET /api/v1/portfolio/{account_id}/positions/open
├── GET /api/v1/portfolio/{account_id}/positions/all
├── GET /api/v1/portfolio/{account_id}/trades?limit=10
├── GET /api/v1/portfolio/{account_id}/metrics
└── GET /api/v1/health
```

## Usage

### As a Service (Python)

```python
from pathlib import Path
from hokage.dashboard.service import DashboardService
from bots.portfolio.store import JsonPortfolioStore
from bots.execution.store.json_trade_store import JsonTradeStore

service = DashboardService(
    JsonPortfolioStore(Path("data/portfolio")),
    JsonTradeStore(Path("data/paper_trades")),
)

overview = service.get_portfolio_overview("paper")
positions = service.get_open_positions("paper")
metrics = service.get_account_metrics("paper")
```

### As REST API (Flask)

```python
from hokage.dashboard.api import run_dashboard_api

run_dashboard_api(host="127.0.0.1", port=5000, debug=True)
```

Then access: `http://localhost:5000/api/v1/portfolio/paper/overview`

## Data Models

All endpoints return JSON with the following structures:

### PortfolioOverview
```json
{
  "account_id": "paper",
  "initial_balance": 10000.0,
  "current_equity": 10150.5,
  "cash": 8000.0,
  "total_realized_pnl": 50.5,
  "total_unrealized_pnl": 100.0,
  "open_positions_count": 2,
  "total_trades_count": 5,
  "return_percentage": 1.505,
  "last_updated": "2026-06-21T14:30:00.000000"
}
```

### PositionSnapshot
```json
{
  "position_id": "pos_001",
  "market": "EUR/USD",
  "direction": "LONG",
  "quantity": 100.0,
  "entry_price": 1.0850,
  "current_price": 1.0900,
  "unrealized_pnl": 500.0,
  "realized_pnl": 0.0,
  "status": "OPEN"
}
```

### TradeSnapshot
```json
{
  "trade_id": "trade_001",
  "proposal_id": "prop_001",
  "market": "EUR/USD",
  "direction": "LONG",
  "quantity": 100.0,
  "entry_price": 1.0850,
  "status": "OPEN",
  "mode": "PAPER",
  "strategy_name": "Momentum Strategy",
  "executed_at": "2026-06-21T14:00:00.000000"
}
```

### AccountMetrics
```json
{
  "account_id": "paper",
  "equity": 10150.5,
  "cash": 8000.0,
  "margin_used": 2150.5,
  "margin_available": -150.5,
  "total_return": 150.5,
  "return_percentage": 1.505,
  "sharpe_ratio": null,
  "win_rate": null,
  "profit_factor": null,
  "max_drawdown": null
}
```

## Phase 2 Scope

✅ Portfolio overview endpoint
✅ Open positions view endpoint
✅ Trade history endpoint
✅ Account metrics endpoint
✅ Clean service architecture (read-only, no side effects)
✅ DashboardService interface for Python consumers
✅ Flask REST API for web frontend

## Future (Phase 3+)

- Real market data integration (update current_price)
- Historical backtest metrics (sharpe_ratio, win_rate, profit_factor, max_drawdown)
- Performance analytics
- Web dashboard UI
- WebSocket for real-time updates
