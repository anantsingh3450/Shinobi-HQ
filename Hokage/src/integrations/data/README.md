# Data Integrations

Market data provider adapters used by Research, Backtest, and Execution bots.

## Implementation
Data integration interfaces and providers are fully implemented. `MockMarketDataProvider` generates daily candle data and simulated quotes, and is instantiated dynamically by `ProviderFactory` under `factory.py`.
