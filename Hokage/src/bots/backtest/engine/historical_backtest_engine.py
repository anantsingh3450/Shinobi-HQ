"""Provider-backed historical backtest engine.

This engine consumes normalized candles from MarketDataProvider. It remains
deterministic in mock mode and intentionally avoids broker/live execution.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from bots.backtest.interfaces import BacktestEngine
from bots.backtest.models import BacktestResult
from bots.strategy.models import StrategyProposal
from integrations.data.interfaces import MarketDataProvider
from integrations.data.models import CandleInterval, HistoricalDataRequest


class HistoricalBacktestEngine(BacktestEngine):
    """Backtest a StrategyProposal against provider-supplied candles."""

    def __init__(
        self,
        market_data_provider: MarketDataProvider,
        *,
        lookback_days: int = 30,
        initial_equity: float = 10_000.0,
        risk_per_trade: float = 100.0,
        tax_rate: float = 0.0,
    ) -> None:
        if lookback_days < 2:
            raise ValueError("lookback_days must be at least 2.")
        if initial_equity <= 0:
            raise ValueError("initial_equity must be positive.")
        if risk_per_trade <= 0:
            raise ValueError("risk_per_trade must be positive.")
        if not 0.0 <= tax_rate <= 1.0:
            raise ValueError("tax_rate must be between 0.0 and 1.0.")
        self._provider = market_data_provider
        self._lookback_days = lookback_days
        self._initial_equity = initial_equity
        self._risk_per_trade = risk_per_trade
        self._tax_rate = tax_rate

    def run_backtest(self, proposal: StrategyProposal) -> BacktestResult:
        """Run a simple directional candle backtest."""
        instrument = self._provider.resolve_instrument(proposal.market)
        end = datetime(2026, 1, 1, tzinfo=UTC)
        start = end - timedelta(days=self._lookback_days)
        request = HistoricalDataRequest(
            instrument=instrument,
            start=start,
            end=end,
            interval=self._interval_from_timeframe(proposal.timeframe),
        )
        result = self._provider.get_historical_candles(request)
        candles = result.candles

        if len(candles) < 2:
            return BacktestResult(
                proposal_id=proposal.proposal_id,
                total_trades=0,
                win_rate=0.0,
                net_profit=0.0,
                max_drawdown=0.0,
                profit_factor=0.0,
                passed=False,
                summary=f"Insufficient historical candles for {proposal.name}.",
                market=proposal.market,
                timeframe=proposal.timeframe,
                start=start,
                end=end,
                provider=result.provider,
            )

        direction_factor = -1.0 if "short" in proposal.entry_rule.lower() else 1.0
        trade_pnls: list[float] = []
        equity_curve: list[float] = [self._initial_equity]
        equity = self._initial_equity

        for previous, current in zip(candles, candles[1:]):
            move_pct = (current.close - previous.close) / previous.close
            pnl = round(direction_factor * move_pct * self._risk_per_trade, 6)
            trade_pnls.append(pnl)
            equity = round(equity + pnl, 6)
            equity_curve.append(equity)

        wins = [pnl for pnl in trade_pnls if pnl > 0]
        losses = [pnl for pnl in trade_pnls if pnl < 0]
        gross_profit = round(sum(wins), 6)
        gross_loss = round(abs(sum(losses)), 6)
        net_profit = round(sum(trade_pnls), 6)
        tax_estimate = round(max(net_profit, 0.0) * self._tax_rate, 6)
        after_tax_net_profit = round(net_profit - tax_estimate, 6)
        total_trades = len(trade_pnls)
        win_rate = round((len(wins) / total_trades) * 100, 2) if total_trades else 0.0
        profit_factor = round(gross_profit / gross_loss, 6) if gross_loss else float("inf")
        max_drawdown = self._max_drawdown_pct(equity_curve)
        average_win = round(gross_profit / len(wins), 6) if wins else 0.0
        average_loss = round(gross_loss / len(losses), 6) if losses else 0.0
        passed = win_rate >= 50 and after_tax_net_profit > 0 and max_drawdown < 20
        summary = (
            f"Historical backtest completed for {proposal.name} using "
            f"{result.provider}. Win Rate={win_rate}%, "
            f"After-tax Net Profit={after_tax_net_profit}, "
            f"Drawdown={max_drawdown}%."
        )

        return BacktestResult(
            proposal_id=proposal.proposal_id,
            total_trades=total_trades,
            win_rate=win_rate,
            net_profit=net_profit,
            max_drawdown=max_drawdown,
            profit_factor=profit_factor,
            passed=passed,
            summary=summary,
            market=proposal.market,
            timeframe=proposal.timeframe,
            start=start,
            end=end,
            gross_profit=gross_profit,
            gross_loss=gross_loss,
            average_win=average_win,
            average_loss=average_loss,
            after_tax_net_profit=after_tax_net_profit,
            tax_estimate=tax_estimate,
            equity_curve=tuple(equity_curve),
            provider=result.provider,
        )

    @staticmethod
    def _interval_from_timeframe(timeframe: str) -> CandleInterval:
        normalized = timeframe.strip().lower()
        if normalized in {"1h", "60m"}:
            return CandleInterval.ONE_HOUR
        if normalized in {"15m", "15min"}:
            return CandleInterval.FIFTEEN_MINUTES
        if normalized in {"5m", "5min"}:
            return CandleInterval.FIVE_MINUTES
        if normalized in {"1m", "1min"}:
            return CandleInterval.ONE_MINUTE
        return CandleInterval.ONE_DAY

    @staticmethod
    def _max_drawdown_pct(equity_curve: list[float]) -> float:
        peak = equity_curve[0]
        max_drawdown = 0.0
        for equity in equity_curve:
            peak = max(peak, equity)
            if peak > 0:
                drawdown = (peak - equity) / peak * 100
                max_drawdown = max(max_drawdown, drawdown)
        return round(max_drawdown, 6)
