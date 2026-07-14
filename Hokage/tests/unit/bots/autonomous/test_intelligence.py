from bots.autonomous.intelligence import (
    AdvancedMarketRegimeEngine,
    SessionBehaviorEngine,
    LiquidityEngine,
    VolumeEngine,
    PositionManagementEngine,
    AdaptiveSizingEngine,
    TradeQualityEngine,
)

def test_market_regime_classification():
    engine = AdvancedMarketRegimeEngine()
    assert engine.classify_regime(0.0, 4.0) == "PANIC_BEAR"
    assert engine.classify_regime(0.0, 2.0) == "VOLATILE_MIXED"
    assert engine.classify_regime(0.8, 0.0) == "STRONG_BULL"
    assert engine.classify_regime(-0.8, 0.0) == "STRONG_BEAR"
    assert engine.classify_regime(0.0, 0.0) == "SIDEWAYS"

def test_session_behavior_filter():
    engine = SessionBehaviorEngine()
    assert engine.get_current_session() in ("OPEN_SESSION", "MID_SESSION", "CLOSE_SESSION", "OFF_MARKET")
    
    # Test morning breakouts permitted
    allowed, msg = engine.filter_opportunity("OPEN_SESSION", "long breakout")
    assert allowed
    
    # Test mid-session mean reversion permitted, breakout suspended
    allowed, msg = engine.filter_opportunity("MID_SESSION", "long mean-reversion")
    assert allowed
    allowed, msg = engine.filter_opportunity("MID_SESSION", "long breakout momentum")
    assert not allowed
    
    # Test close session breakout suspended
    allowed, msg = engine.filter_opportunity("CLOSE_SESSION", "breakout")
    assert not allowed

def test_liquidity_engine():
    engine = LiquidityEngine()
    
    # Normal profile
    allowed, msg = engine.check_liquidity(0.05, 1.0)
    assert allowed
    
    # Wide spread trap
    allowed, msg = engine.check_liquidity(0.25, 1.0)
    assert not allowed
    assert "spread" in msg.lower()
    
    # Imbalance depth trap
    allowed, msg = engine.check_liquidity(0.05, 6.0)
    assert not allowed
    assert "imbalance" in msg.lower()

    # Thin bid-side book (ratio below 0.2x) is equally a trap
    allowed, msg = engine.check_liquidity(0.05, 0.1)
    assert not allowed
    assert "imbalance" in msg.lower()

    # Depth data unavailable (None): imbalance check skipped, spread still enforced
    allowed, msg = engine.check_liquidity(0.05, None)
    assert allowed
    allowed, msg = engine.check_liquidity(0.25, None)
    assert not allowed
    assert "spread" in msg.lower()

def test_volume_engine():
    engine = VolumeEngine()

    # Normal volume fails the default breakout family (1.0x < 1.2x)
    allowed, msg = engine.validate_breakout(100.0, 100.0)
    assert not allowed
    assert "FAKE_BREAKOUT" in msg

    # Breakout volume
    allowed, msg = engine.validate_breakout(200.0, 100.0)
    assert allowed

    # Abnormal volume
    allowed, msg = engine.validate_breakout(300.0, 100.0)
    assert allowed
    assert "ABNORMAL_VOLUME" in msg


def test_volume_engine_entry_families():
    """Commander-approved: breakout entries keep the 1.2x surge bar; trend/
    pullback entries only reject a dead tape (< 0.8x average)."""
    engine = VolumeEngine()

    # 0.84x: rejected for breakout, accepted for trend (the exact ratio that
    # starved the flagship on 2026-07-14).
    allowed, msg = engine.validate_breakout(84.0, 100.0, entry_family="breakout")
    assert not allowed and "FAKE_BREAKOUT" in msg
    allowed, msg = engine.validate_breakout(84.0, 100.0, entry_family="trend")
    assert allowed

    # 0.5x: dead tape rejected for every family
    allowed, msg = engine.validate_breakout(50.0, 100.0, entry_family="trend")
    assert not allowed and "THIN_TAPE" in msg

def test_position_management_engine():
    engine = PositionManagementEngine()
    
    # Standard stops
    tsl, tp = engine.get_adapted_exit_percentages(0.05, 0.10, 0.0)
    assert tsl == 0.05
    assert tp == 0.10
    
    # High volatility (widen stops)
    tsl, tp = engine.get_adapted_exit_percentages(0.05, 0.10, 2.5)
    assert tsl == 0.075
    assert tp == 0.13
    
    # Low volatility (tighten stops)
    tsl, tp = engine.get_adapted_exit_percentages(0.05, 0.10, -1.5)
    assert tsl == 0.04
    assert tp == 0.09

def test_adaptive_sizing_engine():
    engine = AdaptiveSizingEngine()
    
    # Bull market sizing
    size = engine.get_adapted_allocation(2.0, "STRONG_BULL", 0.0, 0.0)
    assert size == 2.4  # scaled up
    
    # Panic market drawdown sizing
    size = engine.get_adapted_allocation(2.0, "PANIC_BEAR", 6.0, 2.0)
    # Scaled down by panic (0.5), drawdown (0.5), and VIX (0.7) -> 2.0 * 0.5 * 0.5 * 0.7 = 0.35
    assert size == 0.35

def test_trade_quality_engine():
    engine = TradeQualityEngine()
    
    # Stable position
    exit_needed, msg = engine.evaluate_open_position("TCS", 100.0, 100.0, 0.0, "SIDEWAYS")
    assert not exit_needed
    
    # Panic Bear regime switch exit
    exit_needed, msg = engine.evaluate_open_position("TCS", 100.0, 100.0, 0.0, "PANIC_BEAR")
    assert exit_needed
    assert "PANIC_BEAR" in msg
    
    # Volatility VIX shock spike exit
    exit_needed, msg = engine.evaluate_open_position("TCS", 100.0, 100.0, 4.5, "SIDEWAYS")
    assert exit_needed
    assert "VIX" in msg
    
    # Sharp selling volume reversal exit
    exit_needed, msg = engine.evaluate_open_position("TCS", 90.0, 100.0, 0.0, "SIDEWAYS", volume_ratio=3.5)
    assert exit_needed
    assert "selling volume" in msg.lower()
