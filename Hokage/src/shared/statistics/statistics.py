"""Dual hypothesis testing engine for strategy promotion evaluations."""
from __future__ import annotations

import math
from shared.statistics.covariance import mean
from shared.statistics.lag_selection import get_optimal_lag
from shared.statistics.newey_west import newey_west_se

def sample_std(x: list[float], x_mean: float | None = None) -> float:
    """Calculate the sample standard error (standard deviation) of a list of floats."""
    n = len(x)
    if n <= 1:
        return 0.0
    if x_mean is None:
        x_mean = mean(x)
    var = sum((val - x_mean) ** 2 for val in x) / (n - 1)
    return math.sqrt(max(0.0, var))

def hac_t_test(
    x: list[float],
    y: list[float],
    fallback_mean_x: float = 0.0,
    fallback_mean_y: float = 0.0,
    fallback_std_x: float = 1.0,
    fallback_std_y: float = 1.0,
    fallback_n_x: int | None = None,
    fallback_n_y: int | None = None,
    method: str = "newey_west_1994",
    override_lag: int | None = None
) -> dict[str, any]:
    """Compute both classical and HAC-adjusted t-statistics and confidence intervals.
    
    Compares the returns of a probation strategy (x) against a production strategy (y).
    
    If histories are empty or contain only 1 element, falls back cleanly to classical
    standard errors using the provided fallback standard deviations and effective counts.
    """
    # Clean inputs: filter out None and NaN values
    x = [v for v in x if v is not None and not (isinstance(v, float) and math.isnan(v))]
    y = [v for v in y if v is not None and not (isinstance(v, float) and math.isnan(v))]
    
    nx = len(x)
    ny = len(y)
    
    # 1. Resolve Means, Standard Deviations, and Effective Counts (with fallback if sample size <= 1)
    if nx > 1:
        mean_x = mean(x)
        std_x = sample_std(x, mean_x)
        effective_n_x = nx
    elif nx == 1:
        mean_x = x[0]
        std_x = fallback_std_x
        effective_n_x = fallback_n_x if fallback_n_x is not None else 1
    else:
        mean_x = fallback_mean_x
        std_x = fallback_std_x
        effective_n_x = fallback_n_x if fallback_n_x is not None else 1
        
    if ny > 1:
        mean_y = mean(y)
        std_y = sample_std(y, mean_y)
        effective_n_y = ny
    elif ny == 1:
        mean_y = y[0]
        std_y = fallback_std_y
        effective_n_y = fallback_n_y if fallback_n_y is not None else 1
    else:
        mean_y = fallback_mean_y
        std_y = fallback_std_y
        effective_n_y = fallback_n_y if fallback_n_y is not None else 1
        
    # 2. Calculate Classical Welch Standard Errors and t-statistic
    classical_var_mean_x = (std_x ** 2) / max(1, effective_n_x)
    classical_var_mean_y = (std_y ** 2) / max(1, effective_n_y)
    classical_se_diff = math.sqrt(classical_var_mean_x + classical_var_mean_y)
    
    diff_mean = mean_x - mean_y
    classical_t_stat = diff_mean / classical_se_diff if classical_se_diff > 0.0 else 0.0
    classical_ci_lower = diff_mean - 1.645 * classical_se_diff
    
    # 3. Calculate HAC-adjusted Standard Errors and t-statistic
    # Obtain selected lags for each series
    lag_x = get_optimal_lag(x, method=method, override_lag=override_lag) if nx > 1 else 0
    lag_y = get_optimal_lag(y, method=method, override_lag=override_lag) if ny > 1 else 0
    
    if nx > 1:
        hac_se_x = newey_west_se(x, method=method, override_lag=override_lag, adjust=True)
    else:
        hac_se_x = math.sqrt(classical_var_mean_x)
        
    if ny > 1:
        hac_se_y = newey_west_se(y, method=method, override_lag=override_lag, adjust=True)
    else:
        hac_se_y = math.sqrt(classical_var_mean_y)
        
    hac_se_diff = math.sqrt(hac_se_x ** 2 + hac_se_y ** 2)
    hac_t_stat = diff_mean / hac_se_diff if hac_se_diff > 0.0 else 0.0
    hac_ci_lower = diff_mean - 1.645 * hac_se_diff
    
    # 4. Compile and Return Results
    return {
        "mean_x": mean_x,
        "mean_y": mean_y,
        "count_x": nx,
        "count_y": ny,
        "std_x": std_x,
        "std_y": std_y,
        "classical_se_x": math.sqrt(classical_var_mean_x),
        "classical_se_y": math.sqrt(classical_var_mean_y),
        "classical_se_diff": classical_se_diff,
        "classical_t_stat": classical_t_stat,
        "classical_ci_lower": classical_ci_lower,
        "hac_se_x": hac_se_x,
        "hac_se_y": hac_se_y,
        "hac_se_diff": hac_se_diff,
        "hac_t_stat": hac_t_stat,
        "hac_ci_lower": hac_ci_lower,
        "lag_x": lag_x,
        "lag_y": lag_y,
        "bandwidth_method": method if (nx > 1 or ny > 1) else "NONE_FALLBACK"
    }
