from __future__ import annotations


class KiteMarketDataProvider:
    """Primary Kite market data provider placeholder for Phase 4.

    This provider is the architecture placeholder for the future Zerodha/Kite
    integration. It is intentionally not wired by default in Phase 3A.
    """

    def __init__(self, api_key: str | None = None, access_token: str | None = None) -> None:
        self.api_key = api_key
        self.access_token = access_token

    def get_price(self, market: str) -> float:
        """Retrieve the latest market price for the requested instrument."""
        raise NotImplementedError(
            "KiteMarketDataProvider is a placeholder integration point. "
            "Implement Kite API access in Phase 4."
        )
