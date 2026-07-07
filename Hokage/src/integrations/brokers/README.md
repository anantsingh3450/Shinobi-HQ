# Broker Integrations

Live execution only. Paper mode does not use this folder.

One subfolder per broker:

- `zerodha/`
- `alpaca/`
- ...

Each implements a common broker interface consumed by `bots/execution/live/`.

## Implementation
The Kite (Zerodha) market data provider scaffolding exists in `kite_market_data_provider.py` which serves as a mock integration point for broker market data and connections.
