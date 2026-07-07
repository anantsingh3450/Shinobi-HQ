"""Execution Friction Model for simulated execution realism.

Defines the pluggable friction model interface, profiles, and parameter sets.
"""
from __future__ import annotations

import hashlib
import random
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any

from bots.execution.interfaces import PriceSource
from bots.execution.models import TradeDirection


class FrictionProfile(Enum):
    """Supported execution realism profiles."""

    ZERO = "ZERO"
    LIGHT = "LIGHT"
    NSE_EQUITY = "NSE_EQUITY"
    NSE_FNO = "NSE_FNO"
    CRYPTO = "CRYPTO"
    STRESS = "STRESS"


# Param mapping:
# (spread_pct, base_slippage_pct, volatility_coeff, qty_threshold, partial_chance, min_fill_pct, min_lat, max_lat)
PROFILE_PARAMS = {
    FrictionProfile.ZERO: {
        "spread_pct": 0.0,
        "base_slippage_pct": 0.0,
        "volatility_coeff": 0.0,
        "qty_threshold": float("inf"),
        "partial_chance": 0.0,
        "min_fill_pct": 100.0,
        "min_latency_ms": 0.0,
        "max_latency_ms": 0.0,
    },
    FrictionProfile.LIGHT: {
        "spread_pct": 0.01,
        "base_slippage_pct": 0.01,
        "volatility_coeff": 0.05,
        "qty_threshold": 1000.0,
        "partial_chance": 0.0,
        "min_fill_pct": 100.0,
        "min_latency_ms": 10.0,
        "max_latency_ms": 30.0,
    },
    FrictionProfile.NSE_EQUITY: {
        "spread_pct": 0.02,
        "base_slippage_pct": 0.03,
        "volatility_coeff": 0.1,
        "qty_threshold": 500.0,
        "partial_chance": 0.05,
        "min_fill_pct": 80.0,
        "min_latency_ms": 20.0,
        "max_latency_ms": 80.0,
    },
    FrictionProfile.NSE_FNO: {
        "spread_pct": 0.01,
        "base_slippage_pct": 0.02,
        "volatility_coeff": 0.08,
        "qty_threshold": 1000.0,
        "partial_chance": 0.02,
        "min_fill_pct": 90.0,
        "min_latency_ms": 15.0,
        "max_latency_ms": 50.0,
    },
    FrictionProfile.CRYPTO: {
        "spread_pct": 0.05,
        "base_slippage_pct": 0.08,
        "volatility_coeff": 0.2,
        "qty_threshold": 10.0,
        "partial_chance": 0.15,
        "min_fill_pct": 70.0,
        "min_latency_ms": 50.0,
        "max_latency_ms": 200.0,
    },
    FrictionProfile.STRESS: {
        "spread_pct": 0.15,
        "base_slippage_pct": 0.25,
        "volatility_coeff": 0.5,
        "qty_threshold": 100.0,
        "partial_chance": 0.40,
        "min_fill_pct": 30.0,
        "min_latency_ms": 150.0,
        "max_latency_ms": 500.0,
    },
}


class ExecutionFrictionModel(ABC):
    """Abstract base class for all execution friction models."""

    @abstractmethod
    def apply_friction(
        self,
        market: str,
        direction: TradeDirection,
        quantity: float,
        mid_price: float,
        market_volatility: float = 0.0,
    ) -> dict[str, Any]:
        """Apply market friction and return execution metrics."""
        pass


class ZeroFrictionModel(ExecutionFrictionModel):
    """Simplest friction model that performs zero execution adjustment."""

    def apply_friction(
        self,
        market: str,
        direction: TradeDirection,
        quantity: float,
        mid_price: float,
        market_volatility: float = 0.0,
    ) -> dict[str, Any]:
        return {
            "fill_price": mid_price,
            "filled_quantity": quantity,
            "slippage_price": 0.0,
            "slippage_pct": 0.0,
            "latency_ms": 0.0,
        }


class ProfiledFrictionModel(ExecutionFrictionModel):
    """Friction model driven by configurable execution profiles."""

    def __init__(self, profile: FrictionProfile = FrictionProfile.ZERO) -> None:
        """Initialize with selected execution profile."""
        self.profile = profile
        self.params = PROFILE_PARAMS[profile]

    def apply_friction(
        self,
        market: str,
        direction: TradeDirection,
        quantity: float,
        mid_price: float,
        market_volatility: float = 0.0,
    ) -> dict[str, Any]:
        # 1. Create a local deterministic random generator seeded by trade inputs
        seed_str = f"{market}:{quantity}:{direction.value}:{mid_price}:{market_volatility}"
        seed_hash = int(hashlib.sha256(seed_str.encode()).hexdigest()[:8], 16)
        rng = random.Random(seed_hash)

        # 2. Extract parameters
        spread_pct = self.params["spread_pct"]
        base_slippage_pct = self.params["base_slippage_pct"]
        vol_coeff = self.params["volatility_coeff"]
        qty_thresh = self.params["qty_threshold"]
        partial_chance = self.params["partial_chance"]
        min_fill = self.params["min_fill_pct"]
        min_lat = self.params["min_latency_ms"]
        max_lat = self.params["max_latency_ms"]

        # 3. Volatility-aware slippage calculation
        # Slippage % = Base % + Coefficient * Market Volatility
        slippage_pct = base_slippage_pct + vol_coeff * market_volatility

        # 4. Latency simulation (purely numerical - do not block thread)
        if max_lat > min_lat:
            latency_ms = rng.uniform(min_lat, max_lat)
        else:
            latency_ms = min_lat
        latency_ms = round(latency_ms, 2)

        # 5. Partial fill simulation
        filled_qty = quantity
        if quantity > qty_thresh and partial_chance > 0.0:
            if rng.random() < partial_chance:
                # Determine fill percentage
                fill_ratio = rng.uniform(min_fill / 100.0, 0.99)
                filled_qty = round(quantity * fill_ratio, 4)

        # 6. Apply spread & slippage to mid price
        # Buy executes at Ask (mid + spread/2) + slippage
        # Sell executes at Bid (mid - spread/2) - slippage
        half_spread_pct = spread_pct / 2.0
        total_friction_pct = slippage_pct + half_spread_pct

        if direction == TradeDirection.LONG:
            fill_price = mid_price * (1.0 + total_friction_pct / 100.0)
            slippage_price = fill_price - mid_price
        else:
            fill_price = mid_price * (1.0 - total_friction_pct / 100.0)
            slippage_price = mid_price - fill_price

        # Guarantee positive values
        fill_price = max(0.0001, round(fill_price, 6))
        slippage_price = round(slippage_price, 6)
        slippage_pct_realized = round((slippage_price / mid_price) * 100.0, 4) if mid_price > 0 else 0.0

        return {
            "fill_price": fill_price,
            "filled_quantity": filled_qty,
            "slippage_price": slippage_price,
            "slippage_pct": slippage_pct_realized,
            "latency_ms": latency_ms,
        }


def get_market_volatility(price_source: PriceSource, market: str) -> float:
    """Determine current market volatility.

    Retrieves historical candles from the price source if supported.
    Otherwise falls back to spread metrics or a default baseline.
    """
    if hasattr(price_source, "get_historical_candles"):
        from datetime import datetime, timedelta, timezone
        from integrations.data.models import HistoricalDataRequest

        try:
            req = HistoricalDataRequest(
                symbol=market,
                timeframe="1m",
                start_time=datetime.now(timezone.utc) - timedelta(minutes=15),
                end_time=datetime.now(timezone.utc),
                limit=10,
            )
            res = price_source.get_historical_candles(req)
            if res and res.candles:
                closes = [c.close for c in res.candles]
                if len(closes) > 1:
                    mean = sum(closes) / len(closes)
                    var = sum((x - mean) ** 2 for x in closes) / (len(closes) - 1)
                    std_dev = var**0.5
                    # Percentage volatility
                    vol = (std_dev / mean) * 100.0 if mean > 0 else 0.0
                    return round(vol, 4)
        except Exception:
            pass

    if hasattr(price_source, "get_quote"):
        try:
            quote = price_source.get_quote(market)
            if quote and quote.bid is not None and quote.ask is not None and quote.price > 0:
                spread_pct = ((quote.ask - quote.bid) / quote.price) * 100.0
                return round(spread_pct, 4)
        except Exception:
            pass

    # Default baseline volatility percentage (0.15%)
    return 0.15


def resolve_active_friction_profile(resolver: Any = None) -> FrictionProfile:
    """Dynamically resolve the active friction profile.

    Checks:
    1. The environment variable 'HOKAGE_FRICTION_PROFILE'
    2. The 'friction_profile' key inside commander_profile.json
    3. Falls back to FrictionProfile.NSE_EQUITY as the standard realistic default.
    """
    import os

    # 1. Check environment variable
    env_val = os.environ.get("HOKAGE_FRICTION_PROFILE")
    if env_val:
        try:
            return FrictionProfile(env_val.upper())
        except ValueError:
            pass

    # 2. Check commander_profile.json
    if resolver is not None:
        try:
            profile_path = resolver.resolve_profile_path()
            if profile_path.exists():
                import json
                with open(profile_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    profile_val = data.get("friction_profile") or data.get("environment", {}).get("friction_profile")
                    if profile_val:
                        return FrictionProfile(profile_val.upper())
        except Exception:
            pass

    # 3. Default fallback (preserves 100% backward compatibility)
    return FrictionProfile.ZERO
