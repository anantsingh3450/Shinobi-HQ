from __future__ import annotations

# Deterministic price table for common markets.
# Keys are upper-cased market identifiers.
_PRICE_TABLE: dict[str, float] = {
    "EUR/USD":  1.0850,
    "GBP/USD":  1.2700,
    "USD/JPY":  157.50,
    "USD/INR":  83.50,
    "BTC/USD":  65_000.00,
    "ETH/USD":  3_500.00,
    "NIFTY":    22_500.00,
    "SENSEX":   74_000.00,
    "RELIANCE": 2_950.00,
    "TCS":      4_100.00,
    "GOLD":     2_350.00,
    "CRUDE":    78.50,
}

_DEFAULT_PRICE = 100.0


class MockMarketDataProvider:
    """Mock market data provider for deterministic local testing."""

    def get_price(self, market: str) -> float:
        """Return a deterministic price for the specified market."""
        return _PRICE_TABLE.get(market.upper().strip(), _DEFAULT_PRICE)
