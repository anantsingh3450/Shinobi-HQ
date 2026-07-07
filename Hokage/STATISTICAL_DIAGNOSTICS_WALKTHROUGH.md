# Hokage Institutional Statistical Diagnostics Walkthrough

This document outlines the design, mathematical formulations, implementation, and usage of the **Institutional Statistical Diagnostics Engine** implemented in **Phase 6.6A**.

Consistent with the **Hokage Engineering Constitution**, all statistical metrics are computed using pure, deterministic mathematical algorithms in Python, with **zero external statistics library dependencies** (e.g., no `scipy`, `statsmodels`, or `numpy`).

---

## 1. Under-The-Hood Mathematics

### 1.1 Ljung-Box Q-Test (Autocorrelation Detection)
The Ljung-Box Q-test evaluates whether any group of autocorrelations of a returns series is significantly different from zero, which detects predictability or volatility clustering (ARCH effects).

**Mathematical Formulation:**
$$Q(h) = n(n+2) \sum_{k=1}^h \frac{\hat{\rho}_k^2}{n-k}$$
where:
*   $n$ is the sample size (number of return observations).
*   $h$ is the number of lags tested (defaulting to $\min(10, n // 5)$).
*   $\hat{\rho}_k$ is the sample autocorrelation at lag $k$:
    $$\hat{\rho}_k = \frac{\text{autocovariance}(x, k)}{\text{autocovariance}(x, 0)}$$

**Hypotheses:**
*   **Null Hypothesis ($H_0$):** The return series is independent white noise (no serial correlation).
*   **Alternative Hypothesis ($H_1$):** The return series exhibits significant serial correlation (predictable residuals or structural bias).

Under $H_0$, $Q(h)$ asymptotically follows a Chi-square distribution with $h$ degrees of freedom ($Q(h) \sim \chi^2_h$). If the $p$-value is $< 0.05$, we reject $H_0$, indicating significant autocorrelation.

---

### 1.2 Jarque-Bera Test (Normality of Returns)
The Jarque-Bera test determines whether a sample return series exhibits skewness and kurtosis consistent with a normal distribution. In financial returns, this is used to identify fat-tail risks (leptokurtosis) and asymmetry.

**Mathematical Formulation:**
$$JB = \frac{n}{6} \left( S^2 + \frac{(K-3)^2}{4} \right)$$
where:
*   $n$ is the sample size.
*   $S$ is the sample skewness:
    $$S = \frac{\frac{1}{n} \sum_{i=1}^n (x_i - \bar{x})^3}{\left( \frac{1}{n} \sum_{i=1}^n (x_i - \bar{x})^2 \right)^{3/2}}$$
*   $K$ is the sample kurtosis (excess kurtosis is $K - 3$):
    $$K = \frac{\frac{1}{n} \sum_{i=1}^n (x_i - \bar{x})^4}{\left( \frac{1}{n} \sum_{i=1}^n (x_i - \bar{x})^2 \right)^2}$$

**Hypotheses:**
*   **Null Hypothesis ($H_0$):** The returns are normally distributed ($S = 0$, $K = 3$).
*   **Alternative Hypothesis ($H_1$):** The returns are non-normally distributed (fat-tailed or skewed).

Under $H_0$, $JB$ asymptotically follows a Chi-square distribution with 2 degrees of freedom ($JB \sim \chi^2_2$). If the $p$-value is $< 0.05$, we reject $H_0$. *Note: Financial returns are frequently non-normal; a rejection here serves as a warning to scale up risk thresholds and use robust critical values.*

---

### 1.3 Kupiec Proportion of Failures (POF) Test (VaR Calibration)
The Kupiec POF test evaluates whether the number of Value-at-Risk (VaR) breaches in a shadow trading session is statistically consistent with the target risk confidence level.

**Mathematical Formulation:**
Let $N$ be the number of daily returns, $x$ be the number of VaR breaches (days where the loss exceeded the $95\%$ VaR limit), and $p = 1 - 0.95 = 0.05$ be the expected failure rate.
The likelihood ratio (LR) statistic is:
$$LR_{POF} = -2 \ln \left( \frac{(1-p)^{N-x} p^x}{(1-\hat{p})^{N-x} \hat{p}^x} \right)$$
where $\hat{p} = \frac{x}{N}$ is the observed failure rate.

**Hypotheses:**
*   **Null Hypothesis ($H_0$):** The VaR model is correctly calibrated (observed failure rate matches target).
*   **Alternative Hypothesis ($H_1$):** The VaR model is invalid (either under-estimating risk with too many failures, or over-conservatively locking up capital with too few).

Under $H_0$, $LR_{POF} \sim \chi^2_1$. If $LR_{POF} > 3.841$ (the $95\%$ critical value, p-value $< 0.05$), we reject the model as statistically invalid.

---

### 1.4 Pure Python Chi-Square p-value Solver
To obtain the exact $p$-value for any Chi-square statistic $\chi^2$ with $d$ degrees of freedom without external libraries, we implement the regularized upper incomplete gamma function:
$$p = Q\left(\frac{d}{2}, \frac{\chi^2}{2}\right)$$
We evaluate this dynamically:
1.  For $x < a + 1$, we use the series expansion:
    $$P(a, x) = \frac{x^a e^{-x}}{\Gamma(a)} \sum_{n=0}^\infty \frac{x^n}{a(a+1)...(a+n)}$$
    and return $Q(a, x) = 1 - P(a, x)$.
2.  For $x \ge a + 1$, we use Gautschi's continued fraction evaluated via Lentz's method:
    $$Q(a, x) = \frac{x^a e^{-x}}{\Gamma(a)} \left( \frac{1}{x + 1 - a + \frac{1(a - 1)}{x + 3 - a + \frac{2(a - 2)}{x + 5 - a + ...}}} \right)$$
3.  $\Gamma(a)$ is resolved using the standard library's `math.lgamma(a)` to prevent overflow on larger degrees of freedom.

---

## 2. Implementation Details

The engine is completely modularized across the following files:

1.  **[`diagnostics.py`](file:///C:/Users/anant/OneDrive/Documents/AI%20PROJECT/AI%20COMMAND%20CENTRE/Hokage/src/shared/statistics/diagnostics.py)**:
    *   Pure mathematical functions: `ljung_box_test`, `jarque_bera_test`, `kupiec_pof_test`, and `evaluate_statistical_health`.
    *   Includes a rolling historical VaR breach calculator (`calculate_var_breaches`) that automatically extracts VaR failures from any returns series, making the Kupiec POF test completely self-contained.
2.  **[`performance_analytics.py`](file:///C:/Users/anant/OneDrive/Documents/AI%20PROJECT/AI%20COMMAND%20CENTRE/Hokage/src/bots/autonomous/performance_analytics.py)**:
    *   Exposes `get_statistical_diagnostics()`, which queries daily portfolio returns from the SQLite `shadow_daily_performance` table for the active shadow session.
    *   If SQLite is not active or has no daily data, it seamlessly falls back to trade-level returns from the history log (`trade_performance_history.jsonl`), ensuring 100% backward compatibility in JSON mode.
3.  **[`api.py`](file:///C:/Users/anant/OneDrive/Documents/AI%20PROJECT/AI%20COMMAND%20CENTRE/Hokage/src/hokage/dashboard/api.py)**:
    *   Exposes the `GET /api/v1/shadow/diagnostics` REST endpoint.
4.  **[`command_router.py`](file:///C:/Users/anant/OneDrive/Documents/AI%20PROJECT/AI%20COMMAND%20CENTRE/Hokage/src/hokage/router/command_router.py)**:
    *   Registers the `hokage shadow diagnostics` CLI command.

---

## 3. Usage Guide

### 3.1 Command-Line Interface (CLI)
To run diagnostics from the terminal, execute:
```powershell
hokage shadow diagnostics
```

**Example Output:**
```text
=== Hokage Shadow Statistical Diagnostics ===
Overall Health Status: GOOD
Explanation:           Good: No return autocorrelation, and VaR calibration is valid. Normal distribution is rejected (Jarque-Bera) due to fat tails/skewness, which is standard for financial returns.
Data Source:           shadow_session_SHADOW_SES_20260626_123045
Sample Size:           25 observations

1. Ljung-Box Q-Test (Autocorrelation Detection):
   - Q-Statistic:      0.2897
   - p-value:          0.96195
   - Tested Lags:      3
   - Status:           Independent (White Noise) (PASS)

2. Jarque-Bera Test (Normality of Returns):
   - JB-Statistic:     0.0292
   - p-value:          0.98551
   - Skewness:         0.0824
   - Kurtosis:         2.885
   - Status:           Normal (PASS)

3. Kupiec Proportion of Failures (POF) (VaR Calibration):
   - LR-Statistic:     0.0
   - p-value:          1.0
   - Failures / Obs:   1 / 25
   - Failure Rate:     4.00% (Expected: 5.00%)
   - Status:           Valid Calibration (PASS)
=============================================
```

### 3.2 REST API
Query the endpoint via HTTP GET:
```http
GET /api/v1/shadow/diagnostics
```

**JSON Response:**
```json
{
  "status": "GOOD",
  "explanation": "Good: No return autocorrelation, and VaR calibration is valid. Normal distribution is rejected (Jarque-Bera) due to fat tails/skewness, which is standard for financial returns.",
  "passed_autocorrelation": true,
  "passed_normality": true,
  "passed_var_calibration": true,
  "sample_size": 25,
  "session_id": "SHADOW_SES_20260626_123045",
  "data_source": "shadow_session_SHADOW_SES_20260626_123045",
  "ljung_box": {
    "stat": 0.2897,
    "p_value": 0.96195,
    "lags": 3,
    "autocorrelations": [-0.05, 0.02, -0.01],
    "has_autocorrelation": false,
    "message": "Independent (White Noise)"
  },
  "jarque_bera": {
    "stat": 0.0292,
    "p_value": 0.98551,
    "skewness": 0.0824,
    "kurtosis": 2.885,
    "excess_kurtosis": -0.115,
    "is_normal": true,
    "message": "Normal"
  },
  "kupiec": {
    "stat": 0.0,
    "p_value": 1.0,
    "failures": 1,
    "total_observations": 25,
    "failure_rate": 0.04,
    "expected_failure_rate": 0.05,
    "is_valid": true,
    "message": "Valid Calibration"
  }
}
```

### 3.3 Dashboard
Navigate to the **Shadow Trading** tab in the War Room Dashboard. You will see a dedicated **Statistical Diagnostics** card displaying real-time mathematical checkouts, color-coded health indicators, and detail lists for Ljung-Box, Jarque-Bera, and Kupiec POF.
