"""Covariance calculations for the Newey-West HAC statistical engine."""
from __future__ import annotations

import math

def mean(x: list[float]) -> float:
    """Calculate the arithmetic mean of a list of floats."""
    if not x:
        return 0.0
    return sum(x) / len(x)

def autocovariance(x: list[float], lag: int, x_mean: float | None = None) -> float:
    """Calculate the sample autocovariance at a given lag.
    
    Formula:
        gamma_j = (1 / T) * sum_{t=j+1}^T (x_t - mean) * (x_{t-j} - mean)
    """
    n = len(x)
    if n == 0 or lag >= n or lag < 0:
        return 0.0
        
    if x_mean is None:
        x_mean = mean(x)
        
    sum_cov = 0.0
    for t in range(lag, n):
        sum_cov += (x[t] - x_mean) * (x[t - lag] - x_mean)
        
    return sum_cov / n

def hac_variance(x: list[float], lag: int, adjust: bool = True) -> float:
    """Calculate the Newey-West HAC long-run variance using the Bartlett kernel.
    
    Formula:
        sigma^2_HAC = gamma_0 + 2 * sum_{j=1}^L (1 - j / (L + 1)) * gamma_j
        
    If adjust is True, applies the finite-sample adjustment:
        sigma^2_HAC_adj = sigma^2_HAC * (T / (T - 1))
    """
    n = len(x)
    if n == 0:
        return 0.0
    if n == 1:
        return 0.0
        
    x_mean = mean(x)
    
    # Lag 0 autocovariance (standard sample variance with T in the denominator)
    gamma_0 = autocovariance(x, 0, x_mean)
    
    # Bartlett kernel weighted sum of lag autocovariances
    sum_lags = 0.0
    for j in range(1, lag + 1):
        if j < n:
            gamma_j = autocovariance(x, j, x_mean)
            weight = 1.0 - (float(j) / (lag + 1))
            sum_lags += weight * gamma_j
            
    var_hac = gamma_0 + 2.0 * sum_lags
    
    # Finite-sample adjustment (T / (T - 1))
    if adjust and n > 1:
        var_hac *= (float(n) / (n - 1))
        
    # Clip to 0.0 to guarantee positive semi-definiteness under float rounding
    return max(0.0, var_hac)
