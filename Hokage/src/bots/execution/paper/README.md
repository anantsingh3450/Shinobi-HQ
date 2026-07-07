# Paper Trading Adapter

Simulates order execution without connecting to a live broker.

- Receives order intents from `engine/`
- Applies simulated slippage and fees (configurable)
- Maintains virtual portfolio via the Portfolio Bot → `data/portfolio/`

Activated by Hokage command: paper mode (default post-backtest path).

## Implementation
Paper trading is fully supported using `PaperEngine` under `engine/paper_engine.py` which interfaces with `JsonTradeStore` (`store/json_trade_store.py`) to record trade data.
