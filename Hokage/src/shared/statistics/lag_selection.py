"""Lag and bandwidth selection algorithms for the Newey-West HAC statistical engine."""
from __future__ import annotations

import math
from shared.statistics.covariance import mean, autocovariance

def newey_west_1994_bandwidth(x: list[float]) -> float:
    """Implement the Newey-West (1994) non-parametric plug-in bandwidth selection.
    
    Formula:
        M = 1.1447 * (alpha(1) * T)^(1/3)
        where alpha(1) = (f^(1) / f^(0))^2
        and f^(0) = gamma_0 + 2 * sum_{j=1}^n gamma_j
        and f^(1) = 2 * sum_{j=1}^n j * gamma_j
        using pilot lag n = floor(4 * (T / 100)^(2/9))
    """
    t = len(x)
    if t <= 2:
        return 0.0
        
    x_mean = mean(x)
    
    # 1. Determine pilot lag length n
    n = max(1, int(4.0 * (float(t) / 100.0) ** (2.0 / 9.0)))
    if n >= t:
        n = t - 1
        
    # 2. Compute sample autocovariances up to pilot lag n
    gamma = [autocovariance(x, j, x_mean) for j in range(n + 1)]
    
    # 3. Compute spectral density estimators at frequency zero
    f_0 = abs(gamma[0] + 2.0 * sum(gamma[j] for j in range(1, n + 1)))
    f_1 = abs(2.0 * sum(float(j) * gamma[j] for j in range(1, n + 1)))
    
    # 4. Handle division by zero or negative values (spectral density must be positive)
    if f_0 <= 1e-15:
        return 0.0
        
    alpha = (f_1 / f_0) ** 2
    
    # 5. Calculate optimal bandwidth
    bandwidth = 1.1447 * (alpha * float(t)) ** (1.0 / 3.0)
    return bandwidth

def ar1_bandwidth(x: list[float]) -> float:
    """Implement the Andrews (1991) parametric AR(1) plug-in bandwidth selection.
    
    Formula:
        M = 1.1447 * (alpha(1) * T)^(1/3)
        where alpha(1) = (4 * rho^2) / ((1 - rho)^2 * (1 + rho)^2)
        and rho is the AR(1) coefficient estimated from OLS.
    """
    t = len(x)
    if t <= 2:
        return 0.0
        
    x_mean = mean(x)
    u = [val - x_mean for val in x]
    
    # Estimate AR(1) coefficient rho via OLS (no intercept)
    num = sum(u[i] * u[i-1] for i in range(1, t))
    den = sum(u[i] ** 2 for i in range(t - 1))
    
    if den == 0.0:
        return 0.0
        
    rho = num / den
    
    # Bound rho to avoid division by zero or extreme instability near unit roots
    if rho >= 0.999:
        rho = 0.999
    elif rho <= -0.999:
        rho = -0.999
        
    alpha = (4.0 * (rho ** 2)) / (((1.0 - rho) ** 2) * ((1.0 + rho) ** 2))
    
    bandwidth = 1.1447 * (alpha * float(t)) ** (1.0 / 3.0)
    return bandwidth

def rule_of_thumb_bandwidth(x: list[float]) -> float:
    """Stock-Watson / Newey-West rule of thumb bandwidth selection:
    
    Formula:
        M = 0.75 * T^(1/3)
    """
    t = len(x)
    if t <= 0:
        return 0.0
    return 0.75 * (float(t) ** (1.0 / 3.0))

def get_optimal_lag(x: list[float], method: str = "newey_west_1994", override_lag: int | None = None) -> int:
    """Determine the optimal integer lag limit L for covariance estimation.
    
    L is derived from bandwidth M as:
        L = floor(M)
    Bound by 0 and T-1.
    """
    if override_lag is not None:
        return max(0, min(len(x) - 1, override_lag))
        
    t = len(x)
    if t <= 2:
        return 0
        
    if method == "newey_west_1994":
        bw = newey_west_1994_bandwidth(x)
    elif method == "ar1":
        bw = ar1_bandwidth(x)
    elif method == "rule_of_thumb":
        bw = rule_of_thumb_bandwidth(x)
    else:
        raise ValueError(f"Unknown lag selection method: {method}")
        
    lag = int(math.floor(bw))
    
    # Bound the lag to [0, T - 1]
    return max(0, min(t - 1, lag))
