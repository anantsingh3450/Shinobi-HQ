import re

filepath = r"c:\Users\anant\OneDrive\Documents\AI PROJECT\AI COMMAND CENTRE\Hokage\src\bots\autonomous\autonomous_bot.py"

with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

# 1. Inject import and MARKET_SCAN_STARTED at the beginning of _scan_and_enter_opportunities
start_target = '''    def _scan_and_enter_opportunities(self) -> None:
        """Scan watchlist/market universe for opportunities, rank, size and place entry orders."""
        # Load active profile settings from SSOT'''

start_replacement = '''    def _scan_and_enter_opportunities(self) -> None:
        """Scan watchlist/market universe for opportunities, rank, size and place entry orders."""
        from hokage.dashboard.event_bus import EventBus
        bus = EventBus()
        bus.publish("MARKET_SCAN_STARTED", {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "scan_mode": getattr(self, "scan_mode", "WATCHLIST_RESTRICTED"),
            "scan_constraints": [u.upper() for u in (self.cache.read_intelligence("market_regime.json") or {}).get("active_universe", [])]
        })
        # Load active profile settings from SSOT'''

if start_target in content:
    content = content.replace(start_target, start_replacement)
    print("Injected MARKET_SCAN_STARTED")
else:
    print("WARNING: start_target not found!")

# 2. Inject global blocker handling (OPPORTUNITY_REJECTED, MARKET_SCAN_COMPLETED, NO_TRADE_DAY)
blocker_target = '''        if global_blocker:
            for s in scanned_symbols:
                if s in existing_symbols:
                    eval_results[s] = {"state": "EXECUTED", "blockers": [], "confirmations": [], "conviction": 85, "risk": 0.0}
                else:
                    eval_results[s] = {
                        "state": "NO_TRADE",
                        "blockers": [global_blocker],
                        "confirmations": [],
                        "conviction": 0,
                        "risk": 0.0,
                        "reasons": [global_blocker]
                    }
            self._update_all_states(eval_results)
            return'''

blocker_replacement = '''        if global_blocker:
            for s in scanned_symbols:
                if s in existing_symbols:
                    eval_results[s] = {"state": "EXECUTED", "blockers": [], "confirmations": [], "conviction": 85, "risk": 0.0}
                else:
                    eval_results[s] = {
                        "state": "NO_TRADE",
                        "blockers": [global_blocker],
                        "confirmations": [],
                        "conviction": 0,
                        "risk": 0.0,
                        "reasons": [global_blocker]
                    }
                bus.publish("OPPORTUNITY_REJECTED", {
                    "symbol": s,
                    "reason": global_blocker,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })
            bus.publish("MARKET_SCAN_COMPLETED", {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "scanned_count": len(scanned_symbols),
                "candidates_count": 0
            })
            bus.publish("NO_TRADE_DAY", {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "reason_summary": global_blocker,
                "risk_score": 5.0,
                "rejected_opportunities_count": len(scanned_symbols),
                "expected_edge": 0.0,
                "capital_preservation_score": 100.0
            })
            self._update_all_states(eval_results)
            return'''

if blocker_target in content:
    content = content.replace(blocker_target, blocker_replacement)
    print("Injected global blocker events")
else:
    print("WARNING: blocker_target not found!")

# 3. Inject OPPORTUNITY_FOUND / OPPORTUNITY_REJECTED in ThreadPoolExecutor candidate loop
# Let's map futures to symbols.
futures_target = '''        candidates = []
        if symbols_to_scan:
            with ThreadPoolExecutor(max_workers=min(10, len(symbols_to_scan))) as executor:
                futures = [executor.submit(self._evaluate_single_symbol, s) for s in symbols_to_scan]
                for fut in futures:
                    res = fut.result()
                    if res is not None:'''

futures_replacement = '''        candidates = []
        if symbols_to_scan:
            with ThreadPoolExecutor(max_workers=min(10, len(symbols_to_scan))) as executor:
                futures = {executor.submit(self._evaluate_single_symbol, s): s for s in symbols_to_scan}
                for fut in futures:
                    symbol = futures[fut]
                    res = fut.result()
                    if res is not None:
                        proposal = res["proposal"]
                        bus.publish("OPPORTUNITY_FOUND", {
                            "symbol": symbol,
                            "proposal_name": proposal.name,
                            "confidence_score": proposal.confidence_score,
                            "timestamp": datetime.now(timezone.utc).isoformat()
                        })'''

if futures_target in content:
    content = content.replace(futures_target, futures_replacement)
    print("Injected OPPORTUNITY_FOUND in thread pool")
else:
    print("WARNING: futures_target not found!")

# Since we changed futures to a dict, we need to handle the case where res is None (rejections).
# Wait, the original code had:
# for fut in futures:
#     res = fut.result()
#     if res is not None:
#         ...
# We want to add an `else:` branch to that `if res is not None:` block.
# Let's find the end of that `if res is not None:` block.
# The block ends with `candidates.append(res)`.
# Let's replace the end of that block.
block_end_target = '''                        res.update({
                            "entry_price": entry_price,
                            "valid_price": valid_price,
                            "conviction_score": res_conv["score"],
                            "decision_id": res_conv.get("decision_id", ""),
                            "conviction_breakdown": res_conv.get("conviction_breakdown", {}),
                            "flow_val": flow_val,
                            "vix_impact_delta": vix_impact_delta,
                            "symbol_sec": symbol_sec,
                            "rotation_dir": rotation.get("capital_rotation_direction", "N/A"),
                            "primary_analog": primary_analog,
                        })
                        candidates.append(res)'''

block_end_replacement = '''                        res.update({
                            "entry_price": entry_price,
                            "valid_price": valid_price,
                            "conviction_score": res_conv["score"],
                            "decision_id": res_conv.get("decision_id", ""),
                            "conviction_breakdown": res_conv.get("conviction_breakdown", {}),
                            "flow_val": flow_val,
                            "vix_impact_delta": vix_impact_delta,
                            "symbol_sec": symbol_sec,
                            "rotation_dir": rotation.get("capital_rotation_direction", "N/A"),
                            "primary_analog": primary_analog,
                        })
                        candidates.append(res)
                    else:
                        bus.publish("OPPORTUNITY_REJECTED", {
                            "symbol": symbol,
                            "reason": "Failed research/strategy/backtest validation.",
                            "timestamp": datetime.now(timezone.utc).isoformat()
                        })'''

if block_end_target in content:
    content = content.replace(block_end_target, block_end_replacement)
    print("Injected OPPORTUNITY_REJECTED in thread pool")
else:
    print("WARNING: block_end_target not found!")

# 4. Inject OPPORTUNITY_REJECTED for filter engines
# Filter 1: SessionBehaviorEngine
session_reject_target = '''            is_session_allowed, session_reason = self.session_behavior_engine.filter_opportunity(session, proposal.entry_rule)
            if not is_session_allowed:
                logger.info(f"Opportunity for {symbol} rejected by SessionBehaviorEngine: {session_reason}")
                eval_results[symbol] = {
                    "state": "NO_TRADE",
                    "blockers": [f"SessionBehaviorEngine: {session_reason}"],
                    "confirmations": [],
                    "conviction": 0,
                    "risk": round(backtest_result.profit_factor, 2),
                    "reasons": [f"SessionBehaviorEngine: {session_reason}"],
                    "proposal_name": proposal.name,
                    "breakdown": {}
                }
                continue'''

session_reject_replacement = '''            is_session_allowed, session_reason = self.session_behavior_engine.filter_opportunity(session, proposal.entry_rule)
            if not is_session_allowed:
                logger.info(f"Opportunity for {symbol} rejected by SessionBehaviorEngine: {session_reason}")
                eval_results[symbol] = {
                    "state": "NO_TRADE",
                    "blockers": [f"SessionBehaviorEngine: {session_reason}"],
                    "confirmations": [],
                    "conviction": 0,
                    "risk": round(backtest_result.profit_factor, 2),
                    "reasons": [f"SessionBehaviorEngine: {session_reason}"],
                    "proposal_name": proposal.name,
                    "breakdown": {}
                }
                bus.publish("OPPORTUNITY_REJECTED", {
                    "symbol": symbol,
                    "reason": f"SessionBehaviorEngine: {session_reason}",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })
                continue'''

if session_reject_target in content:
    content = content.replace(session_reject_target, session_reject_replacement)
    print("Injected SessionBehaviorEngine OPPORTUNITY_REJECTED")
else:
    print("WARNING: session_reject_target not found!")

# Filter 2: VolumeEngine
volume_reject_target = '''            is_vol_valid, vol_reason = self.volume_engine.validate_breakout(current_vol, avg_vol)
            if not is_vol_valid:
                logger.info(f"Opportunity for {symbol} rejected by VolumeEngine: {vol_reason}")
                eval_results[symbol] = {
                    "state": "NO_TRADE",
                    "blockers": [f"VolumeEngine: {vol_reason}"],
                    "confirmations": [],
                    "conviction": 0,
                    "risk": round(backtest_result.profit_factor, 2),
                    "reasons": [f"VolumeEngine: {vol_reason}"],
                    "proposal_name": proposal.name,
                    "breakdown": {}
                }
                continue'''

volume_reject_replacement = '''            is_vol_valid, vol_reason = self.volume_engine.validate_breakout(current_vol, avg_vol)
            if not is_vol_valid:
                logger.info(f"Opportunity for {symbol} rejected by VolumeEngine: {vol_reason}")
                eval_results[symbol] = {
                    "state": "NO_TRADE",
                    "blockers": [f"VolumeEngine: {vol_reason}"],
                    "confirmations": [],
                    "conviction": 0,
                    "risk": round(backtest_result.profit_factor, 2),
                    "reasons": [f"VolumeEngine: {vol_reason}"],
                    "proposal_name": proposal.name,
                    "breakdown": {}
                }
                bus.publish("OPPORTUNITY_REJECTED", {
                    "symbol": symbol,
                    "reason": f"VolumeEngine: {vol_reason}",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })
                continue'''

if volume_reject_target in content:
    content = content.replace(volume_reject_target, volume_reject_replacement)
    print("Injected VolumeEngine OPPORTUNITY_REJECTED")
else:
    print("WARNING: volume_reject_target not found!")

# Filter 3: LiquidityEngine
liq_reject_target = '''            is_liq_valid, liq_reason = self.liquidity_engine.check_liquidity(spread_pct, bid_ask_ratio)
            if not is_liq_valid:
                logger.info(f"Opportunity for {symbol} rejected by LiquidityEngine: {liq_reason}")
                eval_results[symbol] = {
                    "state": "NO_TRADE",
                    "blockers": [f"LiquidityEngine: {liq_reason}"],
                    "confirmations": [],
                    "conviction": 0,
                    "risk": round(backtest_result.profit_factor, 2),
                    "reasons": [f"LiquidityEngine: {liq_reason}"],
                    "proposal_name": proposal.name,
                    "breakdown": {}
                }
                continue'''

liq_reject_replacement = '''            is_liq_valid, liq_reason = self.liquidity_engine.check_liquidity(spread_pct, bid_ask_ratio)
            if not is_liq_valid:
                logger.info(f"Opportunity for {symbol} rejected by LiquidityEngine: {liq_reason}")
                eval_results[symbol] = {
                    "state": "NO_TRADE",
                    "blockers": [f"LiquidityEngine: {liq_reason}"],
                    "confirmations": [],
                    "conviction": 0,
                    "risk": round(backtest_result.profit_factor, 2),
                    "reasons": [f"LiquidityEngine: {liq_reason}"],
                    "proposal_name": proposal.name,
                    "breakdown": {}
                }
                bus.publish("OPPORTUNITY_REJECTED", {
                    "symbol": symbol,
                    "reason": f"LiquidityEngine: {liq_reason}",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })
                continue'''

if liq_reject_target in content:
    content = content.replace(liq_reject_target, liq_reject_replacement)
    print("Injected LiquidityEngine OPPORTUNITY_REJECTED")
else:
    print("WARNING: liq_reject_target not found!")

# 5. Inject STRATEGY_STARTED and STRATEGY_COMPLETED
strat_target = '''            selection_res = self.strategy_portfolio.select_strategy(
                asset=symbol,
                market_regime=regime_str,
                volatility_regime=volatility_str
            )
            selected_strat = selection_res["strategy"]
            logger.info(selection_res["reason"])'''

strat_replacement = '''            bus.publish("STRATEGY_STARTED", {
                "symbol": symbol,
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
            selection_res = self.strategy_portfolio.select_strategy(
                asset=symbol,
                market_regime=regime_str,
                volatility_regime=volatility_str
            )
            selected_strat = selection_res["strategy"]
            logger.info(selection_res["reason"])
            bus.publish("STRATEGY_COMPLETED", {
                "symbol": symbol,
                "strategy_id": selected_strat.get("strategy_id"),
                "strategy_name": selected_strat.get("name"),
                "reason": selection_res["reason"],
                "timestamp": datetime.now(timezone.utc).isoformat()
            })'''

if strat_target in content:
    content = content.replace(strat_target, strat_replacement)
    print("Injected Strategy selection events")
else:
    print("WARNING: strat_target not found!")

# 6. Inject RISK_APPROVED, RISK_REJECTED
risk_target = '''            # Validate entry price & RiskBot early
            risk_approved = False
            risk_reason = "Risk verification pipeline failure."
            if valid_price:
                try:
                    account = self.orchestrator.portfolio_store.load_account(self.orchestrator.paper_venue._account_id)
                    risk_verdict = self.orchestrator.risk_bot.check_proposal(account, proposal, entry_price)
                    risk_approved = risk_verdict.is_approved
                    risk_reason = risk_verdict.reason if not risk_approved else "All risk parameters satisfied."
                except Exception as exc:
                    risk_reason = f"Risk check failed: {exc}"
            else:
                risk_reason = "Invalid entry price."'''

risk_replacement = '''            # Validate entry price & RiskBot early
            risk_approved = False
            risk_reason = "Risk verification pipeline failure."
            if valid_price:
                try:
                    account = self.orchestrator.portfolio_store.load_account(self.orchestrator.paper_venue._account_id)
                    risk_verdict = self.orchestrator.risk_bot.check_proposal(account, proposal, entry_price)
                    risk_approved = risk_verdict.is_approved
                    risk_reason = risk_verdict.reason if not risk_approved else "All risk parameters satisfied."
                    if risk_approved:
                        bus.publish("RISK_APPROVED", {
                            "symbol": symbol,
                            "reason": risk_reason,
                            "timestamp": datetime.now(timezone.utc).isoformat()
                        })
                    else:
                        bus.publish("RISK_REJECTED", {
                            "symbol": symbol,
                            "reason": risk_reason,
                            "timestamp": datetime.now(timezone.utc).isoformat()
                        })
                except Exception as exc:
                    risk_reason = f"Risk check failed: {exc}"
                    bus.publish("RISK_REJECTED", {
                        "symbol": symbol,
                        "reason": risk_reason,
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    })
            else:
                risk_reason = "Invalid entry price."
                bus.publish("RISK_REJECTED", {
                    "symbol": symbol,
                    "reason": risk_reason,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })'''

if risk_target in content:
    content = content.replace(risk_target, risk_replacement)
    print("Injected Risk events")
else:
    print("WARNING: risk_target not found!")

# 7. Inject COMMITTEE_VOTE and OPPORTUNITY_REJECTED (Committee level)
comm_target = '''            # Evaluate Proposal through Investment Committee
            committee_decision = self.committee.evaluate_proposal(proposal, backtest_result, ic_context)

            # Record in Immutable Committee Ledger
            self.committee_ledger.record_decision(decision_id, selected_strat["strategy_id"], symbol, committee_decision)'''

comm_replacement = '''            # Evaluate Proposal through Investment Committee
            committee_decision = self.committee.evaluate_proposal(proposal, backtest_result, ic_context)

            # Record in Immutable Committee Ledger
            self.committee_ledger.record_decision(decision_id, selected_strat["strategy_id"], symbol, committee_decision)
            
            # Fire COMMITTEE_VOTE
            votes_dict = {c: {"vote": v.vote.value, "reason": v.reasoning} for c, v in committee_decision.votes.items()}
            bus.publish("COMMITTEE_VOTE", {
                "symbol": symbol,
                "verdict": committee_decision.final_verdict,
                "confidence": committee_decision.decision_confidence,
                "votes": votes_dict,
                "timestamp": datetime.now(timezone.utc).isoformat()
            })'''

if comm_target in content:
    content = content.replace(comm_target, comm_replacement)
    print("Injected COMMITTEE_VOTE")
else:
    print("WARNING: comm_target not found!")

comm_reject_target = '''            if committee_decision.final_verdict == "REJECTED":
                # Compute allocation for statistics and EOD avoided-loss
                alloc_res = self.allocation_engine.evaluate_allocation(symbol, committee_decision.decision_confidence)'''

comm_reject_replacement = '''            if committee_decision.final_verdict == "REJECTED":
                # Compute allocation for statistics and EOD avoided-loss
                bus.publish("OPPORTUNITY_REJECTED", {
                    "symbol": symbol,
                    "reason": f"Rejected by Investment Committee. Rejecting members: {', '.join(committee_decision.rejecting_committees)}",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })
                alloc_res = self.allocation_engine.evaluate_allocation(symbol, committee_decision.decision_confidence)'''

if comm_reject_target in content:
    content = content.replace(comm_reject_target, comm_reject_replacement)
    print("Injected Committee OPPORTUNITY_REJECTED")
else:
    print("WARNING: comm_reject_target not found!")

# 8. Inject OPPORTUNITY_REJECTED for 0% allocation
alloc_zero_target = '''            if alloc_pct == 0.0:
                reasons_list = [
                    f"Allocation sized to 0% by Capital Preservation sizing engine or active constraints: {active_constraints}."
                ]'''

alloc_zero_replacement = '''            if alloc_pct == 0.0:
                reasons_list = [
                    f"Allocation sized to 0% by Capital Preservation sizing engine or active constraints: {active_constraints}."
                ]
                bus.publish("OPPORTUNITY_REJECTED", {
                    "symbol": symbol,
                    "reason": "Allocation sized to 0% by Capital Preservation sizing engine or active constraints.",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })'''

if alloc_zero_target in content:
    content = content.replace(alloc_zero_target, alloc_zero_replacement)
    print("Injected Allocation 0% OPPORTUNITY_REJECTED")
else:
    print("WARNING: alloc_zero_target not found!")

# 9. Inject EXECUTION_STARTED, EXECUTION_COMPLETED
exec_target = '''                logger.info(f"Placing autonomous entry order: {side} {qty} {symbol} on venue {venue.venue_id}")
                resolved_exch = self.orchestrator.session_manager.resolve_exchange(symbol)
                resolved_ac = self.orchestrator.session_manager.resolve_asset_class(symbol)
                inst = Instrument(symbol=symbol, asset_class=resolved_ac, exchange=resolved_exch)
                req = OrderRequest(
                    instrument=inst,
                    side=side,
                    quantity=qty,
                    order_type=OrderType.MARKET,
                    venue_id=venue.venue_id,
                    strategy_id=proposal.name,
                    execution_reason="Autonomous CIO Allocation Sized Entry"
                )
                resp = venue.place_order(req)'''

exec_replacement = '''                bus.publish("EXECUTION_STARTED", {
                    "symbol": symbol,
                    "side": side.value,
                    "quantity": qty,
                    "allocated_pct": alloc_pct,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })
                logger.info(f"Placing autonomous entry order: {side} {qty} {symbol} on venue {venue.venue_id}")
                resolved_exch = self.orchestrator.session_manager.resolve_exchange(symbol)
                resolved_ac = self.orchestrator.session_manager.resolve_asset_class(symbol)
                inst = Instrument(symbol=symbol, asset_class=resolved_ac, exchange=resolved_exch)
                req = OrderRequest(
                    instrument=inst,
                    side=side,
                    quantity=qty,
                    order_type=OrderType.MARKET,
                    venue_id=venue.venue_id,
                    strategy_id=proposal.name,
                    execution_reason="Autonomous CIO Allocation Sized Entry"
                )
                resp = venue.place_order(req)
                bus.publish("EXECUTION_COMPLETED", {
                    "symbol": symbol,
                    "side": side.value,
                    "quantity": qty,
                    "price": entry_price,
                    "status": "SUCCESS",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })'''

if exec_target in content:
    content = content.replace(exec_target, exec_replacement)
    print("Injected EXECUTION_STARTED and EXECUTION_COMPLETED (Success)")
else:
    print("WARNING: exec_target not found!")

exec_fail_target = '''            except Exception as exc:
                logger.error(f"Failed to enter autonomous opportunity for {symbol}: {exc}")'''

exec_fail_replacement = '''            except Exception as exc:
                logger.error(f"Failed to enter autonomous opportunity for {symbol}: {exc}")
                bus.publish("EXECUTION_COMPLETED", {
                    "symbol": symbol,
                    "status": "FAILED",
                    "error": str(exc),
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })'''

if exec_fail_target in content:
    content = content.replace(exec_fail_target, exec_fail_replacement)
    print("Injected EXECUTION_COMPLETED (Failure)")
else:
    print("WARNING: exec_fail_target not found!")

# 10. Inject MARKET_SCAN_COMPLETED, PORTFOLIO_UPDATED, NO_TRADE_DAY at the end of the method
end_target = '''        # Update all active universe surveillance states
        self._update_all_states(eval_results, scanned_symbols, existing_symbols)

        # Loop over candidate strategies in SHADOW_MODE or PROBATION to simulate decisions'''

end_replacement = '''        # Update all active universe surveillance states
        self._update_all_states(eval_results, scanned_symbols, existing_symbols)
        
        # Fire MARKET_SCAN_COMPLETED
        bus.publish("MARKET_SCAN_COMPLETED", {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "scanned_count": len(scanned_symbols),
            "candidates_count": len(candidates)
        })

        # Fire PORTFOLIO_UPDATED
        bus.publish("PORTFOLIO_UPDATED", {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "trades_taken_count": len(self._trades_taken_today),
            "portfolio_health": portfolio_health
        })

        # Fire NO_TRADE_DAY if no trades taken today
        if not self._trades_taken_today:
            reasons_summary = []
            for sym, res in eval_results.items():
                if res.get("state") in ("NO_TRADE", "WAITING") and "reasons" in res:
                    reasons_summary.extend(res["reasons"])
            bus.publish("NO_TRADE_DAY", {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "reason_summary": "; ".join(reasons_summary) or "No actionable opportunities found.",
                "risk_score": 1.5,
                "rejected_opportunities_count": len(eval_results),
                "expected_edge": 0.0,
                "capital_preservation_score": 100.0 if profile.risk.capital_preservation else 50.0
            })

        # Loop over candidate strategies in SHADOW_MODE or PROBATION to simulate decisions'''

if end_target in content:
    content = content.replace(end_target, end_replacement)
    print("Injected MARKET_SCAN_COMPLETED, PORTFOLIO_UPDATED, NO_TRADE_DAY")
else:
    print("WARNING: end_target not found!")

# 11. Inject LEARNING_STARTED, LEARNING_COMPLETED
learn_target = '''        # Evaluate pipeline transitions for all candidate strategies
        for strat_id, strat in list(self.strategy_portfolio.portfolio.get("strategies", {}).items()):'''

learn_replacement = '''        # Evaluate pipeline transitions for all candidate strategies
        bus.publish("LEARNING_STARTED", {
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        for strat_id, strat in list(self.strategy_portfolio.portfolio.get("strategies", {}).items()):'''

if learn_target in content:
    content = content.replace(learn_target, learn_replacement)
    print("Injected LEARNING_STARTED")
else:
    print("WARNING: learn_target not found!")

# The method ends at the end of that loop.
# Let's find the end of that loop.
# The loop ends with:
#                     self.strategy_portfolio.save()
# Let's append LEARNING_COMPLETED after that.
learn_end_target = '''                changed, transition_reason = self.strategy_evolution.evaluate_pipeline_transition(strat, active_prod)
                if changed:
                    logger.info(f"Strategy {strat_id} transitioned: {transition_reason}")
                    if strat["status"] == "PRODUCTION":
                        strat["status"] = "ACTIVE"
                    self.strategy_portfolio.save()'''

# Note: We need to make sure we only match this specific block at the end of the method.
learn_end_replacement = '''                changed, transition_reason = self.strategy_evolution.evaluate_pipeline_transition(strat, active_prod)
                if changed:
                    logger.info(f"Strategy {strat_id} transitioned: {transition_reason}")
                    if strat["status"] == "PRODUCTION":
                        strat["status"] = "ACTIVE"
                    self.strategy_portfolio.save()
        bus.publish("LEARNING_COMPLETED", {
            "timestamp": datetime.now(timezone.utc).isoformat()
        })'''

if learn_end_target in content:
    content = content.replace(learn_end_target, learn_end_replacement)
    print("Injected LEARNING_COMPLETED")
else:
    print("WARNING: learn_end_target not found!")

with open(filepath, "w", encoding="utf-8") as f:
    f.write(content)
print("Done!")
