"""Unit tests for the Institutional Statistical Diagnostics engine."""
from __future__ import annotations

import math
import pytest

from shared.statistics.diagnostics import (
    chi2_p_value,
    ljung_box_test,
    jarque_bera_test,
    kupiec_pof_test,
    evaluate_statistical_health,
)


def test_chi2_p_value():
    """Test the Chi-square p-value calculator against known critical values."""
    # df = 1, stat = 3.841 (approximately 95% critical value, so p-value ~ 0.05)
    p_val_1 = chi2_p_value(3.841, 1)
    assert math.isclose(p_val_1, 0.05, abs_tol=0.01)

    # df = 2, stat = 5.991 (approximately 95% critical value, so p-value ~ 0.05)
    p_val_2 = chi2_p_value(5.991, 2)
    assert math.isclose(p_val_2, 0.05, abs_tol=0.01)

    # df = 10, stat = 18.307 (approximately 95% critical value, so p-value ~ 0.05)
    p_val_10 = chi2_p_value(18.307, 10)
    assert math.isclose(p_val_10, 0.05, abs_tol=0.01)

    # Edge cases
    assert chi2_p_value(0.0, 1) == 1.0
    assert chi2_p_value(-1.0, 5) == 1.0
    assert chi2_p_value(5.0, 0) == 1.0
    assert chi2_p_value(5.0, -2) == 1.0


def test_ljung_box_white_noise():
    """Test Ljung-Box test on independent data (should pass)."""
    # A sequence with extremely low autocorrelation (deterministic white noise)
    white_noise = [
        -0.535, 0.143, 1.42, -0.221, -1.797, 0.867, -1.211, 0.673, -1.114, -1.179,
        -1.719, 0.875, 0.001, -0.958, 0.221, 0.978, 1.018, -0.351, -1.383, 0.523,
        -0.094, -0.167, 0.25, -0.745, -0.22, -0.839, -0.675, -0.594, -1.995, -1.358
    ]
    result = ljung_box_test(white_noise, lags=3)
    
    assert result["lags"] == 3
    assert result["has_autocorrelation"] is False
    assert result["p_value"] >= 0.05
    assert result["message"] == "Independent (White Noise)"


def test_ljung_box_autocorrelation():
    """Test Ljung-Box test on highly autocorrelated data (should fail)."""
    # A strongly trending series (perfectly autocorrelated)
    correlated_series = [float(i) for i in range(20)]
    result = ljung_box_test(correlated_series, lags=3)
    
    assert result["lags"] == 3
    assert result["has_autocorrelation"] is True
    assert result["p_value"] < 0.05
    assert result["message"] == "Serially Correlated"


def test_ljung_box_edge_cases():
    """Test Ljung-Box test edge cases (small samples, zero variance)."""
    # Empty series
    assert ljung_box_test([])["stat"] == 0.0
    assert ljung_box_test([])["p_value"] == 1.0
    assert ljung_box_test([])["has_autocorrelation"] is False

    # n = 1
    assert ljung_box_test([1.0])["p_value"] == 1.0
    assert ljung_box_test([1.0])["has_autocorrelation"] is False

    # Zero variance (flat line)
    flat_series = [1.0, 1.0, 1.0, 1.0, 1.0, 1.0]
    result = ljung_box_test(flat_series)
    assert result["stat"] == 0.0
    assert result["p_value"] == 1.0
    assert result["has_autocorrelation"] is False


def test_jarque_bera_normal():
    """Test Jarque-Bera test on a symmetric, near-normal series (should pass)."""
    # A symmetric series with low skewness and near-3 kurtosis
    near_normal = [-2.0, -1.0, -1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 2.0]
    result = jarque_bera_test(near_normal)
    
    assert result["is_normal"] is True
    assert result["p_value"] >= 0.05
    assert abs(result["skewness"]) < 0.1
    assert result["message"] == "Normal"


def test_jarque_bera_non_normal():
    """Test Jarque-Bera test on highly skewed/fat-tailed data (should fail)."""
    # Add a massive outlier to create a highly skewed and leptokurtic distribution
    non_normal = [0.1, -0.1, 0.05, -0.08, 0.12, -0.05, 0.02, -0.03, 10.0, -0.15]
    result = jarque_bera_test(non_normal)
    
    assert result["is_normal"] is False
    assert result["p_value"] < 0.05
    assert result["stat"] > 5.991
    assert result["message"] == "Non-Normal (Fat-tailed / Skewed)"


def test_jarque_bera_edge_cases():
    """Test Jarque-Bera test edge cases (small samples, zero variance)."""
    # n = 2
    result_small = jarque_bera_test([1.0, 2.0])
    assert result_small["stat"] == 0.0
    assert result_small["p_value"] == 1.0
    assert result_small["is_normal"] is True

    # Zero variance
    result_flat = jarque_bera_test([2.5, 2.5, 2.5, 2.5])
    assert result_flat["stat"] == 0.0
    assert result_flat["p_value"] == 1.0
    assert result_flat["is_normal"] is True


def test_kupiec_pof_exact_match():
    """Test Kupiec POF test where observed failures equals expected (should pass)."""
    # 95% VaR over 100 days. Expected failures = 5.
    # Observed failures = 5.
    result = kupiec_pof_test(failures=5, total_observations=100, var_confidence=0.95)
    
    assert result["failures"] == 5
    assert result["total_observations"] == 100
    assert result["failure_rate"] == 0.05
    assert result["stat"] == 0.0  # Log-likelihood ratio should be exactly 0
    assert result["p_value"] == 1.0
    assert result["is_valid"] is True
    assert result["message"] == "Valid Calibration"


def test_kupiec_pof_rejection():
    """Test Kupiec POF test where observed failures deviates severely (should fail)."""
    # 95% VaR over 100 days. Expected failures = 5.
    # Observed failures = 25 (way too high, model underestimating risk).
    result_high = kupiec_pof_test(failures=25, total_observations=100, var_confidence=0.95)
    
    assert result_high["is_valid"] is False
    assert result_high["p_value"] < 0.05
    assert result_high["message"] == "Invalid Calibration (Model Failure)"

    # Observed failures = 0 over 200 days (too low, model too conservative).
    result_low = kupiec_pof_test(failures=0, total_observations=200, var_confidence=0.95)
    assert result_low["is_valid"] is False
    assert result_low["p_value"] < 0.05


def test_kupiec_pof_boundary_cases():
    """Test Kupiec POF boundary cases (failures = 0, failures = total, empty)."""
    # 0 failures out of 10 observations (not enough to reject null hypothesis)
    result_zero = kupiec_pof_test(failures=0, total_observations=10, var_confidence=0.95)
    assert result_zero["is_valid"] is True
    assert result_zero["p_value"] >= 0.05

    # failures = total
    result_all = kupiec_pof_test(failures=50, total_observations=50, var_confidence=0.95)
    assert result_all["is_valid"] is False
    assert result_all["p_value"] < 0.05

    # 0 total observations
    result_empty = kupiec_pof_test(failures=0, total_observations=0, var_confidence=0.95)
    assert result_empty["stat"] == 0.0
    assert result_empty["p_value"] == 1.0
    assert result_empty["is_valid"] is True

    # Invalid arguments
    with pytest.raises(ValueError):
        kupiec_pof_test(failures=-1, total_observations=10)
    with pytest.raises(ValueError):
        kupiec_pof_test(failures=11, total_observations=10)


def test_evaluate_statistical_health():
    """Test combined evaluate_statistical_health function."""
    # 1. Insufficient data
    res_short = evaluate_statistical_health([1.0, 2.0])
    assert res_short["status"] == "INSUFFICIENT_DATA"

    # 2. Excellent health (normal, independent, valid VaR)
    # 95% VaR over 25 days. Observed = 1 failure.
    # Deterministic sequence with low autocorrelation and near-normality
    excellent_returns = [
        -0.326, 1.064, -0.243, 0.469, -0.41, -0.543, -0.109, 0.626, -1.919, 0.406,
        1.053, 0.288, 0.092, -1.876, 0.43, -1.874, -0.945, 0.962, 0.282, 2.544,
        1.35, -2.334, -0.082, -0.58, -0.774
    ]
    res_excellent = evaluate_statistical_health(
        returns=excellent_returns,
        failures=1,
        total_observations=25,
        var_confidence=0.95
    )
    assert res_excellent["status"] == "EXCELLENT"
    assert res_excellent["passed_autocorrelation"] is True
    assert res_excellent["passed_normality"] is True
    assert res_excellent["passed_var_calibration"] is True

    # 3. Good health (independent, valid VaR, but rejected normality)
    # Add a massive outlier to reject normality (fat tails), but keep autocorrelation low
    fat_returns = excellent_returns.copy()
    fat_returns[10] = 20.0  # Massive outlier
    res_good = evaluate_statistical_health(
        returns=fat_returns,
        failures=1,
        total_observations=25,
        var_confidence=0.95
    )
    assert res_good["status"] == "GOOD"
    assert res_good["passed_autocorrelation"] is True
    assert res_good["passed_normality"] is False
    assert res_good["passed_var_calibration"] is True

    # 4. Critical health (autocorrelated)
    trend_returns = [float(i) for i in range(20)]
    res_critical = evaluate_statistical_health(
        returns=trend_returns,
        failures=1,
        total_observations=20,
        var_confidence=0.95
    )
    assert res_critical["status"] == "CRITICAL"
    assert res_critical["passed_autocorrelation"] is False
