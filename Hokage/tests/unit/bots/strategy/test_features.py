from __future__ import annotations

import pandas as pd
import numpy as np
from bots.strategy.features import calculate_features

def test_calculate_features() -> None:
    # Create synthetic OHLCV data
    dates = pd.date_range(start="2026-01-01", periods=30, freq="D")
    data = {
        "timestamp": dates,
        "open": np.linspace(100, 130, 30),
        "high": np.linspace(102, 132, 30),
        "low": np.linspace(98, 128, 30),
        "close": np.linspace(101, 131, 30),
        "volume": np.linspace(1000, 2000, 30)
    }
    df = pd.DataFrame(data)
    
    # Run calculation
    df_feat = calculate_features(df)
    
    # Assert features are created
    assert "log_returns" in df_feat.columns
    assert "hist_volatility" in df_feat.columns
    assert "atr" in df_feat.columns
    assert "bb_width" in df_feat.columns
    
    # Verify no NaN values
    assert not df_feat.isnull().values.any()
