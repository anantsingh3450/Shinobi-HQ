from __future__ import annotations

from typing import Any, Protocol, runtime_checkable
from datetime import datetime


@runtime_checkable
class BrokerAdapter(Protocol):
    """Interface for future broker providers (e.g. Zerodha, AngelOne, Interactive Brokers)."""
    
    def connect(self) -> bool:
        """Establish connection with the broker."""
        ...
        
    def get_profile(self) -> dict[str, Any]:
        """Retrieve broker account profile."""
        ...
        
    def place_order(self, symbol: str, transaction_type: str, quantity: int, order_type: str, price: float | None = None) -> str:
        """Place an order and return the order ID."""
        ...
        
    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order."""
        ...
        
    def get_order_status(self, order_id: str) -> str:
        """Retrieve current status of an order."""
        ...


@runtime_checkable
class ExchangeAdapter(Protocol):
    """Interface for future exchange interfaces (e.g. NSE, BSE, MCX, Binance)."""
    
    def get_instrument_details(self, symbol: str) -> dict[str, Any]:
        """Retrieve instrument specifications and margins."""
        ...
        
    def is_market_open(self) -> bool:
        """Check if the exchange market is currently open."""
        ...


@runtime_checkable
class LLMAdapter(Protocol):
    """Interface for future LLM providers (e.g. Gemini, OpenAI, Claude, local models)."""
    
    def generate_text(self, prompt: str, system_instruction: str | None = None) -> str:
        """Generate text based on a prompt."""
        ...
        
    def generate_structured(self, prompt: str, schema: dict[str, Any], system_instruction: str | None = None) -> dict[str, Any]:
        """Generate structured JSON matching the provided schema."""
        ...


@runtime_checkable
class MarketDataAdapter(Protocol):
    """Interface for future market data providers (e.g. Yahoo Finance, Bloomberg, Kite Ticker)."""
    
    def fetch_quotes(self, symbols: list[str]) -> dict[str, dict[str, Any]]:
        """Fetch real-time quotes for a list of symbols."""
        ...
        
    def fetch_historical_candles(self, symbol: str, interval: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
        """Fetch historical candle data."""
        ...


@runtime_checkable
class NotificationAdapter(Protocol):
    """Interface for future notification systems (e.g. Telegram, Email, Slack, SMS)."""
    
    def send_message(self, target: str, message: str, priority: str = "NORMAL") -> bool:
        """Send a notification message to a target channel."""
        ...


@runtime_checkable
class StorageAdapter(Protocol):
    """Interface for future storage backends (e.g. S3, GCS, local files, PostgreSQL)."""
    
    def save_object(self, key: str, data: bytes) -> bool:
        """Save raw bytes data under a key."""
        ...
        
    def load_object(self, key: str) -> bytes | None:
        """Retrieve raw bytes data for a key."""
        ...
        
    def delete_object(self, key: str) -> bool:
        """Delete data under a key."""
        ...
