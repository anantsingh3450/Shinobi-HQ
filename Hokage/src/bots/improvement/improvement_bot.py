"""ImprovementBot for Hokage — Phase 5: Self-Improving Loop.

Compares historical backtest parameters against actual paper/live trading outcomes,
detects performance and slippage drift, and generates/applies optimization proposals.
Strictly advisory in Hokage Alpha.
"""
from __future__ import annotations

import json
import logging
import uuid
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

from hokage.memory.resolver import PathResolver
from hokage.ledger.prediction_ledger import JsonPredictionLedger
from bots.execution.store.json_trade_store import JsonTradeStore
from bots.strategy.portfolio import StrategyPortfolioManager

from hokage.research import proposals as _proposals

logger = logging.getLogger("Hokage.ImprovementBot")


class ImprovementBot:
    """Detects strategy performance drift and manages optimization proposals."""

    def __init__(
        self,
        portfolio_manager: StrategyPortfolioManager,
        resolver: PathResolver | None = None,
        prediction_ledger: JsonPredictionLedger | None = None,
        trade_store: JsonTradeStore | None = None,
        autonomous_mode: bool = False,
        extra_portfolio_managers: "Sequence[StrategyPortfolioManager] | None" = None,
    ) -> None:
        """Initialize ImprovementBot.

        `extra_portfolio_managers` IS THE MCX ARENA, AND LEAVING IT OUT WAS A
        WHOLE LEAGUE OF DECISIONS THAT COULD NOT LAND. One manager is one
        league with its own file - that separation is deliberate and keeps two
        ledgers' capital apart - but this bot was handed only the index book,
        so `apply_improvement_proposal` could not find any `strat-*-mcx-v1`
        strategy and returned False. The router reported that as "Failed to
        apply proposal. Verify it is pending approval", which blames the
        commander's input for a wiring fault, and the four MCX commodity
        modules are exactly the ones the retirement policy keeps clearing.
        """
        self.portfolio_manager = portfolio_manager
        #: Every book this bot may look in, primary first. Order matters only
        #: for a strategy id that exists in both, which must not happen: the
        #: two leagues' ids are distinct by construction.
        self.portfolio_managers: list[StrategyPortfolioManager] = [portfolio_manager]
        for extra in (extra_portfolio_managers or ()):
            if extra is not None and extra is not portfolio_manager:
                self.portfolio_managers.append(extra)
        self.resolver = resolver or PathResolver()
        self.prediction_ledger = prediction_ledger or JsonPredictionLedger(self.resolver.resolve_predictions_dir())
        self.trade_store = trade_store or JsonTradeStore(self.resolver.resolve_trades_dir())
        self.autonomous_mode = autonomous_mode  # STRICTLY FALSE FOR ALPHA

        # Resolve paths
        self._brain_root = self.resolver.resolve_brain_root()
        self._improvement_dir = self._brain_root / "improvement"
        self._improvement_dir.mkdir(parents=True, exist_ok=True)
        self._proposals_file = self._improvement_dir / "improvement_proposals.jsonl"
        self._journal_dir = self._brain_root / "journal"
        self._journal_dir.mkdir(parents=True, exist_ok=True)
        self._applied_improvements_file = self._journal_dir / "applied_improvements.jsonl"
        self._autopsies_file = self._improvement_dir / "trade_autopsies.jsonl"

    def _find_strategy(
        self, strategy_id: str
    ) -> "tuple[StrategyPortfolioManager | None, dict[str, Any] | None]":
        """The book that holds this strategy, and the record, searching both.

        THE BOOK HAS TO COME BACK WITH THE RECORD. Saving the primary manager
        after editing a record found in the MCX one would write the index book
        and leave the change nowhere - a success message over no change, which
        is the failure this project has paid for most often.
        """
        for manager in self.portfolio_managers:
            strat = (manager.portfolio.get("strategies") or {}).get(strategy_id)
            if strat is not None:
                return manager, strat
        return None, None

    def _known_strategy_ids(self) -> list[str]:
        """Every strategy id across every book, for an error worth reading."""
        out: list[str] = []
        for manager in self.portfolio_managers:
            out.extend((manager.portfolio.get("strategies") or {}).keys())
        return sorted(set(out))

    def analyze_performance_drift(self, strategy_id: str, asset: str = "DEFAULT") -> dict[str, Any]:
        """Compare backtest parameters vs. actual execution metrics for a strategy and asset."""
        _, strat = self._find_strategy(strategy_id)
        if not strat:
            raise ValueError(
                f"Strategy {strategy_id} not found in any portfolio book "
                f"(searched {len(self.portfolio_managers)}). Known: "
                f"{', '.join(self._known_strategy_ids()) or 'none'}")

        asset_upper = asset.upper()

        # 1. Fetch backtest benchmarks from supporting evidence
        evidence = strat.get("supporting_evidence", {})
        backtest_wr = float(evidence.get("backtest_win_rate", 55.0))
        backtest_exp = float(evidence.get("backtest_expectancy", 0.0))
        backtest_dd = float(evidence.get("max_drawdown", evidence.get("backtest_drawdown", 15.0)))

        # 2. Fetch actual portfolio outcomes
        actual_wr = float(strat.get("win_rate", {}).get(asset_upper, strat.get("win_rate", {}).get("DEFAULT", 50.0)))
        actual_exp = float(strat.get("expectancy", {}).get(asset_upper, strat.get("expectancy", {}).get("DEFAULT", 0.0)))
        actual_dd = float(strat.get("drawdown", {}).get(asset_upper, strat.get("drawdown", {}).get("DEFAULT", 0.0)))
        trade_count = int(strat.get("trade_count", {}).get(asset_upper, strat.get("trade_count", {}).get("DEFAULT", 0)))

        # 3. Compute slippage drift from trade records
        avg_slippage = 0.0
        slippage_count = 0
        try:
            # Cross-reference with trade authorizations or predictions to get target prices
            auths_file = self._journal_dir / "trade_authorizations.jsonl"
            target_prices = {}
            if auths_file.exists():
                with auths_file.open("r", encoding="utf-8") as fh:
                    for line in fh:
                        if line.strip():
                            auth_data = json.loads(line.strip())
                            # Store target price by asset and closest timestamp or simply proposal_id if present
                            asset_key = auth_data.get("asset", "").upper()
                            target_prices[asset_key] = float(auth_data.get("entry_price", 0.0))

            # Load actual trades
            trades = self.trade_store.load_all()
            strategy_name_lower = strat.get("name", "").lower()
            matching_trades = [
                t for t in trades 
                if t.strategy_name.lower() == strategy_name_lower and t.market.upper() == asset_upper
            ]

            if matching_trades:
                slippage_sum = 0.0
                for trade in matching_trades:
                    # Target price from auths or fallback to trade entry price (0 slippage)
                    target = target_prices.get(asset_upper, trade.entry_price)
                    slippage = abs(trade.entry_price - target)
                    slippage_sum += slippage
                    slippage_count += 1
                if slippage_count > 0:
                    avg_slippage = slippage_sum / slippage_count
        except Exception as exc:
            logger.warning(f"Error computing slippage drift: {exc}")

        # Calculate drifts
        win_rate_drift = actual_wr - backtest_wr
        expectancy_drift = actual_exp - backtest_exp
        drawdown_drift = actual_dd - backtest_dd

        return {
            "strategy_id": strategy_id,
            "strategy_name": strat.get("name", ""),
            "asset": asset_upper,
            "trade_count": trade_count,
            "backtest": {
                "win_rate": backtest_wr,
                "expectancy": backtest_exp,
                "drawdown": backtest_dd
            },
            "actual": {
                "win_rate": actual_wr,
                "expectancy": actual_exp,
                "drawdown": actual_dd,
                "avg_slippage": avg_slippage
            },
            "drift": {
                "win_rate_drift": round(win_rate_drift, 2),
                "expectancy_drift": round(expectancy_drift, 2),
                "drawdown_drift": round(drawdown_drift, 2),
                "slippage_drift": round(avg_slippage, 2)
            }
        }

    def generate_improvement_proposals(self) -> list[dict[str, Any]]:
        """Scan all active or probation strategies and generate advisory optimization proposals."""
        logger.info("Generating advisory improvement proposals.")
        strategies = self.portfolio_manager.portfolio.get("strategies", {})
        proposals = []

        # Load existing proposals to prevent duplicates or preserve history
        existing_proposals = self.load_proposals()
        existing_keys = {
            (p["strategy_id"], p["asset"], p["action"]): p["proposal_id"] 
            # BOTH spellings. sweep_lab and weekly_audit write "PENDING"
            # and this read "PENDING_APPROVAL", so the measured proposals -
            # the only ones carrying real evidence - were invisible to every
            # duplicate check and to `hokage proposals` alike.
            for p in existing_proposals if _proposals.is_pending(p.get("status"))
        }

        for strat_id, strat in strategies.items():
            if strat.get("status") == "ARCHIVED":
                continue

            # Analyze default drift and asset-specific drifts
            assets_to_check = set(strat.get("supported_assets", []))
            if not assets_to_check:
                assets_to_check.add("DEFAULT")

            for asset in assets_to_check:
                try:
                    drift_stats = self.analyze_performance_drift(strat_id, asset)
                except Exception as exc:
                    logger.error(f"Failed to run drift analysis for {strat_id} {asset}: {exc}")
                    continue

                trade_count = drift_stats["trade_count"]
                if trade_count < 3:
                    # Insufficient execution history to reliably detect drift
                    continue

                wr_drift = drift_stats["drift"]["win_rate_drift"]
                dd_drift = drift_stats["drift"]["drawdown_drift"]
                actual_wr = drift_stats["actual"]["win_rate"]
                actual_dd = drift_stats["actual"]["drawdown"]

                # Heuristics for generating proposals
                # 1. Severe underperformance -> DEMOTE + RISK_MULTIPLIER
                if wr_drift <= -10.0 or dd_drift >= 5.0 or actual_wr < 45.0:
                    action = "DEMOTE"
                    previous_status = strat.get("status", "ACTIVE")
                    proposed_status = "PROBATION" if previous_status == "ACTIVE" else "ARCHIVED"
                    
                    prev_values = {"status": previous_status, "risk_multiplier": 1.0}
                    new_values = {"status": proposed_status, "risk_multiplier": 0.5}
                    
                    rationale = (
                        f"Severe performance drift detected for {asset}. "
                        f"Actual win rate ({actual_wr}%) is {abs(wr_drift)}% lower than backtest. "
                        f"Actual max drawdown ({actual_dd}%) exceeds backtest drawdown by {dd_drift}%."
                    )
                    expected_imp = (
                        f"Demoting to {proposed_status} and reducing risk multiplier to 0.5x "
                        f"preserves capital, reducing expected drawdown exposure by 50% "
                        f"while the strategy is undergoing parameter recalibration."
                    )
                    
                    self._create_proposal_record(
                        strat_id, strat.get("name", ""), asset, action, prev_values, new_values, rationale, expected_imp, proposals, existing_keys
                    )

                # 2. Mild underperformance or high slippage -> PARAMETER_TUNE
                elif wr_drift <= -5.0 or drift_stats["actual"]["avg_slippage"] > 0.0:
                    action = "PARAMETER_TUNE"
                    
                    # Propose tightening stop loss to cut losses faster
                    current_stop_rule = "Standard 2% stop loss applied."
                    proposed_stop_rule = "Tightened 1.5% stop loss due to negative drift."
                    
                    prev_values = {"stop_loss_rule": current_stop_rule}
                    new_values = {"stop_loss_rule": proposed_stop_rule}
                    
                    rationale = (
                        f"Mild performance drift or execution slippage detected. "
                        f"Win rate drift is {wr_drift}%. Average slippage is {drift_stats['actual']['avg_slippage']:.2f}."
                    )
                    expected_imp = (
                        "Tightening the stop loss cuts losing trades faster, "
                        "which is estimated to improve expectancy by 10-15% under sideways or volatile regimes."
                    )
                    
                    self._create_proposal_record(
                        strat_id, strat.get("name", ""), asset, action, prev_values, new_values, rationale, expected_imp, proposals, existing_keys
                    )

        if proposals:
            # Write new proposals atomically to the ledger
            all_proposals = existing_proposals + [p for p in proposals if p["proposal_id"] not in [x["proposal_id"] for x in existing_proposals]]
            self._save_proposals_atomic(all_proposals)
            
            # Notify Commander for each new proposal
            from bots.strategy.evolution import StrategyEvolutionEngine
            evo_engine = StrategyEvolutionEngine(self.resolver)
            for prop in proposals:
                evo_engine.notify_commander(
                    strategy_id=prop["strategy_id"],
                    change_type="EVOLUTION",
                    reason=f"Advisory improvement proposal {prop['proposal_id']} generated: {prop['rationale']}",
                    evidence={
                        "proposal_id": prop["proposal_id"],
                        "asset": prop["asset"],
                        "action": prop["action"],
                        "expected_improvement": prop["expected_improvement"]
                    },
                    validation_status=prop["status"],
                    confidence=50.0,
                    is_experimental=True
                )

        return proposals

    def _create_proposal_record(
        self, strat_id: str, strat_name: str, asset: str, action: str,
        prev_values: dict[str, Any], new_values: dict[str, Any],
        rationale: str, expected_imp: str, proposals: list[dict[str, Any]],
        existing_keys: dict[tuple[str, str, str], str]
    ) -> None:
        key = (strat_id, asset, action)
        if key in existing_keys:
            # Already exists as pending, do not duplicate
            return

        prop_id = f"prop-{strat_name.lower().replace(' ', '-')}-{str(uuid.uuid4())[:8]}"
        proposal = {
            "proposal_id": prop_id,
            "strategy_id": strat_id,
            "strategy_name": strat_name,
            "asset": asset,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "previous_values": prev_values,
            "new_values": new_values,
            "rationale": rationale,
            "expected_improvement": expected_imp,
            "status": "PENDING_APPROVAL",
            "approving_commander": None,
            "applied_at": None,
            "actual_post_change_performance": None,
            # Stamped as drift rather than left blank: blank means nobody
            # recorded the basis, and "this was never a lab measurement" is a
            # different fact worth keeping.
            "measured_geometry": _proposals.DRIFT_BASIS,
        }
        proposals.append(proposal)

    def apply_improvement_proposal(self, proposal_id: str, commander_name: str) -> bool:
        """Apply a specific improvement proposal. Requires explicit Commander name."""
        if not commander_name or not commander_name.strip():
            raise ValueError("Applying an improvement proposal requires an explicit approving Commander name.")

        proposals = self.load_proposals()
        target_prop = None
        for prop in proposals:
            if prop["proposal_id"] == proposal_id:
                target_prop = prop
                break

        if not target_prop:
            logger.error(f"Proposal {proposal_id} not found.")
            return False

        if not _proposals.is_pending(target_prop["status"]):
            logger.warning(f"Proposal {proposal_id} is already in {target_prop['status']} status.")
            return False

        # A PROPOSAL MEASURED ON A RETIRED BASIS IS NOT EVIDENCE.
        #
        # Until 2026-10-16 this gate rejected every lab-written proposal
        # outright, because they carry status "PENDING" rather than
        # "PENDING_APPROVAL" - so nothing measured could ever be applied.
        # Accepting them makes a second question real: three of them were
        # measured before the audit moved to full geometry with a per-cell
        # stop and raised its bar from 2.0 to 3.16, and one says in its own
        # rationale that it used the 1.25 ATR stop while GOLDM has run 3.0
        # since 2026-08-13.
        #
        # Refusing is the cheap error. Re-running the lab produces a fresh
        # proposal on the current basis in minutes; applying a knob change
        # justified by a retired measurement is how a number from the wrong
        # instrument becomes production.
        if _proposals.is_stale(target_prop.get("measured_geometry")):
            logger.warning(
                f"Proposal {proposal_id} refused: "
                f"{_proposals.describe(target_prop.get('measured_geometry'))}. "
                f"Re-run the lab that produced it and apply the fresh proposal."
            )
            return False

        strat_id = target_prop["strategy_id"]
        # BOTH BOOKS. Until 2026-11-10 this read the index book alone, so every
        # MCX proposal - which is where the four commodity modules and every
        # retirement the policy clears live - failed here and was reported to
        # the commander as if his proposal id were wrong.
        manager, strat = self._find_strategy(strat_id)
        if not strat or manager is None:
            logger.error(
                f"Strategy {strat_id} referenced by proposal {proposal_id} "
                f"not found in any portfolio book (searched "
                f"{len(self.portfolio_managers)}).")
            return False

        # Apply the proposed changes to the strategy portfolio
        new_vals = target_prop["new_values"]
        prev_vals = target_prop["previous_values"]
        asset = target_prop["asset"]
        action = target_prop["action"]

        now_str = datetime.now(timezone.utc).isoformat()

        # ALREADY DONE IS NOT FAILED, AND IT IS NOT APPLIED-BY-ME EITHER.
        #
        # On 2026-11-10 two of three PENDING retirements named modules that
        # `fund_cells.py` had already archived on 11-09: EventRider and
        # MeanReversion. Nothing marks a row APPLIED when the outcome arrives
        # by another route, so they sat PENDING for ever - and a PENDING row
        # SUPPRESSES the re-proposal of the same change, so the table was both
        # lying about the state and muting the measurement of it.
        #
        # The row is closed because its outcome exists, and the log says the
        # state already matched rather than claiming this call changed
        # anything. No new status word: `proposals.py` exists because two
        # spellings of PENDING made measured proposals invisible for weeks.
        already = {k: v for k, v in new_vals.items()
                   if k != "asset" and strat.get(k) == v}
        if already and len(already) == len({k for k in new_vals if k != "asset"}):
            target_prop["status"] = _proposals.APPLIED
            target_prop["approving_commander"] = commander_name
            target_prop["applied_at"] = now_str
            target_prop["already_in_target_state"] = True
            strat.setdefault("history", []).append({
                "timestamp": now_str,
                "event": f"Proposal {proposal_id} closed by {commander_name}: "
                         f"the book already read {already} - recorded, nothing "
                         f"changed.",
            })
            manager.save()
            self._save_proposals_atomic(proposals)
            self._log_applied_improvement_immutable(target_prop)
            logger.info(
                f"Proposal {proposal_id} needed no change: {strat_id} already "
                f"reads {already}. Marked APPLIED so it stops suppressing a "
                f"fresh measurement of the same question.")
            return True

        # Update fields in strategy portfolio
        if "status" in new_vals:
            strat["status"] = new_vals["status"]
            strat.setdefault("history", []).append({
                "timestamp": now_str,
                "event": f"Status updated from {prev_vals.get('status')} to {new_vals['status']} via Commander approved proposal {proposal_id}."
            })

        if "risk_multiplier" in new_vals:
            # We store risk multipliers per asset under a specialized portfolio dictionary
            multipliers = strat.setdefault("risk_multipliers", {})
            multipliers[asset] = new_vals["risk_multiplier"]
            strat.setdefault("history", []).append({
                "timestamp": now_str,
                "event": f"Risk multiplier for {asset} updated to {new_vals['risk_multiplier']}x via proposal {proposal_id}."
            })

        if "stop_loss_rule" in new_vals:
            # Update stop loss rule text in the strategy
            strat["stop_loss_rule"] = new_vals["stop_loss_rule"]
            strat.setdefault("history", []).append({
                "timestamp": now_str,
                "event": f"Stop loss rule updated via proposal {proposal_id}."
            })

        # Update proposal status
        target_prop["status"] = "APPLIED"
        target_prop["approving_commander"] = commander_name
        target_prop["applied_at"] = now_str

        # Persist updated strategy portfolio - THE BOOK THAT HOLDS IT.
        manager.save()

        # Persist updated proposals ledger
        self._save_proposals_atomic(proposals)

        # Log an immutable record to applied_improvements.jsonl (atomic write-then-rename)
        self._log_applied_improvement_immutable(target_prop)

        logger.info(f"Successfully applied improvement proposal {proposal_id} approved by {commander_name}.")
        return True

    def load_proposals(self) -> list[dict[str, Any]]:
        """Load all proposals from the proposals ledger."""
        from shared.persistence.sqlite_engine import SqliteStorageEngine
        if SqliteStorageEngine.is_active(self.resolver):
            engine = SqliteStorageEngine(self.resolver)
            conn = engine.get_connection()
            try:
                cursor = conn.execute("SELECT * FROM improvement_proposals ORDER BY timestamp ASC;")
                proposals = []
                for row in cursor.fetchall():
                    proposals.append({
                        "proposal_id": row["proposal_id"],
                        "strategy_id": row["strategy_id"],
                        "strategy_name": row["strategy_name"],
                        "asset": row["asset"],
                        "timestamp": row["timestamp"],
                        "action": row["action"],
                        "previous_values": json.loads(row["previous_values"]),
                        "new_values": json.loads(row["new_values"]),
                        "rationale": row["rationale"],
                        "expected_improvement": row["expected_improvement"],
                        "status": row["status"],
                        "approving_commander": row["approving_commander"],
                        "applied_at": row["applied_at"],
                        "actual_post_change_performance": json.loads(row["actual_post_change_performance"]) if row["actual_post_change_performance"] else None,
                        # Absent on a database that predates schema 9, which
                        # correctly reads as an unrecorded basis.
                        "measured_geometry": (
                            row["measured_geometry"]
                            if "measured_geometry" in row.keys() else None
                        ),
                    })
                return proposals
            except Exception as exc:
                logger.error(f"Failed to read proposals from SQLite: {exc}")
                return []

        proposals = []
        if not self._proposals_file.exists():
            return proposals
        try:
            with self._proposals_file.open("r", encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        proposals.append(json.loads(line.strip()))
        except Exception as exc:
            logger.error(f"Failed to read proposals ledger: {exc}")
        return proposals

    def _save_proposals_atomic(self, data: list[dict[str, Any]]) -> None:
        """Atomically save proposals list to the proposals ledger."""
        from shared.persistence.sqlite_engine import SqliteStorageEngine
        if SqliteStorageEngine.is_active(self.resolver):
            engine = SqliteStorageEngine(self.resolver)
            conn = engine.get_connection()
            try:
                with conn:
                    for p in data:
                        conn.execute("""
                            INSERT OR REPLACE INTO improvement_proposals (
                                proposal_id, strategy_id, strategy_name, asset, timestamp, action,
                                previous_values, new_values, rationale, expected_improvement, status,
                                approving_commander, applied_at, actual_post_change_performance,
                                measured_geometry
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                        """, (
                            p["proposal_id"], p["strategy_id"], p["strategy_name"], p["asset"],
                            p["timestamp"], p["action"], json.dumps(p["previous_values"]),
                            json.dumps(p["new_values"]), p["rationale"], p["expected_improvement"],
                            p["status"], p.get("approving_commander"), p.get("applied_at"),
                            json.dumps(p.get("actual_post_change_performance")),
                            # INSERT OR REPLACE rewrites the whole row, so
                            # leaving this out would silently strip the basis
                            # off every lab-written proposal on the next save.
                            p.get("measured_geometry"),
                        ))
                logger.info("Saved proposals atomically to SQLite.")
                return
            except Exception as exc:
                logger.error(f"Failed to write proposals to SQLite: {exc}")
                raise exc

        temp_path = self._proposals_file.with_suffix(".tmp")
        try:
            with temp_path.open("w", encoding="utf-8") as fh:
                for prop in data:
                    fh.write(json.dumps(prop, sort_keys=True) + "\n")
                fh.flush()
                try:
                    os.fsync(fh.fileno())
                except Exception:
                    pass
            temp_path.replace(self._proposals_file)
        except Exception as exc:
            logger.error(f"Failed to atomically write proposals ledger: {exc}")

    def _log_applied_improvement_immutable(self, prop: dict[str, Any]) -> None:
        """Atomically log an applied improvement to the immutable ledger."""
        from shared.persistence.sqlite_engine import SqliteStorageEngine
        if SqliteStorageEngine.is_active(self.resolver):
            engine = SqliteStorageEngine(self.resolver)
            conn = engine.get_connection()
            try:
                with conn:
                    conn.execute("""
                        INSERT OR REPLACE INTO applied_improvements (
                            proposal_id, strategy_id, strategy_name, asset, timestamp,
                            previous_values, new_values, rationale, expected_improvement,
                            actual_post_change_performance, approving_commander
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """, (
                        prop["proposal_id"], prop["strategy_id"], prop["strategy_name"], prop["asset"],
                        prop["applied_at"], json.dumps(prop["previous_values"]), json.dumps(prop["new_values"]),
                        prop["rationale"], prop["expected_improvement"],
                        json.dumps(prop.get("actual_post_change_performance")), prop["approving_commander"]
                    ))
                logger.info(f"Logged applied improvement {prop['proposal_id']} to SQLite.")
                return
            except Exception as exc:
                logger.error(f"Failed to write applied improvement to SQLite: {exc}")
                raise exc

        lines = []
        if self._applied_improvements_file.exists():
            try:
                with self._applied_improvements_file.open("r", encoding="utf-8") as fh:
                    for line in fh:
                        if line.strip():
                            lines.append(line)
            except Exception as exc:
                logger.error(f"Failed to read applied improvements: {exc}")

        # Formulate the audit record
        audit_record = {
            "proposal_id": prop["proposal_id"],
            "strategy_id": prop["strategy_id"],
            "strategy_name": prop["strategy_name"],
            "asset": prop["asset"],
            "timestamp": prop["applied_at"],
            "previous_values": prop["previous_values"],
            "new_values": prop["new_values"],
            "rationale": prop["rationale"],
            "expected_improvement": prop["expected_improvement"],
            "actual_post_change_performance": None,
            "approving_commander": prop["approving_commander"]
        }
        lines.append(json.dumps(audit_record, sort_keys=True) + "\n")

        temp_path = self._applied_improvements_file.with_suffix(".tmp")
        try:
            with temp_path.open("w", encoding="utf-8") as fh:
                fh.writelines(lines)
                fh.flush()
                try:
                    os.fsync(fh.fileno())
                except Exception:
                    pass
            temp_path.replace(self._applied_improvements_file)
        except Exception as exc:
            logger.error(f"Failed to atomically write applied improvements log: {exc}")

    @staticmethod
    def _autopsy_identity(record: dict) -> tuple:
        """What makes two autopsy rows the SAME trade.

        A trade_id when there is one. When there is not, the position itself:
        symbol, entry price, and the calendar day it was opened. Two distinct
        entries on one contract at an identical premium on the same day would
        collapse — possible under the 3-per-symbol cap, but far less damaging
        than the alternative, which is what actually happened.
        """
        tid = record.get("trade_id")
        if tid:
            return ("id", tid)
        return ("pos", record.get("symbol"), record.get("entry_price"),
                str(record.get("timestamp") or "")[:10])

    def _autopsy_exists(self, record: dict) -> bool:
        """Has this trade already been autopsied?

        THE FIRST VERSION OF THIS GUARD ONLY MATCHED trade_id, AND THAT MISSED
        85% OF THE PROBLEM. Of 444 rows on file, 378 were EOD square-off
        records carrying NO trade_id at all — 42 real positions written 9x over,
        one CRUDEOIL position on 2026-07-15 alone producing 32 identical rows
        one second apart. Keyed on trade_id they were invisible, so the dedupe
        run on 2026-08-19 removed four rows and left every one of them behind.

        The exit loop that produced them was fixed on 2026-08-17 (it fired once
        per registered paper venue instead of once per position), so this guard
        is the belt to that fix's braces — and it now sees the rows the fix
        could not.

        WHY IT MATTERS: this file is what detect_patterns counts. A position
        autopsied 32 times votes 32 times on whatever the Pattern Reader
        concludes.
        """
        if not self._autopsies_file.exists():
            return False
        identity = self._autopsy_identity(record)
        try:
            with self._autopsies_file.open("r", encoding="utf-8") as fh:
                for line in fh:
                    if not line.strip():
                        continue
                    try:
                        if self._autopsy_identity(json.loads(line)) == identity:
                            return True
                    except json.JSONDecodeError:
                        continue
        except OSError:
            return False
        return False

    def process_autopsy(self, autopsy: Any) -> None:
        """Process and save a TradeAutopsy record."""
        try:
            record = autopsy.to_dict()
            if self._autopsy_exists(record):
                logger.info(
                    f"TradeAutopsy for {autopsy.symbol} (Trade ID: "
                    f"{autopsy.trade_id}) already recorded; not appending a duplicate."
                )
                return
            with self._autopsies_file.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record) + "\n")
            logger.info(f"Saved TradeAutopsy for {autopsy.symbol} (Trade ID: {autopsy.trade_id})")
            
            # Check if we should trigger evolution and LLM journal
            # For this alpha, we'll run it every 5 trades.
            count = 0
            with self._autopsies_file.open("r", encoding="utf-8") as fh:
                count = sum(1 for line in fh if line.strip())
            
            if count > 0 and count % 5 == 0:
                logger.info(f"Autopsy threshold reached ({count}). Writing journal entry.")
                # No strategy id. Autopsies do not carry one (absent in all
                # 122 records on 2026-10-12), so the old argument
                # "strat-autotrend-equities-v1" -- an id in neither
                # portfolio -- was a label on pooled data, not a filter.
                patterns = self.detect_patterns()
                if patterns:
                    from integrations.llm.processor import LLMProcessor
                    llm = LLMProcessor()
                    journal_entry = llm.generate_trading_journal_entry(patterns)
                    
                    from integrations.notifications.telegram_bot import TelegramBotUplink
                    tb = TelegramBotUplink()
                    if tb.enabled:
                        tb.send_message(f"📖 *HOKAGE TRADING JOURNAL*\n\n{journal_entry}")
                    
                    self.evaluate_promotions()
                    
        except Exception as e:
            logger.error(f"Failed to process TradeAutopsy: {e}")

    #: Autopsies an ASSET needs before any rate is reported for it. Below this
    #: the cell carries its count and nothing else — a win rate over three
    #: trades is a coin, and printing one invites acting on it.
    MIN_AUTOPSIES_PER_ASSET = 8

    #: How far back to look. Autopsies go back to July; a regime from three
    #: months ago should not dilute what is happening now.
    PATTERN_WINDOW_DAYS = 90

    def detect_patterns(self, window_days: int | None = None) -> dict[str, Any]:
        """Win rate and stop behaviour PER UNDERLYING, never pooled.

        WHAT THIS USED TO DO. It accepted a `strategy_id`, ignored it, pooled
        every autopsy ever written across every strategy and every symbol, and
        returned one blended win rate with the ignored id attached as a label.
        `process_autopsy` passed "strat-autotrend-equities-v1", an id in
        neither portfolio, and the result was fed to an LLM that wrote the
        commander a confident journal entry about it.

        Measured on the live file, 2026-10-12, 122 autopsies:

            pooled        28.7%
            CRUDEOIL      10.6%   (47 autopsies)
            SILVERM       52.9%   (17)
            GOLDM         43.5%   (23)

        A fivefold spread flattened into one number, and the pooled figure was
        dominated by CRUDEOIL — an asset PARKED weeks ago for having no
        measurable edge. So the "insight" was mostly the failure of something
        already retired, burying the fact that the metals are the one
        confirmed edge in the system. That is the same mistake the arena
        already learned once: when strategies trade different markets, a
        pooled figure measures the market, not the strategy.

        `symbol` is the full option contract (CRUDEOIL26JUL7750CE), so
        grouping on it raw yields sixty cells of n=1. Group on the underlying.

        MISSING IS NOT A VALUE. The old code read `vix_at_entry` with a
        default of 15, so an absent measurement became a plausible number
        indistinguishable from a real one. Missing fields are counted and
        excluded here — max_adverse_excursion_pct is absent in 35 of 122
        records, which is worth knowing rather than papering over.
        """
        if not self._autopsies_file.exists():
            return {}

        try:
            from shared.instrument import underlying_of

            cutoff = datetime.now(timezone.utc) - timedelta(
                days=window_days if window_days is not None else self.PATTERN_WINDOW_DAYS
            )

            autopsies: list[dict[str, Any]] = []
            skipped_undated = 0
            with self._autopsies_file.open("r", encoding="utf-8") as fh:
                for line in fh:
                    if not line.strip():
                        continue
                    rec = json.loads(line.strip())
                    stamp = rec.get("timestamp")
                    if not stamp:
                        skipped_undated += 1
                        continue
                    try:
                        when = datetime.fromisoformat(str(stamp))
                        if when.tzinfo is None:
                            when = when.replace(tzinfo=timezone.utc)
                    except ValueError:
                        skipped_undated += 1
                        continue
                    if when >= cutoff:
                        autopsies.append(rec)

            by_asset: dict[str, list[dict[str, Any]]] = {}
            for rec in autopsies:
                by_asset.setdefault(underlying_of(rec.get("symbol", "")), []).append(rec)

            assets: dict[str, Any] = {}
            for asset, rows in sorted(by_asset.items()):
                cell: dict[str, Any] = {"n": len(rows)}

                if len(rows) < self.MIN_AUTOPSIES_PER_ASSET:
                    # Counted, but no rate. Absence announces itself.
                    cell.update({
                        "win_rate": None,
                        "stop_tightness_issue": None,
                        "insufficient": True,
                        "needs": self.MIN_AUTOPSIES_PER_ASSET,
                    })
                    assets[asset] = cell
                    continue

                wins = [r for r in rows if (r.get("pnl") or 0) > 0]
                losses = [r for r in rows if (r.get("pnl") or 0) <= 0]
                cell["wins"] = len(wins)
                cell["win_rate"] = round(len(wins) / len(rows), 4)
                cell["insufficient"] = False

                def _mean(records, field):
                    vals = [r[field] for r in records
                            if isinstance(r.get(field), (int, float))]
                    return (round(sum(vals) / len(vals), 4) if vals else None), len(records) - len(vals)

                cell["avg_win_vix"], cell["avg_win_vix_missing"] = _mean(wins, "vix_at_entry")
                cell["avg_loss_vix"], cell["avg_loss_vix_missing"] = _mean(losses, "vix_at_entry")

                # Stops cutting winners short: a loss that had been meaningfully
                # in profit first. Reported per asset, because one percentage
                # threshold cannot mean the same thing on NIFTY and NATURALGAS.
                measurable = [r for r in losses
                              if isinstance(r.get("max_favorable_excursion_pct"), (int, float))]
                premature = [r for r in measurable
                             if r["max_favorable_excursion_pct"] > 1.0]
                cell["premature_stops"] = len(premature)
                cell["losses_with_excursion"] = len(measurable)
                cell["losses_missing_excursion"] = len(losses) - len(measurable)
                cell["stop_tightness_issue"] = (
                    len(premature) > len(measurable) * 0.5 if measurable else None
                )
                assets[asset] = cell

            return {
                "window_days": window_days if window_days is not None else self.PATTERN_WINDOW_DAYS,
                "autopsies_in_window": len(autopsies),
                "skipped_undated": skipped_undated,
                "min_per_asset": self.MIN_AUTOPSIES_PER_ASSET,
                "assets": assets,
            }
        except Exception as e:
            logger.error(f"Failed to detect patterns: {e}")
            return {}

    def apply_autonomous_evolution(self, patterns: dict[str, Any]) -> None:
        """REMOVED 2026-08-26. It was a loaded gun, not a dead branch.

        This method used to widen a strategy's stop (up to 2.0 ATR) and raise
        its risk multiplier (up to 1.5x) on its own, and it never fired only
        because `process_autopsy` handed it a strategy id that exists in neither
        portfolio. That made it look harmless. It was not: the day anyone
        "fixed" that id — a one-line change, and an obvious one — Hokage would
        have started AUTONOMOUSLY WIDENING STOPS AND INCREASING SIZE.

        On what evidence? `detect_patterns` ignores its strategy_id argument and
        pools every autopsy across every strategy and symbol, and the trigger
        fires every five trades. So a blended win rate over five trades spanning
        four modules and six assets could have raised risk on one of them.

        That is Tier 3 in the evolution policy — "anything that widens a stop,
        raises a cap, or increases size" — the one tier that is never autonomous
        at any confidence. It is also the exact opposite of the commander's
        standing rule that capital must not be exposed to great risks.

        It wrote to `risk_management.stop_loss_atr_multiplier` and
        `risk_multiplier`, which production has never read — it reads
        `_THESIS_ATR_MULT_BY_STRATEGY_ASSET`. So the knob was not connected to
        the machine either. Three separate faults, and the only reason none of
        them cost money is a typo.

        The real loop now lives in `tools/research/sweep_lab.py`: it measures
        every candidate on two disjoint periods with the production stop
        applied, and writes PENDING proposals the commander rules on. It cannot
        widen a stop or raise size at all — those knobs are declared tier "ask"
        and are printed, never written.
        """
        logger.warning(
            "apply_autonomous_evolution is retired — autonomous stop-widening "
            "and size increases are Tier 3 and never automatic. Parameter "
            "changes come from tools/research/sweep_lab.py as PENDING proposals."
        )

    #: Trades and win rate a PROBATION strategy needs before promotion is even
    #: PROPOSED. Deliberately unchanged from when promotion was automatic — the
    #: bar was never the problem, acting on it alone was.
    PROMOTION_MIN_TRADES = 10
    PROMOTION_MIN_WIN_RATE = 55.0

    def evaluate_promotions(self) -> None:
        """PROPOSE promotion of probation strategies. Never perform one.

        THIS USED TO PROMOTE BY ITSELF. A PROBATION strategy with
        trade_count >= 10 and win_rate >= 55% was flipped to ACTIVE, written to
        disk and announced as "Automatically promoted to ACTIVE/LIVE mode",
        with no commander in the loop. It is reached from `process_autopsy`,
        which runs it every five trades.

        Promotion RAISES RISK. An ACTIVE strategy takes real entries and
        competes for a chest; a PROBATION one does not. The evolution policy
        has exactly one rule about that — reducing risk may act alone, raising
        risk always asks — and it is the same line the commander's standing
        instruction draws around his capital. Retirement stayed autonomous
        because an archived strategy cannot open anything. This is the mirror
        case and it was on the wrong side of the line.

        THE EVIDENCE WAS ALSO WRONG. `win_rate["DEFAULT"]` is pooled across
        every asset a strategy trades, and win rate does not track
        profitability. Measured in this very portfolio on 2026-10-12:

            strat-trendrider-mcx-v1   win_rate 60.0%   realized -17,502
            strat-macrobreakout-...   win_rate 100.0%  trade_count 1

        TrendRider would have cleared a 55% bar while having lost seventeen
        thousand rupees. Ten pooled trades is also far below the MIN_N the
        weekly audit requires, and carries no hold-out split, no production
        stop and no t-statistic — the three things that make a number mean
        anything here.

        So: still measured, still reported, still at the same bar. Written as
        a PENDING_APPROVAL proposal that only `apply_improvement_proposal` can
        act on, and that requires an explicit commander name.
        """
        strategies = self.portfolio_manager.portfolio.get("strategies", {})

        existing = self.load_proposals()
        existing_keys = {
            (p["strategy_id"], p["asset"], p["action"]): p["proposal_id"]
            for p in existing if _proposals.is_pending(p.get("status"))
        }
        new_proposals: list[dict[str, Any]] = []

        for s_id, strat in strategies.items():
            if strat.get("status") != "PROBATION":
                continue

            wr = (strat.get("win_rate") or {}).get("DEFAULT", 0)
            tc = (strat.get("trade_count") or {}).get("DEFAULT", 0)
            if tc < self.PROMOTION_MIN_TRADES or wr < self.PROMOTION_MIN_WIN_RATE:
                continue

            self._create_proposal_record(
                strat_id=s_id,
                strat_name=strat.get("name", s_id),
                asset="DEFAULT",
                action="promote_to_active",
                prev_values={"status": "PROBATION"},
                new_values={"status": "ACTIVE"},
                rationale=(
                    f"{tc} paper/shadow trades at a {wr}% win rate, clearing the "
                    f"{self.PROMOTION_MIN_TRADES}-trade / "
                    f"{self.PROMOTION_MIN_WIN_RATE}% bar. NOTE: this win rate is "
                    f"pooled across every asset and win rate does not track "
                    f"profitability — TrendRider showed 60% while losing 17,502. "
                    f"Confirm against the weekly audit's hold-out edge before "
                    f"approving."
                ),
                expected_imp="Strategy begins taking real entries and competing for a chest.",
                proposals=new_proposals,
                existing_keys=existing_keys,
            )

        if not new_proposals:
            return

        self._save_proposals_atomic(existing + new_proposals)
        logger.info(
            "Proposed %d promotion(s) for commander approval; none applied.",
            len(new_proposals),
        )

        try:
            from integrations.notifications.telegram_bot import TelegramBotUplink

            tb = TelegramBotUplink()
            if tb.enabled:
                lines = "\n".join(
                    f"- {p['strategy_name']} ({p['strategy_id']})"
                    for p in new_proposals
                )
                tb.send_message(
                    "PROMOTION PROPOSED - not applied\n\n" + lines +
                    "\n\nPromotion raises risk, so it is never automatic. "
                    "The win rate behind it is pooled across assets and does "
                    "not track profitability. Check the weekly audit's "
                    "hold-out edge, then approve from the dashboard."
                )
        except Exception as e:
            logger.error(f"Error sending promotion proposal alert: {e}")
