"""Mock price source — implements PriceSource for MVP paper trading.

Returns deterministic prices based on the market symbol so that test output
is reproducible. The same market always returns the same price across runs.

This is a temporary adapter. Replace with KitePriceSource (Zerodha) when
live market data integration is ready — PaperEngine requires no changes.
"""
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


class MockPriceSource:
    """Returns deterministic prices for known markets; defaults to 100.0.

    Implements the PriceSource protocol without importing it explicitly,
    keeping this adapter dependency-free for easy testing.

    Example:
        >>> src = MockPriceSource()
        >>> src.get_price("EUR/USD")
        1.085
    """

    def get_price(self, market: str) -> float:
        """Return the mock price for the given market symbol.

        Args:
            market: Instrument identifier (e.g. ``"EUR/USD"``).
                    Matching is case-insensitive.

        Returns:
            A deterministic float price. Falls back to 100.0 for unknown markets.
        """
        return _PRICE_TABLE.get(market.upper().strip(), _DEFAULT_PRICE)
