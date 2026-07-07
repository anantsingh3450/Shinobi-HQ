from __future__ import annotations

from bots.backtest.engine.historical_backtest_engine import HistoricalBacktestEngine
from bots.strategy.models import StrategyProposal
from integrations.data.mock_provider import MockMarketDataProvider


def test_historical_backtest_engine_uses_provider_candles() -> None:
    provider = MockMarketDataProvider()
    engine = HistoricalBacktestEngine(provider, lookback_days=10)
    proposal = StrategyProposal(
        name="Mock EUR Strategy",
        description="Directional strategy",
        market="EUR/USD",
        entry_rule="Enter long on confirmed momentum.",
        exit_rule="Exit on reversal.",
        stop_loss_rule="2% stop",
        take_profit_rule="3:1 target",
        timeframe="1D",
        confidence_score=0.8,
        sources_cited=("test",),
    )

    result = engine.run_backtest(proposal)

    assert result.provider == provider.provider_name
    assert result.market == "EUR/USD"
    assert result.total_trades == 9
    assert len(result.equity_curve) == 10
    assert result.gross_profit >= 0
    assert result.gross_loss >= 0
    assert result.after_tax_net_profit == result.net_profit


def test_historical_backtest_engine_applies_tax_rate_to_positive_profit() -> None:
    provider = MockMarketDataProvider()
    engine = HistoricalBacktestEngine(provider, lookback_days=10, tax_rate=0.2)
    proposal = StrategyProposal(
        name="Mock Short Strategy",
        description="Directional strategy",
        market="EUR/USD",
        entry_rule="Enter short on breakdown.",
        exit_rule="Exit on reversal.",
        stop_loss_rule="2% stop",
        take_profit_rule="3:1 target",
        timeframe="1D",
        confidence_score=0.8,
        sources_cited=("test",),
    )

    result = engine.run_backtest(proposal)

    assert result.tax_estimate is not None
    assert result.after_tax_net_profit is not None
    if result.net_profit > 0:
        assert result.after_tax_net_profit < result.net_profit
    else:
        assert result.after_tax_net_profit == result.net_profit
