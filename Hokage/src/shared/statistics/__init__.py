"""Newey-West HAC Statistical Engine package.

Provides Heteroskedasticity and Autocorrelation Consistent (HAC) covariance estimation,
optimal lag selection, HAC standard errors, and dual hypothesis testing.
"""
from __future__ import annotations

from shared.statistics.covariance import mean, autocovariance, hac_variance
from shared.statistics.lag_selection import (
    newey_west_1994_bandwidth,
    ar1_bandwidth,
    rule_of_thumb_bandwidth,
    get_optimal_lag
)
from shared.statistics.newey_west import newey_west_se
from shared.statistics.statistics import sample_std, hac_t_test

__all__ = [
    "mean",
    "autocovariance",
    "hac_variance",
    "newey_west_1994_bandwidth",
    "ar1_bandwidth",
    "rule_of_thumb_bandwidth",
    "get_optimal_lag",
    "newey_west_se",
    "sample_std",
    "hac_t_test"
]
