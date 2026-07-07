# Integrations

Adapters to external systems. Bots depend on integrations; integrations do not depend on bots.

## Submodules

| Folder | Purpose | Status |
|--------|---------|--------|
| `brokers/` | Live broker APIs (Zerodha, Alpaca, etc.) | Placeholder (`kite_market_data_provider.py`) |
| `data/` | Market data providers (mock + factory) | **Implemented** |
| `tax/` | Simulated tax event generation and ledger | **Implemented** |
| `llm/` | LLM provider abstraction | Placeholder |
| `telegram/` | Telegram Bot API wrapper | Placeholder |
| `obsidian/` | Optional sync with Knowledge vault | Placeholder |
