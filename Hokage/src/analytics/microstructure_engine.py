import collections
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from integrations.data.models import MarketQuote

logger = logging.getLogger(__name__)


@dataclass
class MicrostructureFeatures:
    """Contains derived microstructure analytics for a symbol."""
    symbol: str
    timestamp: datetime
    current_price: float
    rolling_volume_delta: float
    cumulative_volume_delta: float
    fractionally_differentiated_price: float | None
    wyckoff_spring_detected: bool
    institutional_absorption_detected: bool


class MicrostructureEngine:
    """
    Ingests tick-level MarketQuote data to synthesize institutional 
    order-flow metrics and detect structural anomalies like 
    Wyckoff Springs and Institutional Absorption.
    """

    def __init__(self, d_coeff: float = 0.5, delta_window_minutes: float = 5.0, weight_threshold: float = 1e-4) -> None:
        """
        Args:
            d_coeff: The fractional differentiation coefficient (default 0.5).
            delta_window_minutes: Time window for rolling volume delta aggregation.
            weight_threshold: Cutoff threshold for fractional diff weights to prevent infinite memory leakage.
        """
        self.d_coeff = d_coeff
        self.delta_window_minutes = delta_window_minutes
        self.weight_threshold = weight_threshold
        
        # State tracking per symbol
        self._quotes: dict[str, collections.deque[MarketQuote]] = collections.defaultdict(collections.deque)
        self._cvds: dict[str, float] = collections.defaultdict(float)
        
        # Precompute fractional diff weights
        self._fd_weights = self._compute_fd_weights()

    def _compute_fd_weights(self) -> list[float]:
        """Compute the fractional differentiation weights up to the threshold cutoff."""
        weights = [1.0]
        k = 1
        while True:
            # w_k = -w_{k-1} * (d - k + 1) / k
            w = -weights[-1] * (self.d_coeff - k + 1) / k
            if abs(w) < self.weight_threshold:
                break
            weights.append(w)
            k += 1
            if k > 5000:  # Safety fallback max lookback
                break
        return weights

    def _get_trade_direction(self, current: MarketQuote, previous: MarketQuote | None) -> int:
        """Determine if a tick was buy-initiated (1) or sell-initiated (-1)."""
        if current.bid is not None and current.ask is not None:
            # Estimate via bid/ask
            mid = (current.bid + current.ask) / 2.0
            if current.price >= current.ask:
                return 1
            elif current.price <= current.bid:
                return -1
            elif current.price > mid:
                return 1
            elif current.price < mid:
                return -1
        
        # Fallback to tick-test
        if previous:
            if current.price > previous.price:
                return 1
            elif current.price < previous.price:
                return -1
        
        return 0

    def process_quote(self, quote: MarketQuote) -> MicrostructureFeatures | None:
        """
        Ingest a live quote, update rolling windows, and evaluate structural rules.
        """
        symbol = quote.instrument.symbol
        history = self._quotes[symbol]
        
        previous_quote = history[-1] if history else None
        
        # Determine tick volume direction
        direction = self._get_trade_direction(quote, previous_quote)
        tick_volume = quote.volume or 1.0  # Default to 1 if missing
        tick_delta = direction * tick_volume
        
        # Update CVD
        self._cvds[symbol] += tick_delta
        
        # Append to rolling history
        history.append(quote)
        
        # Prune history to the delta window + the FD weight lookback (max of both)
        cutoff_time = quote.quoted_at - timedelta(minutes=self.delta_window_minutes)
        # We need at least len(self._fd_weights) items for the frac-diff calculation if we want full precision
        max_lookback_len = len(self._fd_weights)
        
        while len(history) > max_lookback_len and history[0].quoted_at < cutoff_time:
            history.popleft()
            
        # Calculate Rolling Volume Delta (over delta_window_minutes)
        rolling_delta = 0.0
        for i in range(1, len(history)):
            curr = history[i]
            prev = history[i-1]
            if curr.quoted_at >= cutoff_time:
                d = self._get_trade_direction(curr, prev)
                v = curr.volume or 1.0
                rolling_delta += (d * v)
                
        # Calculate Fractional Differentiation
        fd_price = None
        if len(history) >= 2:
            fd_val = 0.0
            idx = len(history) - 1
            w_idx = 0
            while idx >= 0 and w_idx < len(self._fd_weights):
                fd_val += self._fd_weights[w_idx] * history[idx].price
                idx -= 1
                w_idx += 1
            fd_price = fd_val
            
        # Anomaly Detection Flags
        wyckoff_spring = False
        absorption = False
        
        if len(history) >= 10:
            # 1. Wyckoff Spring: Price undercut (lower lows) paired with volume drying/absorption (positive delta burst)
            recent_prices = [q.price for q in list(history)[-10:]]
            if quote.price <= min(recent_prices[:-1]) and tick_delta > 0:
                wyckoff_spring = True
                
            # 2. Institutional Absorption: Heavy negative CVD + stalled downward price progression.
            # E.g., over the rolling window, price hasn't dropped much but delta is heavily negative.
            window_price_change = quote.price - history[0].price
            if rolling_delta < -100 and window_price_change >= 0:
                absorption = True

        return MicrostructureFeatures(
            symbol=symbol,
            timestamp=quote.quoted_at,
            current_price=quote.price,
            rolling_volume_delta=rolling_delta,
            cumulative_volume_delta=self._cvds[symbol],
            fractionally_differentiated_price=fd_price,
            wyckoff_spring_detected=wyckoff_spring,
            institutional_absorption_detected=absorption
        )
