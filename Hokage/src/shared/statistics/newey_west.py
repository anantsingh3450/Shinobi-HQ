"""Newey-West HAC-adjusted standard error calculation."""
from __future__ import annotations

import math
from shared.statistics.lag_selection import get_optimal_lag
from shared.statistics.covariance import hac_variance

def newey_west_se(
    x: list[float],
    method: str = "newey_west_1994",
    override_lag: int | None = None,
    adjust: bool = True
) -> float:
    """Compute the Newey-West HAC-adjusted standard error of the sample mean.
    
    Formula:
        SE_HAC = sqrt(sigma^2_HAC_adj / T)
        
    If T <= 1, returns 0.0.
    """
    # Clean input: filter out None and NaN values
    x = [v for v in x if v is not None and not (isinstance(v, float) and math.isnan(v))]
    
    n = len(x)
    if n <= 1:
        return 0.0
        
    # 1. Determine optimal lag truncation limit L
    lag = get_optimal_lag(x, method=method, override_lag=override_lag)
    
    # 2. Compute Bartlett-weighted long-run variance (HAC variance)
    var_hac = hac_variance(x, lag=lag, adjust=adjust)
    
    # 3. Calculate standard error of the mean: SE = sqrt(var_hac / T)
    se = math.sqrt(var_hac / n)
    return se
