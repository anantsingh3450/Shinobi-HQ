"""Trade DNA Framework for Hokage — Phase 4C.5D.

Every closed trade generates a Trade DNA record — a compact, queryable
fingerprint capturing the conditions that produced a WIN or LOSS.

Purpose:
    - Future machine learning and pattern discovery
    - Alpha Program regime/sector/grade analytics
    - Capital allocation feedback loop

Storage: hokage_brain/intelligence/trade_dna.jsonl

Queryable by:
    - market regime
    - sector
    - conviction grade
    - holding period range
    - result (WIN | LOSS | BREAKEVEN)
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hokage.memory.resolver import PathResolver

logger = logging.getLogger("Hokage.TradeDNA")

# Conviction grade classification — mirrors ConvictionScoreEngine
_GRADE_MAP = [
    (86, "ELITE"),
    (71, "HIGH"),
    (51, "MODERATE"),
    (31, "WATCH"),
    (0,  "AVOID"),
]


def _score_to_grade(score: int) -> str:
    for threshold, grade in _GRADE_MAP:
        if score >= threshold:
            return grade
    return "AVOID"


class TradeDNAEngine:
    """Records and queries Trade DNA records.

    Minimum DNA schema (approved Phase 4C.5D spec):

        decision_id:     str
        symbol:          str
        market_regime:   str
        sector:          str
        conviction_grade:str
        holding_period_days: int
        result:          "WIN" | "LOSS" | "BREAKEVEN"
        return_pct:      float

    Extended fields added for richer analytics:

        conviction_score, pnl, entry_price, exit_price, exit_reason,
        vix_level, personality_mode, sector_flow, timestamp
    """

    def __init__(self, brain_root: Path | None = None) -> None:
        """Initialize TradeDNAEngine."""
        self._resolver = PathResolver(brain_root)
        intel_dir = self._resolver.resolve_brain_root() / "intelligence"
        intel_dir.mkdir(parents=True, exist_ok=True)
        self._dna_file = intel_dir / "trade_dna.jsonl"

    # ------------------------------------------------------------------
    # Record
    # ------------------------------------------------------------------

    def record_dna(
        self,
        decision_id: str,
        symbol: str,
        market_regime: str,
        sector: str,
        conviction_score: int,
        holding_period_days: int,
        result: str,            # "WIN" | "LOSS" | "BREAKEVEN"
        return_pct: float,
        # Extended fields
        pnl: float = 0.0,
        entry_price: float = 0.0,
        exit_price: float = 0.0,
        exit_reason: str = "",
        vix_level: float = 0.0,
        personality_mode: str = "BALANCED",
        sector_flow: str = "N/A",
    ) -> dict[str, Any]:
        """Record a Trade DNA entry for a closed trade.

        Returns the DNA record dict.
        """
        conviction_grade = _score_to_grade(conviction_score)
        result_upper = result.upper()
        if result_upper not in ("WIN", "LOSS", "BREAKEVEN"):
            result_upper = "WIN" if pnl > 0 else ("LOSS" if pnl < 0 else "BREAKEVEN")

        dna: dict[str, Any] = {
            # Minimum required schema
            "decision_id":          decision_id,
            "symbol":               symbol.upper(),
            "market_regime":        market_regime,
            "sector":               sector.lower(),
            "conviction_grade":     conviction_grade,
            "holding_period_days":  holding_period_days,
            "result":               result_upper,
            "return_pct":           round(return_pct, 4),
            # Extended schema
            "conviction_score":     conviction_score,
            "pnl":                  round(pnl, 2),
            "entry_price":          round(entry_price, 2),
            "exit_price":           round(exit_price, 2),
            "exit_reason":          exit_reason,
            "vix_level":            round(vix_level, 2),
            "personality_mode":     personality_mode,
            "sector_flow":          sector_flow,
            "timestamp":            datetime.now(timezone.utc).isoformat(),
        }

        try:
            with self._dna_file.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(dna, sort_keys=True) + "\n")
            logger.info(
                "Trade DNA recorded: %s %s %s %.2f%% (decision_id=%s)",
                symbol.upper(), conviction_grade, result_upper, return_pct * 100, decision_id or "N/A"
            )
        except Exception as exc:
            logger.error("Failed to record Trade DNA: %s", exc)

        return dna

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------

    def load_all(self) -> list[dict[str, Any]]:
        """Load all Trade DNA records from disk."""
        records: list[dict[str, Any]] = []
        if not self._dna_file.exists():
            return records
        try:
            with self._dna_file.open("r", encoding="utf-8") as fh:
                for line in fh:
                    s = line.strip()
                    if s:
                        records.append(json.loads(s))
        except Exception as exc:
            logger.error("Failed to load Trade DNA: %s", exc)
        return records

    # ------------------------------------------------------------------
    # Query interface
    # ------------------------------------------------------------------

    def query(
        self,
        regime: str | None = None,
        sector: str | None = None,
        conviction_grade: str | None = None,
        holding_period_min: int | None = None,
        holding_period_max: int | None = None,
        result: str | None = None,
    ) -> list[dict[str, Any]]:
        """Filter Trade DNA records by one or more dimensions.

        All provided filters are applied with AND logic.

        Args:
            regime:            Match if value is substring of market_regime (case-insensitive).
            sector:            Exact sector match (case-insensitive).
            conviction_grade:  Exact grade match: ELITE / HIGH / MODERATE / WATCH / AVOID.
            holding_period_min: Minimum inclusive holding days.
            holding_period_max: Maximum inclusive holding days.
            result:            Exact result match: WIN / LOSS / BREAKEVEN.

        Returns:
            Filtered list of DNA record dicts.
        """
        records = self.load_all()
        matched: list[dict[str, Any]] = []

        for r in records:
            if regime and regime.upper() not in r.get("market_regime", "").upper():
                continue
            if sector and r.get("sector", "").lower() != sector.lower():
                continue
            if conviction_grade and r.get("conviction_grade", "").upper() != conviction_grade.upper():
                continue
            if holding_period_min is not None and r.get("holding_period_days", 0) < holding_period_min:
                continue
            if holding_period_max is not None and r.get("holding_period_days", 0) > holding_period_max:
                continue
            if result and r.get("result", "").upper() != result.upper():
                continue
            matched.append(r)

        return matched

    def query_win_rate(self, **kwargs: Any) -> float:
        """Return win rate % for a filtered set of DNA records.

        Accepts same kwargs as query().
        """
        matched = self.query(**kwargs)
        if not matched:
            return 0.0
        wins = sum(1 for r in matched if r.get("result") == "WIN")
        return round((wins / len(matched)) * 100.0, 2)

    def query_avg_return(self, **kwargs: Any) -> float:
        """Return average return_pct for a filtered set of DNA records."""
        matched = self.query(**kwargs)
        if not matched:
            return 0.0
        return round(sum(r.get("return_pct", 0.0) for r in matched) / len(matched), 4)

    def summarize(self) -> dict[str, Any]:
        """Return a compact summary of all DNA records grouped by grade and result."""
        records = self.load_all()
        total = len(records)
        by_grade: dict[str, dict[str, int]] = {}
        by_regime: dict[str, dict[str, int]] = {}
        by_sector: dict[str, dict[str, int]] = {}

        for r in records:
            grade  = r.get("conviction_grade", "UNKNOWN")
            regime = r.get("market_regime", "UNKNOWN")
            sector = r.get("sector", "unknown")
            result = r.get("result", "UNKNOWN")

            for group, key in ((by_grade, grade), (by_regime, regime), (by_sector, sector)):
                if key not in group:
                    group[key] = {"WIN": 0, "LOSS": 0, "BREAKEVEN": 0, "total": 0}
                group[key][result] = group[key].get(result, 0) + 1
                group[key]["total"] += 1

        return {
            "total_dna_records": total,
            "by_conviction_grade": by_grade,
            "by_regime": by_regime,
            "by_sector": by_sector,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def get_dna_path(self) -> Path:
        """Return absolute path to DNA file (for testing)."""
        return self._dna_file
