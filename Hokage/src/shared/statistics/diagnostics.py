"""Institutional Statistical Diagnostics for Hokage — Phase 6.6A.

Implements:
1. Ljung-Box Q-Test (Autocorrelation Detection)
2. Jarque-Bera Test (Normality of Returns)
3. Kupiec Proportion of Failures (POF) Test (VaR Calibration Validation)
4. Rolling historical Value-at-Risk (VaR) breach calculator
5. Overall Statistical Health Assessment

All calculations are pure, deterministic, and implemented with zero external statistical library dependencies.
"""
from __future__ import annotations

import math
from typing import Any

from shared.statistics.covariance import mean, autocovariance


def _gammp_series(a: float, x: float) -> float:
    """Evaluate regularized lower incomplete gamma function P(a, x) via series."""
    if x <= 0.0:
        return 0.0
    gln = math.lgamma(a)
    ap = a
    sum_val = 1.0 / a
    delta = sum_val
    # Max 100 iterations
    for _ in range(100):
        ap += 1.0
        delta = delta * x / ap
        sum_val += delta
        if abs(delta) < abs(sum_val) * 1e-15:
            break
    return math.exp(a * math.log(x) - x - gln) * sum_val


def _gammq_cf(a: float, x: float) -> float:
    """Evaluate regularized upper incomplete gamma function Q(a, x) via continued fraction."""
    gln = math.lgamma(a)
    # Lentz's method
    tiny = 1e-30
    b = x + 1.0 - a
    c = 1.0 / tiny
    d = 1.0 / b
    h = d
    for _ in range(1, 100):
        an = -_ * (_ - a)
        b += 2.0
        d = an * d + b
        if abs(d) < tiny:
            d = tiny
        c = b + an / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = c * d
        h *= delta
        if abs(delta - 1.0) < 1e-15:
            break
    return math.exp(a * math.log(x) - x - gln) * h


def regularized_upper_incomplete_gamma(a: float, x: float) -> float:
    """Compute Q(a, x) = Gamma(a, x) / Gamma(a).
    
    This represents the upper tail probability of the gamma distribution,
    which is used to compute Chi-square p-values.
    """
    if x < 0.0 or a <= 0.0:
        return 1.0
    if x == 0.0:
        return 1.0
    if x < a + 1.0:
        # Use series representation for P(a, x) and return 1 - P(a, x)
        return max(0.0, min(1.0, 1.0 - _gammp_series(a, x)))
    else:
        # Use continued fraction for Q(a, x)
        return max(0.0, min(1.0, _gammq_cf(a, x)))


def chi2_p_value(chi2_stat: float, df: int) -> float:
    """Compute the p-value for a Chi-square statistic with df degrees of freedom."""
    if df <= 0:
        return 1.0
    if chi2_stat <= 0.0:
        return 1.0
    return regularized_upper_incomplete_gamma(df / 2.0, chi2_stat / 2.0)


def ljung_box_test(x: list[float], lags: int | None = None) -> dict[str, Any]:
    """Compute the Ljung-Box Q-test for serial correlation of a series.
    
    Null Hypothesis (H0): The data values are independent (white noise).
    Alternative Hypothesis (H1): The data values exhibit serial correlation.
    
    Args:
        x: Time series (e.g. returns or residuals).
        lags: Number of lags to test. If None, defaults to min(10, len(x) // 5) or 1.
    """
    clean_x = [v for v in x if v is not None and not (isinstance(v, float) and math.isnan(v))]
    n = len(clean_x)
    
    if n <= 1:
        return {
            "stat": 0.0,
            "p_value": 1.0,
            "lags": 0,
            "has_autocorrelation": False,
            "message": "Insufficient sample size (n <= 1)"
        }
        
    if lags is None:
        lags = max(1, min(10, n // 5))
    else:
        lags = max(1, min(lags, n - 1))
        
    x_mean = mean(clean_x)
    gamma_0 = autocovariance(clean_x, 0, x_mean)
    
    if gamma_0 <= 1e-15:
        return {
            "stat": 0.0,
            "p_value": 1.0,
            "lags": lags,
            "autocorrelations": [0.0] * lags,
            "has_autocorrelation": False,
            "message": "Zero variance in sample"
        }
        
    q_stat = 0.0
    autocorrelations = []
    for k in range(1, lags + 1):
        gamma_k = autocovariance(clean_x, k, x_mean)
        rho_k = gamma_k / gamma_0
        autocorrelations.append(rho_k)
        q_stat += (rho_k ** 2) / (n - k)
        
    q_stat *= n * (n + 2)
    p_val = chi2_p_value(q_stat, lags)
    
    return {
        "stat": round(q_stat, 4),
        "p_value": round(p_val, 6),
        "lags": lags,
        "autocorrelations": [round(val, 4) for val in autocorrelations],
        "has_autocorrelation": bool(p_val < 0.05),
        "message": "Independent (White Noise)" if p_val >= 0.05 else "Serially Correlated"
    }


def jarque_bera_test(x: list[float]) -> dict[str, Any]:
    """Compute the Jarque-Bera normality test for a series.
    
    Null Hypothesis (H0): The data is normally distributed.
    Alternative Hypothesis (H1): The data is not normally distributed (skewed/fat-tailed).
    """
    clean_x = [v for v in x if v is not None and not (isinstance(v, float) and math.isnan(v))]
    n = len(clean_x)
    
    if n < 3:
        return {
            "stat": 0.0,
            "p_value": 1.0,
            "skewness": 0.0,
            "kurtosis": 3.0,
            "excess_kurtosis": 0.0,
            "is_normal": True,
            "message": "Insufficient sample size (n < 3)"
        }
        
    x_mean = mean(clean_x)
    
    m2 = sum((val - x_mean) ** 2 for val in clean_x) / n
    m3 = sum((val - x_mean) ** 3 for val in clean_x) / n
    m4 = sum((val - x_mean) ** 4 for val in clean_x) / n
    
    if m2 <= 1e-15:
        return {
            "stat": 0.0,
            "p_value": 1.0,
            "skewness": 0.0,
            "kurtosis": 3.0,
            "excess_kurtosis": 0.0,
            "is_normal": True,
            "message": "Zero variance in sample"
        }
        
    skewness = m3 / (m2 ** 1.5)
    kurtosis = m4 / (m2 ** 2.0)
    excess_kurtosis = kurtosis - 3.0
    
    stat = (n / 6.0) * (skewness ** 2 + (excess_kurtosis ** 2) / 4.0)
    p_val = chi2_p_value(stat, 2)
    
    return {
        "stat": round(stat, 4),
        "p_value": round(p_val, 6),
        "skewness": round(skewness, 4),
        "kurtosis": round(kurtosis, 4),
        "excess_kurtosis": round(excess_kurtosis, 4),
        "is_normal": bool(p_val >= 0.05),
        "message": "Normal" if p_val >= 0.05 else "Non-Normal (Fat-tailed / Skewed)"
    }


def kupiec_pof_test(
    failures: int,
    total_observations: int,
    var_confidence: float = 0.95
) -> dict[str, Any]:
    """Compute the Kupiec Proportion of Failures (POF) test for VaR calibration.
    
    Null Hypothesis (H0): The VaR model is correctly calibrated.
    Alternative Hypothesis (H1): The VaR model is incorrectly calibrated (fails too often or too rarely).
    """
    p = 1.0 - var_confidence
    n = total_observations
    x = failures
    
    if n <= 0:
        return {
            "stat": 0.0,
            "p_value": 1.0,
            "failures": 0,
            "total_observations": 0,
            "failure_rate": 0.0,
            "expected_failure_rate": p,
            "is_valid": True,
            "message": "No observations to validate"
        }
        
    if x < 0 or x > n:
        raise ValueError("Failures must be between 0 and total_observations inclusive")
        
    p_hat = x / n
    
    # Log-likelihood under null H0
    log_l_null = (n - x) * math.log(1.0 - p) + x * math.log(p)
    
    # Log-likelihood under alternative H1 (handling boundary cases)
    if x == 0:
        log_l_alt = 0.0
    elif x == n:
        log_l_alt = 0.0
    else:
        log_l_alt = (n - x) * math.log(1.0 - p_hat) + x * math.log(p_hat)
        
    lr = -2.0 * (log_l_null - log_l_alt)
    lr = max(0.0, lr)  # Clamp numerical floating point inaccuracies
    
    p_val = chi2_p_value(lr, 1)
    is_valid = bool(p_val >= 0.05)
    
    return {
        "stat": round(lr, 4),
        "p_value": round(p_val, 6),
        "failures": x,
        "total_observations": n,
        "failure_rate": round(p_hat, 4),
        "expected_failure_rate": round(p, 4),
        "is_valid": is_valid,
        "message": "Valid Calibration" if is_valid else "Invalid Calibration (Model Failure)"
    }


def calculate_var_breaches(
    returns: list[float],
    var_confidence: float = 0.95,
    window: int = 20
) -> tuple[int, int]:
    """Calculate the number of VaR breaches and total observations using a rolling historical VaR.
    
    For each day t (starting from window), the ex-ante VaR is the (1 - var_confidence) percentile
    of the returns in the previous 'window' days. A breach occurs if returns[t] < -VaR.
    
    Returns:
        failures: Number of breaches.
        total_observations: Number of days evaluated (len(returns) - window).
    """
    n = len(returns)
    if n <= window:
        # Fallback: if the series is too short for rolling VaR, use a constant VaR of 2%
        failures = sum(1 for r in returns if r < -0.02)
        return failures, n
        
    failures = 0
    total_obs = n - window
    
    alpha = 1.0 - var_confidence
    for t in range(window, n):
        window_returns = returns[t - window : t]
        sorted_window = sorted(window_returns)
        idx = max(0, min(window - 1, int(alpha * window)))
        var_t = -sorted_window[idx]
        if returns[t] < -var_t:
            failures += 1
            
    return failures, total_obs


def evaluate_statistical_health(
    returns: list[float],
    failures: int | None = None,
    total_observations: int | None = None,
    var_confidence: float = 0.95
) -> dict[str, Any]:
    """Perform a comprehensive statistical diagnostics check on returns.
    
    Aggregates Ljung-Box, Jarque-Bera, and optionally Kupiec POF tests to assess
    overall statistical health.
    """
    clean_returns = [v for v in returns if v is not None and not (isinstance(v, float) and math.isnan(v))]
    
    lb_result = ljung_box_test(clean_returns)
    jb_result = jarque_bera_test(clean_returns)
    
    if failures is None or total_observations is None:
        if len(clean_returns) >= 5:
            failures, total_observations = calculate_var_breaches(clean_returns, var_confidence)
        else:
            failures, total_observations = 0, len(clean_returns)
            
    kp_result = kupiec_pof_test(failures, total_observations, var_confidence)
    
    passed_lb = not lb_result.get("has_autocorrelation", False)
    passed_kp = kp_result.get("is_valid", True)
    passed_jb = jb_result.get("is_normal", True)
    
    if len(clean_returns) < 5:
        status = "INSUFFICIENT_DATA"
        explanation = "Insufficient returns observations to perform robust diagnostics (n < 5)."
    elif not passed_lb and not passed_kp:
        status = "CRITICAL"
        explanation = "Critical failure: Return series exhibits significant autocorrelation (Ljung-Box) and VaR calibration is statistically invalid (Kupiec)."
    elif not passed_lb:
        status = "CRITICAL"
        explanation = "Critical warning: Return series exhibits significant autocorrelation (Ljung-Box), indicating residual predictability or model misspecification."
    elif not passed_kp:
        status = "CRITICAL"
        explanation = "Critical failure: Value-at-Risk calibration is statistically invalid (Kupiec POF), indicating severe under- or over-estimation of risk."
    elif not passed_jb:
        status = "GOOD"
        explanation = "Good: No return autocorrelation, and VaR calibration is valid. Normal distribution is rejected (Jarque-Bera) due to fat tails/skewness, which is standard for financial returns."
    else:
        status = "EXCELLENT"
        explanation = "Excellent: Return series exhibits no autocorrelation, normal return distribution, and valid VaR calibration."
        
    return {
        "status": status,
        "explanation": explanation,
        "ljung_box": lb_result,
        "jarque_bera": jb_result,
        "kupiec": kp_result,
        "sample_size": len(clean_returns),
        "passed_autocorrelation": passed_lb,
        "passed_normality": passed_jb,
        "passed_var_calibration": passed_kp
    }
