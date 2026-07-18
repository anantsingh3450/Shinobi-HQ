"""Strategy Portfolio and Registry implementation for Hokage.

Enforces Strategy Evolution and Strategy Specialization Doctrines.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from hokage.memory.resolver import PathResolver

logger = logging.getLogger("Hokage.StrategyPortfolio")

# Commander-approved 2026-07-14: every strategy competes with its own paper
# war chest. Deployed capital and remaining balance are tracked per strategy
# so the Arena scoreboard shows who is spending what.
STRATEGY_STARTING_CAPITAL = 50_000.0


class StrategyPortfolioManager:
    """Manages the portfolio of coexisting specialized trading strategies.

    One instance = one league with its own file, its own seed lineup, and its
    own per-strategy war chest size. The index Dojo and the MCX Arena
    (commander-approved 2026-07-18) each get a separate instance so neither
    ledger can ever touch the other: two different files on disk, two
    different in-memory dicts, promotion/demotion checks scoped to whichever
    instance's `self.portfolio` is being evaluated.
    """

    def __init__(
        self,
        resolver: PathResolver,
        file_name: str = "strategy_portfolio.json",
        starting_capital: float = STRATEGY_STARTING_CAPITAL,
        seed_generator: Any = None,
    ) -> None:
        """Initialize StrategyPortfolioManager.

        Args:
            resolver: Brain-root path resolver.
            file_name: Portfolio JSON filename under the portfolio dir. A
                second league (e.g. MCX) MUST pass a distinct name here —
                this is the entire mechanism that keeps two leagues' capital
                from ever being read/written as one.
            starting_capital: Per-strategy war chest for THIS league's seeds.
            seed_generator: Optional zero-arg callable returning the seed
                portfolio dict (same shape as `_generate_default_portfolio`).
                None keeps the original index Dojo lineup — fully backward
                compatible with every existing call site.
        """
        self.resolver = resolver
        self.portfolio_dir = self.resolver.resolve_portfolio_dir()
        self.portfolio_dir.mkdir(parents=True, exist_ok=True)
        self.file_path = self.portfolio_dir / file_name
        self._starting_capital = starting_capital
        self._seed_generator = seed_generator
        from bots.strategy.evolution import StrategyEvolutionEngine
        self.strategy_evolution = StrategyEvolutionEngine(self.resolver)
        self.portfolio: dict[str, Any] = self._load_portfolio()

    def _load_portfolio(self) -> dict[str, Any]:
        """Load portfolio from disk, returning a default structure if missing/corrupt."""
        if not self.file_path.exists():
            default_portfolio = self._generate_default_portfolio()
            self._save_portfolio_atomic(default_portfolio)
            return default_portfolio

        try:
            with self.file_path.open("r", encoding="utf-8-sig") as fh:
                portfolio = json.load(fh)
            self._ensure_capital_fields(portfolio)
            self._ensure_seed_strategies(portfolio)
            return portfolio
        except Exception as exc:
            logger.error(f"Failed to read strategy portfolio: {exc}")
            default_portfolio = self._generate_default_portfolio()
            return default_portfolio

    def _ensure_capital_fields(self, portfolio: dict[str, Any]) -> None:
        """Migrate persisted portfolios: every strategy gets a war chest."""
        for strat in portfolio.get("strategies", {}).values():
            strat.setdefault(
                "capital",
                {"starting": self._starting_capital, "realized_pnl": 0.0},
            )

    def _ensure_seed_strategies(self, portfolio: dict[str, Any]) -> None:
        """Inject any default-lineup strategy missing from a persisted portfolio.

        Lets a new competitor (e.g. Malfoy) join an existing portfolio without
        wiping the earned stats of strategies already on disk. Only adds what
        is absent by strategy_id; never overwrites an existing entry.
        """
        existing = portfolio.setdefault("strategies", {})
        seeds = self._generate_default_portfolio().get("strategies", {})
        added = False
        for sid, seed in seeds.items():
            if sid not in existing:
                existing[sid] = seed
                added = True
                logger.info(f"Injected missing seed strategy into portfolio: {seed.get('name')} ({sid}).")
        if added:
            portfolio["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._save_portfolio_atomic(portfolio)

    def _save_portfolio_atomic(self, data: dict[str, Any]) -> None:
        """Atomically persist portfolio to disk via write-then-rename."""
        temp_path = self.file_path.with_suffix(".json.tmp")
        try:
            with temp_path.open("w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, sort_keys=True)
                fh.flush()
                import os
                try:
                    os.fsync(fh.fileno())
                except Exception:
                    pass
            temp_path.replace(self.file_path)
        except Exception as exc:
            logger.error(f"Failed to atomically write strategy portfolio: {exc}")

    def save(self) -> None:
        """Persist current in-memory state to disk."""
        self._save_portfolio_atomic(self.portfolio)

    def _seed_strategy(
        self,
        strategy_id: str,
        name: str,
        status: str,
        supported_assets: list[str],
        supported_regimes: list[str],
        notes: str,
        registered_event: str,
        now_str: str,
    ) -> dict[str, Any]:
        """Build a seed strategy with EARNED-ONLY statistics.

        All performance figures start at zero/neutral: earlier seeds shipped
        with fabricated win rates and expectancies for trades that never
        happened, and Kelly sizing consumed them as real evidence. Every
        number in the portfolio must now be earned on live paper data.
        """
        return {
            "strategy_id": strategy_id,
            "name": name,
            "version": "2.0.0",
            "created_at": now_str,
            "status": status,  # ACTIVE, SHADOW_MODE, PROBATION, ARCHIVED
            "supported_assets": supported_assets,
            "supported_regimes": supported_regimes,
            "domain_confidence": {"DEFAULT": 50.0},
            "expectancy": {"DEFAULT": 0.0},
            "win_rate": {"DEFAULT": 0.0},
            "trade_count": {"DEFAULT": 0},
            "capital": {"starting": self._starting_capital, "realized_pnl": 0.0},
            "context_memory": {
                "regime_performance": {},
                "volatility_performance": {},
                "notes": notes,
            },
            "history": [{"timestamp": now_str, "event": registered_event}],
        }

    def _generate_default_portfolio(self) -> dict[str, Any]:
        """Dispatch to this league's seed lineup (index Dojo, unless a
        `seed_generator` was supplied at construction — e.g. the MCX Arena)."""
        if self._seed_generator is not None:
            return self._seed_generator()
        return self._generate_default_index_portfolio()

    def _generate_default_index_portfolio(self) -> dict[str, Any]:
        """Generate the baseline strategy portfolio (Strategy Dojo seeds).

        Evidence-first lineup: the trend/pullback family starts ACTIVE (the
        entry class with the strongest measured live performance on a
        comparable running system, PF ~1.6-3.7); breakout starts in
        SHADOW_MODE (measured live as a net leak, PF ~0.4-0.7) and must earn
        promotion on Hokage's own paper evidence.
        """
        now_str = datetime.now(timezone.utc).isoformat()

        # Every competitor faces the SAME assets. When strategies trade different
        # markets the arena measures the market, not the strategy — MacroBreakout
        # was scoped to CRUDE_OIL/GOLD/SILVER and so could never be compared to
        # MeanReversion on NIFTY.
        #
        # The universe is NSE/BSE index options only, and that is a data
        # constraint rather than a preference: Kite's instruments dump reports
        # lot_size=1 for EVERY MCX chain (CRUDEOIL, GOLD, SILVER, NATURALGAS,
        # COPPER, ZINC), so a real MCX position size can only come from a
        # hand-entered contract-spec table. NFO and BFO report true lot sizes
        # (NIFTY=65, BANKNIFTY=30, SENSEX=20). Commodities return here once
        # their published specs are verified — see _MCX_CONTRACT_MULTIPLIER.
        _UNIVERSE = ["NIFTY", "BANKNIFTY", "SENSEX"]

        s1 = self._seed_strategy(
            "strat-trendpullback-v2",
            "TrendPullback",
            "ACTIVE",
            list(_UNIVERSE),
            ["RISK-ON", "BULL", "BEAR"],
            "EMA(9)/EMA(21) alignment with session-VWAP bias; the entry conduct gate enforces tape agreement.",
            "Registered ACTIVE with zeroed stats: trend/pullback entry family.",
            now_str,
        )
        s2 = self._seed_strategy(
            "strat-macrobreakout-commodities-v1",
            "MacroBreakout",
            "SHADOW_MODE",
            list(_UNIVERSE),
            ["RISK-OFF", "HIGH-VOLATILITY"],
            "Breakout entries demoted to shadow: measured elsewhere as a live net leak.",
            "Demoted to SHADOW_MODE with zeroed stats: breakouts must earn promotion.",
            now_str,
        )
        s3 = self._seed_strategy(
            "strat-meanreversion-sideways-v1",
            "MeanReversion",
            "SHADOW_MODE",
            list(_UNIVERSE),
            ["SIDEWAYS", "LOW-VOLATILITY"],
            "Range rotation family; candidate habitat is balance days.",
            "Registered SHADOW_MODE with zeroed stats: range family gathers evidence.",
            now_str,
        )
        # 4th competitor: derived from the Malfoy benchmark bot's measured
        # edges (EMA9/21 + session-VWAP momentum, midday blackout + 14:00
        # cutoff conduct gates, tiered premium exit ladder), extended with
        # Hokage's own evolution edges — India-VIX-adaptive sizing and a
        # triple-barrier meta-label filter — so it can surpass its source.
        s4 = self._seed_strategy(
            "strat-malfoy-momentum-v1",
            "Malfoy",
            "SHADOW_MODE",
            list(_UNIVERSE),
            ["RISK-ON", "BULL", "HIGH-VOLATILITY"],
            "Disciplined intraday momentum (EMA9/21 + VWAP bias, conduct-gated); Hokage edge: VIX-adaptive sizing + meta-label filter.",
            "Registered SHADOW_MODE with zeroed stats: Malfoy-derived momentum challenger gathers evidence.",
            now_str,
        )

        return {
            "strategies": {
                s1["strategy_id"]: s1,
                s2["strategy_id"]: s2,
                s3["strategy_id"]: s3,
                s4["strategy_id"]: s4,
            },
            "updated_at": now_str
        }

    def register_strategy(
        self,
        name: str,
        version: str,
        supported_assets: list[str],
        supported_regimes: list[str],
        status: str = "PROBATION",
        parent_strategy_id: str | None = None,
        supporting_evidence: dict[str, Any] | None = None,
    ) -> str:
        """Register a new strategy. Prevents deletion or overwrite."""
        strategy_id = f"strat-{name.lower().replace(' ', '-')}-{str(uuid.uuid4())[:8]}"
        now_str = datetime.now(timezone.utc).isoformat()
        
        new_strat = {
            "strategy_id": strategy_id,
            "name": name,
            "version": version,
            "parent_strategy_id": parent_strategy_id or "",
            "created_at": now_str,
            "status": status,
            "supported_assets": [a.upper() for a in supported_assets],
            "supported_regimes": [r.upper() for r in supported_regimes],
            "domain_confidence": {"DEFAULT": 50.0},
            "expectancy": {"DEFAULT": 0.0},
            "win_rate": {"DEFAULT": 50.0},
            "drawdown": {"DEFAULT": 0.0},
            "sharpe_ratio": {"DEFAULT": 1.0},
            "trade_count": {"DEFAULT": 0},
            "supporting_evidence": supporting_evidence or {},
            "capital": {"starting": self._starting_capital, "realized_pnl": 0.0},
            "context_memory": {
                "regime_performance": {},
                "volatility_performance": {}
            },
            "history": [
                {"timestamp": now_str, "event": f"Strategy registered with initial status: {status}."}
            ]
        }
        
        self.portfolio["strategies"][strategy_id] = new_strat
        self.portfolio["updated_at"] = now_str
        self.save()
        logger.info(f"Registered new strategy: {name} (ID: {strategy_id}) under {status} status.")
        return strategy_id

    def select_strategy(
        self,
        asset: str,
        market_regime: str = "BULL",
        volatility_regime: str = "LOW"
    ) -> dict[str, Any]:
        """Automatically select the highest validated strategy for a given domain and environment.
        
        Follows the Strategy Specialization Doctrine: index success never overwrites commodity success.
        """
        asset_upper = asset.upper()
        market_regime_upper = market_regime.upper()
        volatility_regime_upper = volatility_regime.upper()

        best_strategy = None
        highest_score = -1.0
        selection_reason = ""

        # Filter active strategies that support this asset or domain
        for s_id, strat in self.portfolio["strategies"].items():
            if strat["status"] == "ARCHIVED":
                continue

            # Check if asset is supported or if it's default
            supports_asset = (asset_upper in strat["supported_assets"])
            supports_regime = (market_regime_upper in strat["supported_regimes"])

            # Compute match score
            # Base confidence score for this specific asset domain
            confidence = strat["domain_confidence"].get(asset_upper, strat["domain_confidence"].get("DEFAULT", 50.0))
            
            # Score multiplier based on regime alignment
            multiplier = 1.0
            if supports_asset:
                multiplier += 0.2
            if supports_regime:
                multiplier += 0.2

            # Probation strategies compete only for evaluation and cannot override mature ones for live execution
            if strat["status"] == "PROBATION":
                multiplier *= 0.5  # Penalize probation strategies to prevent premature execution

            final_score = confidence * multiplier

            if final_score > highest_score:
                highest_score = final_score
                best_strategy = strat
                selection_reason = (
                    f"Selected strategy '{strat['name']}' ({s_id}) for asset {asset_upper}. "
                    f"Domain confidence: {confidence}%. Regime alignment: {market_regime_upper} "
                    f"(Match={supports_regime}). Status: {strat['status']}."
                )

        if not best_strategy:
            # Fallback: the flagship trend family, else the first registered
            # strategy (portfolios persisted before the v2 seeds keep working).
            strategies = self.portfolio["strategies"]
            fallback_id = "strat-trendpullback-v2"
            if fallback_id not in strategies:
                fallback_id = next(iter(strategies))
            best_strategy = strategies[fallback_id]
            selection_reason = f"No specialized match found. Defaulted to '{best_strategy['name']}'."

        return {
            "strategy": best_strategy,
            "score": highest_score,
            "reason": selection_reason
        }

    def record_trade_outcome(
        self,
        strategy_id: str,
        asset: str,
        is_win: bool,
        pnl: float,
        market_regime: str = "BULL"
    ) -> None:
        """Gradually update strategy domain confidence, win rate, and expectancy using evidence.
        
        Confidence evolves gradually; isolated wins or losses never cause huge spikes or drops.
        """
        strat = self.portfolio["strategies"].get(strategy_id)
        if not strat:
            logger.error(f"Strategy ID {strategy_id} not found in portfolio.")
            return

        asset_upper = asset.upper()
        now_str = datetime.now(timezone.utc).isoformat()

        # Get existing metrics
        count = strat["trade_count"].get(asset_upper, 0)
        win_rate = strat["win_rate"].get(asset_upper, 50.0)
        expectancy = strat["expectancy"].get(asset_upper, 0.0)
        confidence = strat["domain_confidence"].get(asset_upper, 50.0)

        # Update metrics incrementally
        new_count = count + 1
        new_win_rate = ((win_rate * count) + (100.0 if is_win else 0.0)) / new_count
        new_expectancy = ((expectancy * count) + pnl) / new_count

        # Update regime-specific metrics
        regime_upper = market_regime.upper()
        regime_stats = strat.setdefault("regime_stats", {}).setdefault(regime_upper, {"trade_count": 0, "win_rate": 50.0})
        reg_count = regime_stats["trade_count"]
        reg_win_rate = regime_stats["win_rate"]
        new_reg_count = reg_count + 1
        new_reg_win_rate = ((reg_win_rate * reg_count) + (100.0 if is_win else 0.0)) / new_reg_count
        regime_stats["trade_count"] = new_reg_count
        regime_stats["win_rate"] = round(new_reg_win_rate, 2)

        # Update pnl_history and calculate drawdown & Sharpe ratio
        pnl_history = strat.setdefault("pnl_history", {}).setdefault(asset_upper, [])
        pnl_history.append(pnl)
        
        import math
        n = len(pnl_history)
        mean_pnl = sum(pnl_history) / n
        if n > 1:
            variance = sum((x - mean_pnl) ** 2 for x in pnl_history) / (n - 1)
            std_pnl = math.sqrt(variance)
        else:
            std_pnl = 0.0

        if std_pnl > 0:
            sharpe = mean_pnl / std_pnl
        else:
            sharpe = 1.0 if mean_pnl >= 0 else -1.0

        cum_pnl = 0.0
        peak = 0.0
        max_dd = 0.0
        for p in pnl_history:
            cum_pnl += p
            if cum_pnl > peak:
                peak = cum_pnl
            dd = peak - cum_pnl
            if dd > max_dd:
                max_dd = dd

        dd_pct = (max_dd / 500000.0) * 100.0 if max_dd > 0 else 0.0

        # Gradual confidence evolution based on evidence count
        # More trades = higher weight to win rate in confidence
        evidence_factor = min(1.0, new_count / 15.0)  # max weight reached after 15 trades
        target_confidence = new_win_rate
        new_confidence = (confidence * (1.0 - 0.1)) + (target_confidence * 0.1)  # slow exponential moving average
        
        # Clip confidence between 10 and 99
        new_confidence = max(10.0, min(99.0, round(new_confidence, 2)))

        # Update strategy dict
        strat["trade_count"][asset_upper] = new_count
        strat["win_rate"][asset_upper] = round(new_win_rate, 2)
        strat["expectancy"][asset_upper] = round(new_expectancy, 2)
        strat["domain_confidence"][asset_upper] = new_confidence
        strat.setdefault("drawdown", {})[asset_upper] = round(dd_pct, 4)
        strat.setdefault("sharpe_ratio", {})[asset_upper] = round(sharpe, 4)

        # Keep default/overall metrics in sync for the pipeline check
        strat["trade_count"]["DEFAULT"] = new_count
        strat["win_rate"]["DEFAULT"] = round(new_win_rate, 2)
        strat["expectancy"]["DEFAULT"] = round(new_expectancy, 2)
        strat["domain_confidence"]["DEFAULT"] = new_confidence
        strat["drawdown"]["DEFAULT"] = round(dd_pct, 4)
        strat["sharpe_ratio"]["DEFAULT"] = round(sharpe, 4)
        
        # Also copy histories to default key
        strat.setdefault("pnl_history", {}).setdefault("DEFAULT", pnl_history)

        # War chest: realized PnL settles into the strategy's own capital.
        capital = strat.setdefault(
            "capital", {"starting": STRATEGY_STARTING_CAPITAL, "realized_pnl": 0.0}
        )
        capital["realized_pnl"] = round(capital.get("realized_pnl", 0.0) + pnl, 2)

        log_msg = f"Recorded trade outcome for {strat['name']} on {asset_upper}: Win={is_win}, PnL={pnl:.2f}. " \
                  f"New Win Rate: {new_win_rate:.1f}%, Expectancy: {new_expectancy:.1f}, Confidence: {new_confidence:.1f}%."
        strat["history"].append({"timestamp": now_str, "event": log_msg})
        logger.info(log_msg)

        # Run promotion/demotion check
        self._evaluate_strategy_promotion_demotion(strategy_id, asset_upper)

        self.portfolio["updated_at"] = now_str
        self.save()

    def _evaluate_strategy_promotion_demotion(self, strategy_id: str, asset: str) -> None:
        """Run promotion/demotion checks using statistically meaningful evidence."""
        strat = self.portfolio["strategies"][strategy_id]
        
        # Demotion Policy: ACTIVE -> ARCHIVED
        count = strat["trade_count"].get(asset, 0)
        win_rate = strat["win_rate"].get(asset, 50.0)
        expectancy = strat["expectancy"].get(asset, 0.0)
        status = strat["status"]
        if status in ("ACTIVE", "PRODUCTION") and count >= 10 and win_rate < 45.0 and expectancy < 0:
            strat["status"] = "ARCHIVED"
            now_str = datetime.now(timezone.utc).isoformat()
            event_msg = f"DEMOTION: Strategy {strat['name']} demoted to ARCHIVED for {asset} due to negative expectancy after {count} trades (Win Rate: {win_rate}%, Expectancy: {expectancy})."
            strat["history"].append({"timestamp": now_str, "event": event_msg})
            logger.info(event_msg)
            self.save()
            return

        # Find active production strategy in same specialization domain
        active_production = None
        for s_id, s in self.portfolio["strategies"].items():
            if s["status"] in ("ACTIVE", "PRODUCTION") and s_id != strategy_id:
                # Check overlap in assets
                if any(a in s.get("supported_assets", []) for a in strat.get("supported_assets", [])):
                    active_production = s
                    break

        changed, reason = self.strategy_evolution.evaluate_pipeline_transition(strat, active_production, asset)
        if changed:
            logger.info(f"Strategy evolution change: {reason}")
            # If promoted to PRODUCTION/ACTIVE or transitioned, ensure backward compatibility for tests expecting ACTIVE
            if strat["status"] == "PRODUCTION":
                strat["status"] = "ACTIVE"
        self.save()

    def get_capital_report(
        self, deployed_by_strategy: dict[str, float] | None = None
    ) -> list[dict[str, Any]]:
        """Per-strategy war chest report: starting, deployed, available.

        deployed_by_strategy maps strategy_id to the capital currently locked
        in open positions (real for the ACTIVE strategy, simulated for shadow
        strategies). Available = starting + realized_pnl - deployed.
        """
        deployed_by_strategy = deployed_by_strategy or {}
        report = []
        for s_id, strat in self.portfolio.get("strategies", {}).items():
            capital = strat.get(
                "capital", {"starting": self._starting_capital, "realized_pnl": 0.0}
            )
            starting = float(capital.get("starting", self._starting_capital))
            realized = float(capital.get("realized_pnl", 0.0))
            deployed = round(float(deployed_by_strategy.get(s_id, 0.0)), 2)
            report.append(
                {
                    "strategy_id": s_id,
                    "name": strat.get("name", s_id),
                    "status": strat.get("status", "UNKNOWN"),
                    "starting_capital": starting,
                    "realized_pnl": round(realized, 2),
                    "deployed": deployed,
                    "available": round(starting + realized - deployed, 2),
                }
            )
        return report

    def get_selection_explanation(
        self,
        asset: str,
        market_regime: str = "BULL",
        volatility_regime: str = "LOW"
    ) -> str:
        """Explain exactly why a strategy was selected or rejected for a given environment."""
        asset_upper = asset.upper()
        res = self.select_strategy(asset_upper, market_regime, volatility_regime)
        selected_strat = res["strategy"]
        
        explanation = f"--- STRATEGY SELECTION EXPLANATION FOR {asset_upper} ---\n"
        explanation += f"Selected Strategy: {selected_strat['name']} (v{selected_strat['version']})\n"
        explanation += f"Reason: {res['reason']}\n\n"
        explanation += "Coexisting Strategies Audited:\n"

        for s_id, strat in self.portfolio["strategies"].items():
            status = strat["status"]
            conf = strat["domain_confidence"].get(asset_upper, strat["domain_confidence"].get("DEFAULT", 50.0))
            trades = strat["trade_count"].get(asset_upper, 0)
            wr = strat["win_rate"].get(asset_upper, 0.0)
            
            explanation += f"- [{status}] {strat['name']} (ID: {s_id}): "
            explanation += f"Domain Confidence = {conf}%, Trades = {trades}, Win Rate = {wr}%. "
            if s_id == selected_strat["strategy_id"]:
                explanation += "-> SELECTED\n"
            elif status == "ARCHIVED":
                explanation += "-> REJECTED (Archived/Inactive)\n"
            elif status == "PROBATION":
                explanation += "-> REJECTED (Under Probation/Ineligible for Live execution)\n"
            else:
                explanation += "-> REJECTED (Lower matched score)\n"
                
        explanation += "------------------------------------------------------"
        return explanation
