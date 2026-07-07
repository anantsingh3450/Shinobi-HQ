"""Performance Analytics Engine for Hokage — Phase 4C.5D.

Logs EOD trade outcomes and provides deep analytics across:
- Market regimes, sectors, conviction grades, holding periods
- Win rate, profit factor, expectancy, Sharpe ratio (risk-free = 0%)
- Drawdown analytics, rolling metrics, performance reports

Every outcome record carries a decision_id linking back to the
Decision Journal for full cross-system auditability.
"""
from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hokage.memory.resolver import PathResolver

logger = logging.getLogger("Hokage.PerformanceAnalytics")

# Grade thresholds — mirrors ConvictionScoreEngine
_CONVICTION_GRADES = [
    (86, "ELITE"),
    (71, "HIGH"),
    (51, "MODERATE"),
    (31, "WATCH"),
    (0,  "AVOID"),
]


def _classify_conviction_grade(score: int) -> str:
    for threshold, grade in _CONVICTION_GRADES:
        if score >= threshold:
            return grade
    return "AVOID"


class PerformanceAnalyticsEngine:
    """Records trade outcomes and computes rolling analytics by regime, sector, and conviction."""

    def __init__(self, brain_root: Path | None = None) -> None:
        """Initialize PerformanceAnalyticsEngine."""
        self._resolver = PathResolver(brain_root)
        self._portfolio_dir = self._resolver.resolve_portfolio_dir()
        self._portfolio_dir.mkdir(parents=True, exist_ok=True)
        self._history_file = self._portfolio_dir / "trade_performance_history.jsonl"
        self._report_key = "performance_report.json"

        # Resolve IntelligenceCache lazily to avoid circular imports
        self._cache: Any = None

    def _get_cache(self) -> Any:
        """Lazily resolve IntelligenceCache."""
        if self._cache is None:
            try:
                from bots.autonomous.cache import IntelligenceCache
                self._cache = IntelligenceCache()
            except Exception:
                pass
        return self._cache

    # ------------------------------------------------------------------
    # Record
    # ------------------------------------------------------------------

    def record_trade_outcome(
        self,
        symbol: str,
        sector: str,
        market_regime: str,
        conviction_score: int,
        holding_period_days: int,
        pnl: float,
        is_win: bool,
        volatility_level: float = 0.0,
        asset_class: str = "EQUITY",
        decision_id: str = "",
        entry_price: float = 0.0,
        exit_price: float = 0.0,
        return_pct: float = 0.0,
    ) -> dict[str, Any]:
        """Record completed trade outcome to history log.

        Args:
            decision_id: UUID linking this outcome to a DecisionJournal entry.
            return_pct:  Percentage return on the trade (positive = profit).
        """
        conviction_grade = _classify_conviction_grade(conviction_score)

        record: dict[str, Any] = {
            "timestamp":           datetime.now(timezone.utc).isoformat(),
            "decision_id":         decision_id,
            "symbol":              symbol.upper(),
            "sector":              sector.lower(),
            "market_regime":       market_regime,
            "conviction_score":    conviction_score,
            "conviction_grade":    conviction_grade,
            "holding_period_days": holding_period_days,
            "pnl":                 round(pnl, 2),
            "return_pct":          round(return_pct, 4),
            "is_win":              is_win,
            "volatility_level":    round(volatility_level, 2),
            "asset_class":         asset_class.upper(),
            "entry_price":         round(entry_price, 2),
            "exit_price":          round(exit_price, 2),
        }

        try:
            with self._history_file.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, sort_keys=True) + "\n")
            logger.info(
                "Trade outcome recorded: %s %s PnL=%+.2f decision_id=%s",
                symbol.upper(), "WIN" if is_win else "LOSS", pnl, decision_id or "N/A"
            )
        except Exception as exc:
            logger.error("Failed to record trade outcome: %s", exc)

        return record

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------

    def load_records(self) -> list[dict[str, Any]]:
        """Load all trade performance records from disk."""
        records: list[dict[str, Any]] = []
        if not self._history_file.exists():
            return records
        try:
            with self._history_file.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line_str = line.strip()
                    if line_str:
                        records.append(json.loads(line_str))
        except Exception as exc:
            logger.error("Failed to read trade performance history: %s", exc)
        return records

    # ------------------------------------------------------------------
    # Legacy filter method — backward compatible
    # ------------------------------------------------------------------

    def query_win_rate(self, filter_type: str, filter_val: Any) -> float:
        """Query rolling win rate for a specific segment.

        Supported filter_types: regime, sector, conviction_min,
        volatility_stress, all.
        """
        records = self.load_records()
        if not records:
            return 100.0

        matched = []
        for r in records:
            if filter_type == "regime":
                if filter_val.upper() in r.get("market_regime", "").upper():
                    matched.append(r)
            elif filter_type == "sector":
                if r.get("sector", "").lower() == filter_val.lower():
                    matched.append(r)
            elif filter_type == "conviction_min":
                if r.get("conviction_score", 0) >= int(filter_val):
                    matched.append(r)
            elif filter_type == "volatility_stress":
                if r.get("volatility_level", 0.0) >= float(filter_val):
                    matched.append(r)
            elif filter_type == "all":
                matched.append(r)

        if not matched:
            return 100.0

        wins = sum(1 for r in matched if r.get("is_win", False))
        return round((wins / len(matched)) * 100.0, 2)

    # ------------------------------------------------------------------
    # Core metric computations
    # ------------------------------------------------------------------

    def compute_profit_factor(self, records: list[dict[str, Any]] | None = None) -> float:
        """Gross profit / gross loss. Returns inf if no losses."""
        records = records if records is not None else self.load_records()
        gross_wins = sum(r["pnl"] for r in records if r.get("is_win", False) and r["pnl"] > 0)
        gross_losses = abs(sum(r["pnl"] for r in records if not r.get("is_win", True) and r["pnl"] < 0))
        if gross_losses == 0:
            return round(gross_wins, 2) if gross_wins > 0 else 0.0
        return round(gross_wins / gross_losses, 4)

    def compute_expectancy(self, records: list[dict[str, Any]] | None = None) -> float:
        """(Win rate × avg win) − (loss rate × avg loss). Measured in INR."""
        records = records if records is not None else self.load_records()
        if not records:
            return 0.0
        wins = [r["pnl"] for r in records if r.get("is_win", False)]
        losses = [abs(r["pnl"]) for r in records if not r.get("is_win", True)]
        total = len(records)
        win_rate = len(wins) / total if total > 0 else 0.0
        loss_rate = len(losses) / total if total > 0 else 0.0
        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 0.0
        expectancy = (win_rate * avg_win) - (loss_rate * avg_loss)
        return round(expectancy, 2)

    def compute_sharpe(
        self,
        records: list[dict[str, Any]] | None = None,
        risk_free_rate: float = 0.0,   # Risk-free rate locked at 0% (Phase 4 Alpha)
        trading_days_per_year: int = 252,
    ) -> float:
        """Annualized Sharpe ratio using daily PnL series. Risk-free rate = 0%."""
        records = records if records is not None else self.load_records()
        if len(records) < 2:
            return 0.0

        pnls = [r["pnl"] for r in records]
        n = len(pnls)
        mean_pnl = sum(pnls) / n
        variance = sum((p - mean_pnl) ** 2 for p in pnls) / (n - 1)
        std_dev = math.sqrt(variance) if variance > 0 else 0.0

        if std_dev == 0:
            return 0.0

        # Annualize
        annualized_return = mean_pnl * trading_days_per_year
        annualized_std = std_dev * math.sqrt(trading_days_per_year)
        sharpe = (annualized_return - risk_free_rate) / annualized_std
        return round(sharpe, 4)

    def compute_drawdown_analytics(
        self,
        records: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Compute peak-to-trough drawdown, worst session, and recovery stats."""
        records = records if records is not None else self.load_records()
        if not records:
            return {
                "max_drawdown_pct": 0.0,
                "max_drawdown_inr": 0.0,
                "worst_session_pnl": 0.0,
                "worst_session_symbol": "N/A",
                "recovery_trade_count": 0,
                "consecutive_losses_max": 0,
            }

        # Cumulative equity curve (starting from 0)
        equity = 0.0
        peak = 0.0
        max_drawdown_inr = 0.0
        current_drawdown_start = 0.0
        recovery_count = 0
        in_drawdown = False
        consecutive = 0
        max_consecutive = 0

        for r in records:
            equity += r["pnl"]
            if equity > peak:
                if in_drawdown:
                    recovery_count += 1
                    in_drawdown = False
                peak = equity
                consecutive = 0
            else:
                dd = peak - equity
                if dd > max_drawdown_inr:
                    max_drawdown_inr = dd
                    current_drawdown_start = peak
                in_drawdown = True

            if not r.get("is_win", True):
                consecutive += 1
                max_consecutive = max(max_consecutive, consecutive)
            else:
                consecutive = 0

        # Worst single session
        worst = min(records, key=lambda r: r["pnl"])

        # Max drawdown as %  of peak equity
        max_dd_pct = 0.0
        if current_drawdown_start > 0:
            max_dd_pct = (max_drawdown_inr / current_drawdown_start) * 100.0

        return {
            "max_drawdown_pct": round(max_dd_pct, 2),
            "max_drawdown_inr": round(max_drawdown_inr, 2),
            "worst_session_pnl": worst["pnl"],
            "worst_session_symbol": worst["symbol"],
            "recovery_trade_count": recovery_count,
            "consecutive_losses_max": max_consecutive,
        }

    def compute_holding_period_stats(
        self,
        records: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Average holding period for winners vs losers."""
        records = records if records is not None else self.load_records()
        winners = [r["holding_period_days"] for r in records if r.get("is_win", False)]
        losers  = [r["holding_period_days"] for r in records if not r.get("is_win", True)]
        all_periods = [r["holding_period_days"] for r in records]

        return {
            "avg_hold_all":     round(sum(all_periods) / len(all_periods), 2) if all_periods else 0.0,
            "avg_hold_winners": round(sum(winners) / len(winners), 2) if winners else 0.0,
            "avg_hold_losers":  round(sum(losers) / len(losers), 2) if losers else 0.0,
            "best_hold_days":   min(all_periods) if all_periods else 0,
            "worst_hold_days":  max(all_periods) if all_periods else 0,
        }

    def compute_rolling_metrics(
        self,
        window: int = 20,
        records: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Rolling N-trade win rate and expectancy using the most recent N trades."""
        records = records if records is not None else self.load_records()
        window_records = records[-window:] if len(records) >= window else records
        if not window_records:
            return {"window": window, "win_rate": 100.0, "expectancy": 0.0, "trades": 0}

        wins = [r for r in window_records if r.get("is_win", False)]
        win_rate = round((len(wins) / len(window_records)) * 100.0, 2)
        expectancy = self.compute_expectancy(window_records)
        return {
            "window":      window,
            "win_rate":    win_rate,
            "expectancy":  expectancy,
            "trades":      len(window_records),
        }

    # ------------------------------------------------------------------
    # Dimensional queries
    # ------------------------------------------------------------------

    def query_by_conviction_grade(
        self,
        grade: str,
        records: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Win rate and avg PnL for a specific conviction grade."""
        records = records if records is not None else self.load_records()
        matched = [
            r for r in records
            if r.get("conviction_grade", "").upper() == grade.upper()
        ]
        if not matched:
            return {"grade": grade, "win_rate": 0.0, "avg_pnl": 0.0, "trades": 0}
        wins = sum(1 for r in matched if r.get("is_win", False))
        return {
            "grade":    grade.upper(),
            "win_rate": round((wins / len(matched)) * 100.0, 2),
            "avg_pnl":  round(sum(r["pnl"] for r in matched) / len(matched), 2),
            "trades":   len(matched),
        }

    def query_by_regime(
        self,
        regime: str,
        records: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Win rate and avg PnL for a specific market regime."""
        records = records if records is not None else self.load_records()
        matched = [
            r for r in records
            if regime.upper() in r.get("market_regime", "").upper()
        ]
        if not matched:
            return {"regime": regime, "win_rate": 0.0, "avg_pnl": 0.0, "trades": 0}
        wins = sum(1 for r in matched if r.get("is_win", False))
        return {
            "regime":   regime,
            "win_rate": round((wins / len(matched)) * 100.0, 2),
            "avg_pnl":  round(sum(r["pnl"] for r in matched) / len(matched), 2),
            "trades":   len(matched),
        }

    def query_by_sector(
        self,
        sector: str,
        records: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Win rate and avg PnL for a specific sector."""
        records = records if records is not None else self.load_records()
        matched = [
            r for r in records
            if r.get("sector", "").lower() == sector.lower()
        ]
        if not matched:
            return {"sector": sector, "win_rate": 0.0, "avg_pnl": 0.0, "trades": 0}
        wins = sum(1 for r in matched if r.get("is_win", False))
        return {
            "sector":   sector.lower(),
            "win_rate": round((wins / len(matched)) * 100.0, 2),
            "avg_pnl":  round(sum(r["pnl"] for r in matched) / len(matched), 2),
            "trades":   len(matched),
        }

    # ------------------------------------------------------------------
    # Statistical Diagnostics
    # ------------------------------------------------------------------

    def get_statistical_diagnostics(self) -> dict[str, Any]:
        """Compute institutional statistical diagnostics (Ljung-Box, Jarque-Bera, Kupiec POF).
        
        Queries daily portfolio returns from SQLite for the active shadow session if available,
        otherwise falls back to trade-level return percentages from historical records.
        """
        returns: list[float] = []
        session_id = "N/A"
        data_source = "trade_history"

        try:
            from shared.persistence.sqlite_engine import SqliteStorageEngine
            if SqliteStorageEngine.is_active(self._resolver):
                engine = SqliteStorageEngine(self._resolver)
                conn = engine.get_connection()
                
                # Resolve active or most recent shadow session
                cursor = conn.execute(
                    "SELECT session_id FROM shadow_sessions WHERE status = 'ACTIVE' ORDER BY started_at DESC LIMIT 1;"
                )
                row = cursor.fetchone()
                if not row:
                    cursor = conn.execute(
                        "SELECT session_id FROM shadow_sessions ORDER BY started_at DESC LIMIT 1;"
                    )
                    row = cursor.fetchone()
                    
                if row:
                    session_id = row[0]
                    cursor = conn.execute(
                        "SELECT portfolio_return FROM shadow_daily_performance WHERE session_id = ? ORDER BY timestamp ASC;",
                        (session_id,)
                    )
                    returns = [float(r[0]) for r in cursor.fetchall() if r[0] is not None]
                    if returns:
                        data_source = f"shadow_session_{session_id}"
        except Exception as exc:
            logger.debug("Failed to query daily returns from SQLite for diagnostics: %s", exc)

        # Fallback to trade history if no daily returns found
        if not returns:
            records = self.load_records()
            returns = [r.get("return_pct", 0.0) for r in records]
            data_source = "trade_history"

        # Run diagnostics
        from shared.statistics.diagnostics import evaluate_statistical_health
        health_report = evaluate_statistical_health(returns)
        health_report["session_id"] = session_id
        health_report["data_source"] = data_source
        return health_report

    # ------------------------------------------------------------------
    # Full report
    # ------------------------------------------------------------------

    def generate_performance_report(self) -> dict[str, Any]:
        """Compile all metrics into one report and persist to intelligence cache."""
        records = self.load_records()
        total = len(records)

        win_count = sum(1 for r in records if r.get("is_win", False))
        overall_win_rate = round((win_count / total) * 100.0, 2) if total > 0 else 0.0

        # Compute success metrics
        drawdown_data = self.compute_drawdown_analytics(records)
        risk_adjusted_return = self.compute_sharpe(records)
        after_tax_return = round(sum(r.get("return_pct", 0.0) for r in records) * 0.85, 4)
        capital_preservation = bool(drawdown_data.get("max_drawdown_pct", 0.0) < 10.0)
        
        avg_conv = sum(r.get("conviction_score", 0) for r in records) / total if total > 0 else 0.0
        opportunity_quality = round(avg_conv / 100.0, 4)
        
        high_conv_trades = [r for r in records if r.get("conviction_grade") in ("HIGH", "ELITE")]
        if high_conv_trades:
            high_conv_wins = sum(1 for r in high_conv_trades if r.get("is_win", False))
            conviction_accuracy = round((high_conv_wins / len(high_conv_trades)) * 100.0, 2)
        else:
            conviction_accuracy = 0.0
            
        drawdown_control = round(max(0.0, 100.0 - drawdown_data.get("max_drawdown_pct", 0.0)), 2)

        from bots.autonomous.decision_journal import DecisionJournalSystem
        try:
            journal = DecisionJournalSystem(self._resolver.resolve_brain_root())
            trades_rejected = len(journal.load_rejected_entries())
        except Exception:
            trades_rejected = 0
            
        no_trade_days = 0
        reports_dir = self._resolver.resolve_brain_root() / "reports"
        if reports_dir.exists():
            for f in reports_dir.glob("daily_*.json"):
                try:
                    with f.open("r", encoding="utf-8") as fh:
                        data = json.load(fh)
                        if not data.get("trades_taken"):
                            no_trade_days += 1
                except Exception:
                    pass
        if no_trade_days == 0 and total == 0:
            no_trade_days = 1

        starting_capital = 500000.0
        try:
            from hokage.memory.profile import ProfileService
            profile_service = ProfileService(self._resolver)
            profile = profile_service.get_profile()
            starting_capital = profile.portfolio.starting_capital
        except Exception:
            pass

        capital_preserved = trades_rejected * (starting_capital * 0.01)
        avoided_loss_estimates = trades_rejected * (starting_capital * 0.003)

        report: dict[str, Any] = {
            "generated_at":    datetime.now(timezone.utc).isoformat(),
            "total_trades":    total,
            "win_count":       win_count,
            "loss_count":      total - win_count,
            "overall_win_rate": overall_win_rate,
            "profit_factor":   self.compute_profit_factor(records),
            "expectancy_inr":  self.compute_expectancy(records),
            "sharpe_ratio":    self.compute_sharpe(records),
            "drawdown":        self.compute_drawdown_analytics(records),
            "holding_periods": self.compute_holding_period_stats(records),
            "rolling_20":      self.compute_rolling_metrics(20, records),
            "rolling_10":      self.compute_rolling_metrics(10, records),
            "diagnostics":     self.get_statistical_diagnostics(),
            "by_grade": {
                grade: self.query_by_conviction_grade(grade, records)
                for grade in ("ELITE", "HIGH", "MODERATE", "WATCH", "AVOID")
            },
            "success_metrics": {
                "primary": {
                    "risk_adjusted_return": risk_adjusted_return,
                    "after_tax_return": after_tax_return,
                    "capital_preservation": capital_preservation,
                    "opportunity_quality": opportunity_quality,
                    "conviction_accuracy": conviction_accuracy,
                    "drawdown_control": drawdown_control,
                },
                "secondary": {
                    "trades_executed": total,
                    "trades_rejected": trades_rejected,
                    "no_trade_days": no_trade_days,
                    "capital_preserved": round(capital_preserved, 2),
                    "avoided_loss_estimates": round(avoided_loss_estimates, 2),
                }
            }
        }

        # Persist to intelligence cache
        cache = self._get_cache()
        if cache:
            try:
                cache.write_intelligence(self._report_key, report)
            except Exception as exc:
                logger.error("Failed to persist performance report: %s", exc)

        return report
