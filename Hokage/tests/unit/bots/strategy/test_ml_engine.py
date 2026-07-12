from __future__ import annotations

import pandas as pd
import numpy as np
from bots.strategy.ml_engine import MLEngine

def test_ml_engine_prepare_data() -> None:
    engine = MLEngine()
    
    # Create mock dataframe with enough rows
    dates = pd.date_range(start="2026-01-01", periods=60, freq="D")
    data = {
        "timestamp": dates,
        "open": np.linspace(100, 160, 60),
        "high": np.linspace(102, 162, 60),
        "low": np.linspace(98, 158, 60),
        "close": np.linspace(101, 161, 60),
        "volume": np.linspace(1000, 2000, 60),
        "log_returns": np.random.normal(0, 0.02, 60),
        "hist_volatility": np.random.uniform(0.01, 0.05, 60),
        "atr": np.random.uniform(1.0, 5.0, 60),
        "bb_width": np.random.uniform(0.02, 0.1, 60)
    }
    df = pd.DataFrame(data)
    
    X, y = engine.prepare_training_data(df, target_horizon=10)
    assert X is not None
    assert y is not None
    assert len(X) == 50 # 60 - 10 shifted rows
    assert X.shape[1] == 4 # 4 features
