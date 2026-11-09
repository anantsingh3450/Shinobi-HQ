"""Measure every entry module against every asset, weekly, and report what MOVED.

WHY THIS EXISTS
Hokage's ImprovementBot has written 430 trade autopsies and applied exactly
zero improvements — it is wired to a strategy id that exists in neither
portfolio, and writes to fields production does not read. The real measurement
machinery is the labs in this directory, and until now every one of them had to
be fired by hand. That made Claude the evolution loop, not Hokage.

This is the tool that removes the hand. It runs the same measurement
entry_module_lab performs, over the whole universe, writes a dated snapshot to
the brain, and DIFFS against the previous one.

WHAT IT REPORTS, AND WHY IT REPORTS DELTAS
A weekly dump of forty t-statistics is noise nobody reads. What matters is what
CHANGED: a module whose edge is decaying, or an archived one that has come back
to life. Those are the two events that should change the lineup, and both are
invisible in a snapshot taken alone.

  DEMOTION CANDIDATE  a LIVE module whose t is below the ship bar for TWO
                      consecutive weeks. One bad week is noise; two is a trend
                      worth acting on. Only ever removes risk.
  REVIVAL CANDIDATE   an ARCHIVED module whose t has climbed back above the
                      bar. Archiving is not meant to be permanent — regimes
                      change and a module can become right again.

Neither is applied automatically. Phase 1 REPORTS; Phase 2 is where anything
acts on it, and even then only demotion is autonomous.

CAVEAT THAT TRAVELS WITH EVERY NUMBER: these are in-sample over the measurement
window, they score the UNDERLYING rather than option P&L, and a t-stat computed
weekly on an overlapping window is correlated with last week's. Treat a single
week's move as weak evidence and the two-week rule as the real signal.

USAGE
    python tools/research/weekly_audit.py                 # measure + diff
    python tools/research/weekly_audit.py --telegram      # ...and alert
    python tools/research/weekly_audit.py --dry-run       # no snapshot written
"""
from __future__ import annotations

import json
import math
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from hokage.memory.resolver import brain_root

#: The active brain root. NOT `BRAIN` — that ignored
#: HOKAGE_BRAIN_ROOT, so moving the brain gave Hokage one brain and this tool
#: another, silently. See hokage.memory.resolver.brain_root.
BRAIN = brain_root()

from signal_lab import (  # noqa: E402
    MIN_BARS_PER_HALF, Ctx, halves, load_bars, _MCX_FUTURES,
)
from sweep_lab import realised  # noqa: E402
from entry_module_lab import build_context  # noqa: E402

from signal_lab import corrected_t  # noqa: E402
from bots.autonomous.autonomous_bot import AutonomousTradingBot as Bot  # noqa: E402
from bots.strategy.components.entries import ENTRY_MODULES  # noqa: E402
from bots.strategy.components.mcx_entries import MCX_ENTRY_MODULES  # noqa: E402

#: The horizon Hokage's trades actually live at. One number, deliberately:
#: reporting three horizons triples the noise without tripling the information.
HORIZON = 4

#: Below this a measured edge is indistinguishable from luck. Same bar every
#: other lab in this directory ships against.

#: Minimum signals before a t-statistic is quoted at all.
MIN_N = 30

#: How much history each run measures over. Long enough for a decent n, short
#: enough that a regime change shows up rather than being averaged away.
#:
#: Kept only for the snapshot header now — the windows themselves come from
#: signal_lab.halves(), which derives them from the tape Kite actually serves.
LOOKBACK_DAYS = 105

#: The production thesis stop, in ATR of the underlying. Every number this audit
#: writes is measured INSIDE it.
PROD_STOP_ATR = 1.25


UNIVERSE = ["NIFTY", "BANKNIFTY", "SENSEX", "CRUDEOIL", "NATURALGAS", "GOLDM", "SILVERM"]

#: THE BAR, CORRECTED FOR HOW MANY CELLS THIS AUDIT LOOKS AT.
#:
#: Raised 2026-10-14 on the commander's decision, from a flat 2.0.
#:
#: This audit scores every (module, asset) pair and reports the ones that
#: clear. Picking the best of N and judging it as though it were the only test
#: is the oldest mistake in measurement, and hypothesis_lab had just measured
#: its size on Hokage's own tape: of 116,360 generated candidates, 2,808
#: cleared t>=2.0 on BOTH halves and NONE cleared the corrected bar. The
#: audit's family is far smaller and its cells are pre-specified rather than
#: machine-generated, which is a genuinely weaker version of the problem - but
#: it is the same problem, and a flat 2.0 was never the right answer to it.
#:
#: DERIVED, NOT TYPED. The commander asked for 3.11, which is the corrected
#: bar for the 27 cells measured that day. Hardcoding 3.11 would silently
#: become wrong the moment a module or an asset is added or retired, and this
#: audit's whole purpose is to stop numbers drifting from what they describe.
#: So the family size is computed from the lineup and the bar follows it.
#:
#: Consequence, stated plainly: both cells confirmed under the old bar -
#: SessionShift/GOLDM t+2.19 and MeanReversion/SENSEX t+2.15 - fall below this
#: one. That is the point of raising it.
def _family_size() -> int:
    """How many (module, asset) cells this audit tests."""
    return sum(
        len(MCX_ENTRY_MODULES if symbol in _MCX_FUTURES else ENTRY_MODULES)
        for symbol in UNIVERSE
    )


FAMILY_SIZE = _family_size()
SHIP_BAR = round(corrected_t(FAMILY_SIZE), 2)

#: How this audit measures. Written into every snapshot, and compared by
#: evolution.plan() before two snapshots may be treated as consecutive evidence.
#:
#: WHY A VERSION STRING AND NOT JUST A BETTER MEASUREMENT. Until 2026-08-28 this
#: audit scored a 105-day POOLED window on RAW forward edge with NO stop and NO
#: train/hold split — and the evolution policy retired strategies by comparing
#: one week's number against the last. That is a lower evidence bar than any
#: change is allowed to SHIP against, applied to a decision that removes a
#: strategy's capital.
#:
#: It is also the exact geometry that has misled twice in one week: crude's
#: +2.06 became +0.82 once the stop was included, and gas's +2.67 became +1.08
#: once the contract roll shortened the window. A retirement decision resting on
#: that basis is a coin flip wearing a t-statistic.
#:
#: Changing the basis makes old snapshots incomparable. A silent change would
#: have been worse than the original fault: the policy would have read last
#: week's no-stop pooled t against this week's hold-out-with-stop t and called
#: the difference a decline in edge. So the basis is STAMPED, and a change to it
#: RESETS the consecutive-week evidence rather than continuing it.
#: Bumped 2026-10-12: entries on bars that never traded are now excluded
#: (signal_lab.measurable). Zero-volume bars are 13.5% of GOLDM, 13.0% of
#: CRUDEOIL and 12.2% of NATURALGAS, and a flat run of them yields a tiny
#: ATR that turns the gap to the next real trade into a huge edge_atr --
#: one bucket read +7.545 with t=+2.22 off four such bars.
#:
#: This is a BASIS CHANGE, so evolution._same_geometry will refuse to
#: compare these snapshots with the older ones and the retirement clock
#: RESTARTS. That is the intended consequence: there is no trend across a
#: change of instrument, and the two pending MacroBreakout proposals were
#: built on the contaminated basis.
#: Bumped 2026-10-14: the TARGET is now applied, and the stop is resolved PER
#: CELL instead of assumed to be 1.25.
#:
#: This audit applied the production stop and then exited at the horizon. That
#: scores a system nobody runs: production also exits at a target, and a target
#: truncates exactly the winners a horizon exit counts in full. It also
#: hardcoded 1.25 ATR while SessionShift/GOLDM has run 3.0 since 2026-08-13.
#:
#: Both omissions flatter, and not cosmetically. Re-measured across every live
#: cell:
#:
#:   SessionShift / SILVERM   stop only +0.283 t+3.15   full +0.096 t+1.54
#:   TrendRider   / CRUDEOIL  stop only +0.109 t+2.30   full +0.079 t+1.93
#:   SessionShift / CRUDEOIL  stop only +0.153 t+2.21   full +0.113 t+2.12
#:
#: SILVERM was the ONE cell this audit called confirmed, and it does not
#: survive. The bot's own stop table had carried a comment since 2026-08-13
#: saying it was "+0.007 under full geometry, indistinguishable from zero at
#: ANY stop width" — the audit disagreed only because of what it left out. So
#: every promotion and retirement decision in Hokage's history rested on a
#: basis that overstated edge.
#:
#: BASIS CHANGE, so the retirement clock RESETS again. That is the intended
#: consequence and it is the cheaper error: continuing a clock across a change
#: of instrument compares two different measurements and calls the difference
#: a decline in edge.
#: The BAR is part of the stamp. "below the bar two audits running" compares
#: two verdicts, so a change of bar changes what the trend means - exactly
#: like a change of measurement. Folding it in here makes a bar change reset
#: the retirement clock through the one mechanism that already does that,
#: instead of a second rule that could disagree with the first.
#: The basis half now lives in src, so the code that READS a proposal can
#: tell whether it was measured this way without importing a research tool.
#: The string is unchanged byte for byte - a different value here would reset
#: the retirement clock, and that must only ever happen for a real change of
#: measurement.
from hokage.research.proposals import MEASUREMENT_BASIS  # noqa: E402

GEOMETRY = f"{MEASUREMENT_BASIS}+bar{SHIP_BAR:.2f}"

SNAPSHOT_DIR = BRAIN / "research" / "snapshots"
PORTFOLIO_DIR = BRAIN / "portfolio"


# ------------------------------------------------------------------ measuring
def _stats(edges: list[float], hits: int) -> dict[str, float] | None:
    n = len(edges)
    if n < MIN_N:
        return None
    mean = sum(edges) / n
    var = sum((e - mean) ** 2 for e in edges) / (n - 1)
    t = mean / (math.sqrt(var / n) or 1e-9)
    return {"n": n, "accuracy": hits / n * 100.0, "edge_atr": mean, "t": t}


def accumulate(symbol: str, bars: list[dict], modules: dict) -> dict[str, dict]:
    """Raw forward edges per module on this asset, before any statistics.

    Split out from measure() so the same signals can be POOLED across a
    league's assets. A module that fires ~9 times a quarter on one index —
    MacroBreakout does — can never reach significance per asset, but the
    question "does this module have edge" is answerable across the three it
    trades. See the pooled section of the report, and its caveat.
    """
    acc = {name: {"edges": [], "hits": 0} for name in modules}
    for i in range(42, len(bars) - HORIZON):
        window = bars[: i + 1]
        day = window[-1]["date"].date()
        session = [b for b in window if b["date"].date() == day]
        if len(session) < 6 or bars[i + HORIZON]["date"].date() != day:
            continue
        ctx = Ctx(window, session)
        if not ctx.atr:
            continue
        mkt = build_context(symbol, window, ctx, session)
        for name, module in modules.items():
            try:
                sig = module.evaluate(mkt)
            except Exception:
                continue
            if not getattr(sig, "should_enter", False):
                continue
            call = 1 if sig.direction == "long" else -1
            # WITH THE PRODUCTION STOP, not raw forward edge. A module is judged
            # on the geometry it actually trades inside; measuring it without
            # the stop scores a system that does not exist, which is how a
            # 240-minute crude horizon read +2.06 and delivered +0.82.
            edge = realised(bars, i, call, ctx.atr, name, symbol)
            acc[name]["edges"].append(edge)
            if edge > 0:
                acc[name]["hits"] += 1
    return acc


def _summarise(acc: dict[str, dict]) -> dict[str, dict]:
    out = {}
    for name, rec in acc.items():
        stat = _stats(rec["edges"], rec["hits"])
        if stat:
            out[name] = stat
    return out


def measure(symbol: str, bars: list[dict], modules: dict) -> dict[str, dict]:
    """Every module's edge on this asset. Mirrors entry_module_lab exactly."""
    return _summarise(accumulate(symbol, bars, modules))


def measure_split(symbol: str, modules: dict) -> tuple[dict, dict, tuple]:
    """(per-module stats, raw halves for pooling, (train_window, hold_window)).

    Two disjoint periods derived from the tape Kite actually serves, train
    older. The reported `t` and `edge_atr` are the HOLD-OUT's — the half the
    module was not selected on, and the fresher tape — with the train figures
    carried alongside so a retirement can be read against both.

    Returns {} for the asset when either half is too thin to judge. A verdict
    built on 3 signals is what a contract roll looks like, not what a decline
    looks like: on 2026-08-27 the stale fixed window measured six days of gas
    and reported n=3, t=+2.00 without erroring.
    """
    train_win, hold_win = halves(symbol)
    bars = {"train": load_bars(symbol, *train_win),
            "hold": load_bars(symbol, *hold_win)}

    thin = {k: len(v) for k, v in bars.items() if len(v) < MIN_BARS_PER_HALF}
    if thin:
        detail = ", ".join(f"{k} has {n} bars" for k, n in thin.items())
        raise ValueError(f"not enough tape to judge ({detail}); contract may have rolled")

    raw = {half: accumulate(symbol, rows, modules) for half, rows in bars.items()}
    stats = {half: _summarise(rec) for half, rec in raw.items()}

    out: dict[str, dict] = {}
    for name in modules:
        hold = stats["hold"].get(name)
        train = stats["train"].get(name)
        if not hold:
            continue
        out[name] = {
            # `t` and `edge_atr` stay the primary keys every reader already
            # uses; they now mean the HOLD-OUT, measured with the stop.
            "n": hold["n"], "accuracy": hold["accuracy"],
            "edge_atr": hold["edge_atr"], "t": hold["t"],
            # None, NOT 0.0, when the train half fell below MIN_N and was never
            # summarised. RangeFade/NATURALGAS printed "TRn 0, tr_edge +0.000,
            # tr_t +0.00" in the 2026-08-28 snapshot and read as "fired nothing
            # and measured flat"; it had in fact fired 16 times, below the
            # reporting floor of 30. Missing is not zero — the same rule that
            # governs a missing ATR and a missing excursion.
            "n_train": (train or {}).get("n"),
            "edge_train": (train or {}).get("edge_atr"),
            "t_train": (train or {}).get("t"),
            "train_below_min_n": train is None,
            "confirmed": bool(train and train["t"] >= SHIP_BAR and hold["t"] >= SHIP_BAR),
        }
    return out, raw, (train_win, hold_win)


#: Which assets are pooled together. A league's assets move together, which is
#: exactly why pooling needs the caveat printed beside it.
LEAGUES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Index Dojo", ("NIFTY", "BANKNIFTY", "SENSEX")),
    ("MCX Arena", ("CRUDEOIL", "NATURALGAS", "GOLDM", "SILVERM")),
)


#: Printed WITH the pooled table, never as a footnote. A number whose
#: limitation lives somewhere else gets quoted without it.
POOLED_CAVEAT = (
    "A league's assets move together, so pooled signals are correlated and the "
    "effective sample is well below the printed n. Treat the pooled t as an "
    "UPPER BOUND: good for ranking modules and spotting one worth watching, "
    "never enough on its own to move capital. Tier 1 reads it as a VETO only: "
    "it can BLOCK a retirement the per-cell rule cleared, and can never clear "
    "one by itself."
)


def pool(per_asset: dict[str, dict[str, dict]]) -> dict[str, dict[str, dict]]:
    """league -> module -> stat, pooling each module's signals across assets.

    WHY THIS EXISTS (2026-08-18): every one of the six live index pairs measured
    WEAK or NEGATIVE per asset, and MacroBreakout could not be judged at all —
    it fires about nine times a quarter on NIFTY, so no single asset ever
    reaches n. Pooled across the three it trades, it measured t=+2.79 on the
    recent half against t=-0.83 on the older one, with two consecutive positive
    quarters (+1.97 then +2.27). That is the only signal in the index league
    that does not look like noise, and it is invisible per asset.

    READ THE t WITH A DISCOUNT. NIFTY, BANKNIFTY and SENSEX move together, so
    pooled signals are heavily correlated and the effective sample is far below
    the printed n. The pooled t is therefore an UPPER BOUND on significance,
    useful for ranking modules against each other and for spotting a module
    worth watching — never sufficient on its own to move capital.
    """
    out: dict[str, dict[str, dict]] = {}
    for league, assets in LEAGUES:
        merged: dict[str, dict] = {}
        for asset in assets:
            for name, rec in (per_asset.get(asset) or {}).items():
                cell = merged.setdefault(name, {"edges": [], "hits": 0})
                cell["edges"] += rec["edges"]
                cell["hits"] += rec["hits"]
        stats = _summarise(merged)
        if stats:
            out[league] = stats
    return out


# ------------------------------------------------------------------ portfolio
def live_lineup() -> dict[str, dict]:
    """module_id -> {status, scope, strategy_id, name} from the real brain."""
    from bots.strategy.components.entries import ENTRY_MODULES as _E
    from bots.strategy.components.mcx_entries import MCX_ENTRY_MODULES as _M

    module_id_of = {}
    for key, module in {**_E, **_M}.items():
        module_id_of[key] = getattr(module, "module_id", key)

    lineup: dict[str, dict] = {}
    for name in ("strategy_portfolio.json", "mcx_strategy_portfolio.json"):
        path = PORTFOLIO_DIR / name
        if not path.exists():
            continue
        book = json.loads(path.read_text(encoding="utf-8-sig"))
        for sid, strat in (book.get("strategies") or {}).items():
            mid = module_id_of.get(sid)
            if not mid:
                continue
            capital = strat.get("capital") or {}
            try:
                chest = float(capital.get("starting", 0.0)) + float(capital.get("realized_pnl", 0.0))
            except (TypeError, ValueError):
                chest = 0.0
            lineup[mid] = {
                "strategy_id": sid,
                "name": strat.get("name", sid),
                "status": strat.get("status", "UNKNOWN"),
                "scope": [a.upper() for a in (strat.get("supported_assets") or [])],
                "chest": chest,
            }
    return lineup


def coverage_gaps(lineup: dict[str, dict]) -> list[str]:
    """Assets in UNIVERSE that no live, solvent strategy is scoped to.

    The boot audit (autonomous_bot.audit_asset_coverage) catches this when
    Hokage starts. This is the same question asked weekly, because a lineup
    change made mid-week — an archive, a re-scope, a chest transfer — can
    orphan an asset while the process keeps running and nothing reboots.

    An empty scope FAILS OPEN, matching `_strategy_supports`: a missing list
    means "no restriction recorded", not "trades nothing".
    """
    # A PARKED asset is a decision, not a gap. The boot audit has honoured this
    # since CRUDEOIL was parked on 2026-08-26; this one did not, so the weekly
    # report was about to announce "CRUDEOIL: NO live strategy is scoped to it"
    # every Friday for a choice already made. An alarm that fires every week for
    # a settled decision is how the one that matters gets skipped.
    try:
        from bots.autonomous.autonomous_bot import AutonomousTradingBot as _Bot
        parked = dict(getattr(_Bot, "PARKED_ASSETS", {}) or {})
    except Exception:
        parked = {}

    gaps: list[str] = []
    for asset in UNIVERSE:
        if asset.upper() in parked:
            continue
        owners = [
            info for info in lineup.values()
            if info.get("status") not in (None, "UNKNOWN", "ARCHIVED")
            and (not info.get("scope") or asset.upper() in info["scope"])
        ]
        solvent = [o for o in owners if float(o.get("chest") or 0.0) > 0]
        if solvent:
            continue
        if owners:
            names = ", ".join(sorted(o.get("name", "?") for o in owners))
            gaps.append(f"{asset}: only {names} is scoped to it, and it has no chest "
                        f"— it will win auctions and fill nothing.")
        else:
            gaps.append(f"{asset}: NO live strategy is scoped to it. It cannot trade.")
    return gaps


# ------------------------------------------------------------------ snapshots
def previous_snapshots(limit: int = 2, exclude: str | None = None) -> list[dict]:
    if not SNAPSHOT_DIR.exists():
        return []
    files = sorted(SNAPSHOT_DIR.glob("*.json"), reverse=True)
    out = []
    for path in files:
        if exclude and path.stem == exclude:
            continue
        try:
            out.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
        if len(out) >= limit:
            break
    return out


def _get(snapshot: dict, module: str, symbol: str) -> dict | None:
    return (snapshot.get("measurements") or {}).get(symbol, {}).get(module)


# ------------------------------------------------------------------- reporting
def build_report(current: dict, history: list[dict]) -> dict:
    """Deltas, demotion candidates, revival candidates."""
    prev = history[0] if history else None
    older = history[1] if len(history) > 1 else None

    # A DELTA ACROSS TWO MEASUREMENT BASES IS NOT A CHANGE IN EDGE.
    #
    # The first run under the 2026-08-28 geometry produced this, and every line
    # of it was the ruler moving rather than the market:
    #
    #     RangeFade/NATURALGAS   +4.34 -> +1.08  (-3.26)
    #     SessionShift/GOLDM     +3.70 -> +1.87  (-1.83)
    #
    # Both dropped because the stop was included, the sample was split, and the
    # contract had rolled — not because either module got worse. Reporting that
    # as a "notable move", or as a second week below the bar, would hand the
    # commander a decline that did not happen. evolution.plan() already refuses
    # to compare across bases; the human-readable report must refuse too.
    if prev is not None and current.get("geometry") != prev.get("geometry"):
        prev = older = None

    lineup = current["lineup"]

    moves, demotions, revivals, new_rows = [], [], [], []

    for symbol, per_module in current["measurements"].items():
        for module, stat in per_module.items():
            info = lineup.get(module, {})
            status = info.get("status", "UNKNOWN")
            scoped = symbol in info.get("scope", [])
            is_live = status not in ("ARCHIVED", "UNKNOWN") and scoped

            before = _get(prev, module, symbol) if prev else None
            if before is None:
                new_rows.append({"module": module, "symbol": symbol, **stat,
                                 "status": status, "scoped": scoped})
            else:
                delta = stat["t"] - before["t"]
                if abs(delta) >= 0.75:  # smaller moves are week-to-week noise
                    moves.append({
                        "module": module, "symbol": symbol, "status": status,
                        "scoped": scoped, "t_before": before["t"], "t_now": stat["t"],
                        "delta": delta, "n": stat["n"],
                    })

            if is_live and stat["t"] < SHIP_BAR:
                two_weeks = before is not None and before["t"] < SHIP_BAR
                if two_weeks:
                    demotions.append({
                        "module": module, "symbol": symbol,
                        "name": info.get("name", module),
                        "t_now": stat["t"], "t_prev": before["t"], "n": stat["n"],
                    })
            if status == "ARCHIVED" and stat["t"] >= SHIP_BAR:
                revivals.append({
                    "module": module, "symbol": symbol,
                    "name": info.get("name", module),
                    "t": stat["t"], "n": stat["n"],
                })

    moves.sort(key=lambda m: abs(m["delta"]), reverse=True)
    demotions.sort(key=lambda d: d["t_now"])
    revivals.sort(key=lambda r: -r["t"])
    return {
        "compared_to": prev["date"] if prev else None,
        "had_two_priors": older is not None,
        "moves": moves, "demotions": demotions, "revivals": revivals,
        "new": new_rows,
    }


def coverage_line(weeks: int = 8) -> str:
    """How many of the last weeks' sessions Hokage was actually awake for.

    WHY THIS BELONGS IN THE AUDIT. Every number below it is an average over
    sessions Hokage SAW, and he has seen about half of them - 23 of 48 when
    that was first measured. A per-cell n is as much a count of sessions
    attended as of setups found, and `session_coverage.py` could answer it all
    along but was a standalone tool nobody ran. An uptime figure nobody reads
    is the same as not measuring uptime.

    Sessions come from the candle archive, so no holiday list can go stale.
    Returns a plain line on any failure rather than taking the audit down with
    it: this is context, not a verdict.
    """
    try:
        import datetime as _dt
        import sys as _sys
        from pathlib import Path as _P

        ops = str(_P(__file__).resolve().parents[1] / "ops")
        if ops not in _sys.path:
            _sys.path.insert(0, ops)
        import session_coverage

        end = _dt.date.today()
        start = end - _dt.timedelta(weeks=weeks)
        c = session_coverage.coverage(start, end)
        total = c.get("sessions", 0)
        if not total:
            return "coverage: no sessions in the archive for this window"
        covered = c.get("covered", 0)
        pct = covered / total * 100.0
        line = (f"coverage: awake for {covered} of {total} sessions "
                f"({pct:.0f}%) over {weeks} weeks")
        if c.get("partial"):
            line += f", {c['partial']} partial"
        if c.get("longest_blackout", 0) > 1:
            line += f", longest blackout {c['longest_blackout']} sessions"
        if pct < 80.0:
            line += "  <-- every n below is a count of sessions ATTENDED"
        return line
    except Exception as exc:
        return f"coverage: could not be measured ({type(exc).__name__})"


def render(current: dict, report: dict) -> str:
    lines = [f"HOKAGE WEEKLY AUDIT — {current['date']}",
             f"horizon {HORIZON * 15}min · ship bar t>={SHIP_BAR} · min n={MIN_N}"]
    lines.append(
        f"geometry: {GEOMETRY} (hold-out half; per-cell production stop, "
        f"default {PROD_STOP_ATR} ATR; target at "
        f"max({Bot._OPTION_TARGET_MOVE_FRACTION}xATRxsqrt(bars_left), "
        f"{Bot._OPTION_MIN_REWARD_RISK}xstop))"
    )
    lines.append(coverage_line())
    if report["compared_to"]:
        lines.append(f"compared to {report['compared_to']}")
    else:
        lines.append(
            "NO COMPARABLE PRIOR SNAPSHOT — nothing to diff. Either this is the "
            "first run, or the measurement basis changed and last week's numbers "
            "were taken with a different ruler. Retirement needs two audits on "
            "the SAME basis, so the clock starts here."
        )
    lines.append("")

    if report["demotions"]:
        lines.append("DEMOTION CANDIDATES (live, below the bar TWO weeks running):")
        for d in report["demotions"]:
            lines.append(f"  {d['name']} on {d['symbol']}: t={d['t_now']:+.2f} "
                         f"(was {d['t_prev']:+.2f}), n={d['n']}")
        lines.append("")
    if report["revivals"]:
        lines.append("REVIVAL CANDIDATES (archived, back above the bar):")
        for r in report["revivals"]:
            lines.append(f"  {r['name']} on {r['symbol']}: t={r['t']:+.2f}, n={r['n']}")
        lines.append("")
    if report["moves"]:
        lines.append("NOTABLE MOVES (|delta t| >= 0.75):")
        for m in report["moves"][:12]:
            tag = "LIVE" if m["scoped"] and m["status"] != "ARCHIVED" else m["status"].lower()
            lines.append(f"  {m['module']} / {m['symbol']} [{tag}]: "
                         f"{m['t_before']:+.2f} -> {m['t_now']:+.2f} "
                         f"({m['delta']:+.2f})")
        lines.append("")
    if not (report["demotions"] or report["revivals"] or report["moves"]):
        if report["compared_to"]:
            lines.append("Nothing moved enough to report. The lineup measures as it did last week.")
        else:
            lines.append(f"Baseline recorded: {len(report['new'])} (module, asset) pairs measured. "
                         f"Deltas begin next run.")
        lines.append("")

    live = [(s, m, st) for s, per in current["measurements"].items()
            for m, st in per.items()
            if s in current["lineup"].get(m, {}).get("scope", [])
            and current["lineup"].get(m, {}).get("status") not in ("ARCHIVED", "UNKNOWN")]
    if live:
        lines.append("LIVE LINEUP AS MEASURED:")
        for symbol, module, stat in sorted(live, key=lambda x: -x[2]["t"]):
            flag = "" if stat["t"] >= SHIP_BAR else "   << below bar"
            lines.append(f"  {current['lineup'][module]['name']:14s} {symbol:11s} "
                         f"n={stat['n']:>4d} t={stat['t']:+.2f}{flag}")
    return "\n".join(lines)


# ------------------------------------------------------------------------ main
def parked_watch(measurements: dict) -> str:
    """Is a PARKED asset ready to come back? Reported every week.

    WHY THIS EXISTS. CRUDEOIL was parked on 2026-08-26 after six sweeps failed
    out of sample, and re-measured on 2026-09-02 with everything built since —
    the candle archive, derived train/hold windows, full geometry. Still nothing
    confirmed, seventh sweep.

    But nothing was WATCHING it. The knob sweep only visits LIVE pairs, and this
    audit measured crude every week and then said nothing about it. Parking was
    a one-way door: an asset with no live strategy generates no proposals, so
    improving evidence would never have surfaced and crude could never have
    earned its way back.

    That is a direct obstacle to the commander's stated aim — Hokage is to become
    a MASTER of crude and natural gas. Mastery of an asset you have stopped
    looking at is not reachable. So every parked asset is scored here weekly,
    and the moment something clears the bar on BOTH halves it is named.

    Reviving is Tier 3 — it ADDS risk — so this reports and never acts, however
    good the number.
    """
    try:
        from bots.autonomous.autonomous_bot import AutonomousTradingBot as _Bot
        parked = dict(getattr(_Bot, "PARKED_ASSETS", {}) or {})
    except Exception:
        return ""
    if not parked:
        return ""

    lines = ["", "-" * 60, "PARKED ASSET WATCH"]
    for asset, reason in sorted(parked.items()):
        rows = (measurements.get(asset) or {})
        lines.append(f"  {asset} — {reason}")
        if not rows:
            lines.append("    nothing measurable this week.")
            continue
        ranked = sorted(rows.items(), key=lambda kv: -kv[1].get("t", 0.0))
        for module, stat in ranked[:4]:
            train_t = stat.get("t_train")
            train = "below min n" if train_t is None else f"{train_t:+.2f}"
            lines.append(
                "    %-28s train %-12s hold %+.2f (n=%d)%s"
                % (module, train, stat.get("t", 0.0), stat.get("n", 0),
                   "   <<< CLEARS BOTH HALVES" if stat.get("confirmed") else "")
            )
        ready = [m for m, s in ranked if s.get("confirmed")]
        if ready:
            lines.append(
                f"    -> {', '.join(ready)} now clears the bar on {asset}. "
                f"Reviving ADDS risk, so it is Tier 3 and waits for your word."
            )
        else:
            lines.append("    -> still nothing clears both halves. Stays parked.")
    return "\n".join(lines)


from hokage.research import proposals as _proposals  # noqa: E402


def _record_retirements(decisions) -> str:
    """Cleared Tier 1 retirements become PENDING proposals. Returns a report line.

    Deduplicated on (strategy, asset, action) against anything already PENDING or
    REJECTED, for the same reason the knob sweep is: a weekly job that re-asks an
    answered question every Friday teaches the commander to stop reading it.
    """
    import sqlite3
    import uuid
    from datetime import datetime as _dt, timezone as _tz

    cleared = [d for d in decisions if getattr(d, "is_autonomous", False)]
    if not cleared:
        return ""

    db = BRAIN / "hokage.db"
    if not db.exists():
        return "(no brain database — retirement not recorded)"

    written, skipped, unstamped = [], [], []
    with sqlite3.connect(db) as conn:
        for d in cleared:
            new_values = json.dumps({"status": "ARCHIVED", "asset": d.asset})
            has_basis = conn.execute(
                "SELECT 1 FROM pragma_table_info('improvement_proposals') "
                "WHERE name='measured_geometry'"
            ).fetchone() is not None
            existing = conn.execute(
                "SELECT status, %s FROM improvement_proposals WHERE strategy_id=? "
                "AND asset=? AND action=? AND status IN "
                "('PENDING','PENDING_APPROVAL','REJECTED')"
                % ("measured_geometry" if has_basis else "NULL"),
                (d.strategy_id, d.asset, "ARCHIVE_STRATEGY"),
            ).fetchone()
            # A retirement rests on a TREND, and a basis change resets the
            # clock - the rule _same_geometry already applies to snapshots. A
            # PENDING retirement measured on the old basis must therefore not
            # suppress this one, which was measured on the current one. A
            # REJECTED one still does: that is the commander's answer.
            if existing and (existing[0] == "REJECTED"
                             or not _proposals.is_stale(existing[1], SHIP_BAR)):
                skipped.append(f"{d.strategy_name}/{d.asset} (already {existing[0]})")
                continue
            # has_basis is schema 9, which arrives when Hokage next boots.
            # Writing without it is survivable - the row reads as stale and
            # cannot be applied - but it must be said out loud.
            cols = ("proposal_id, strategy_id, strategy_name, asset, timestamp, "
                    "action, previous_values, new_values, rationale, "
                    "expected_improvement, status")
            values = ["retire-" + uuid.uuid4().hex[:12], d.strategy_id,
                      d.strategy_name, d.asset, _dt.now(_tz.utc).isoformat(),
                      "ARCHIVE_STRATEGY", json.dumps({"status": "LIVE"}),
                      new_values,
                      f"{d.reason} | evidence: {json.dumps(d.evidence)}",
                      0.0, "PENDING"]
            if has_basis:
                cols += ", measured_geometry"
                values.append(GEOMETRY)
            else:
                unstamped.append(f"{d.strategy_name}/{d.asset}")
            conn.execute(
                f"INSERT INTO improvement_proposals ({cols}) VALUES "
                f"({','.join('?' * len(values))})",
                values,
            )
            written.append(f"{d.strategy_name}/{d.asset}")

    lines = []
    if written:
        lines.append("Recorded as PENDING proposals: " + ", ".join(written)
                     + ". Apply with Hokage STOPPED — a running Hokage rewrites "
                       "the portfolio from memory and would undo it.")
    if skipped:
        lines.append("Already answered, not re-asked: " + ", ".join(skipped))
    if unstamped:
        lines.append("!! Written WITHOUT a measurement basis (brain at schema 8): "
                     + ", ".join(unstamped)
                     + ". They read as stale and cannot be applied. Restart "
                       "Hokage to migrate, then re-run the audit.")
    return "\n".join(lines)


def _parked_now() -> set[str]:
    """The live PARKED_ASSETS keys, or an empty set if they cannot be read.

    Empty is the conservative direction here: it can only make RAIL 2 block a
    retirement, never allow one.
    """
    try:
        from bots.autonomous.autonomous_bot import AutonomousTradingBot as _Bot
        return {str(a).upper() for a in (getattr(_Bot, "PARKED_ASSETS", {}) or {})}
    except Exception:
        return set()


def main() -> int:
    args = set(sys.argv[1:])
    dry_run = "--dry-run" in args
    telegram = "--telegram" in args

    end = datetime.now(timezone.utc)

    lineup = live_lineup()
    measurements: dict[str, dict] = {}
    raw_hold: dict[str, dict] = {}
    windows: dict[str, dict] = {}
    failed: list[str] = []

    for symbol in UNIVERSE:
        modules = MCX_ENTRY_MODULES if symbol in _MCX_FUTURES else ENTRY_MODULES
        named = {getattr(m, "module_id", k): m for k, m in modules.items()}
        try:
            stats, raw, (train_win, hold_win) = measure_split(symbol, named)
        except Exception as exc:
            print(f"  {symbol}: {exc}")
            failed.append(symbol)
            continue
        measurements[symbol] = stats
        # Pooling reads the hold-out only. Pooling both halves together would
        # rebuild the very number this change exists to retire.
        raw_hold[symbol] = raw["hold"]
        windows[symbol] = {"train": list(train_win), "hold": list(hold_win)}

    if not measurements:
        print("No asset could be measured — is the broker session live? "
              "Refusing to write an empty snapshot.")
        return 1

    today = date.today().isoformat()
    current = {
        "date": today,
        "generated_at": end.isoformat(),
        "horizon_bars": HORIZON,
        "ship_bar": SHIP_BAR,
        "lookback_days": LOOKBACK_DAYS,
        # How this snapshot was measured. evolution.plan() refuses to treat two
        # snapshots as consecutive evidence unless these match, so changing the
        # basis resets the retirement clock instead of silently comparing a
        # no-stop pooled t against a hold-out-with-stop t.
        "geometry": GEOMETRY,
        "stop_atr": PROD_STOP_ATR,
        # Which assets were PARKED when this was measured. RAIL 2 in
        # evolution.plan() refuses to retire a module that would leave an
        # asset uncovered - and until 2026-10-31 it counted a parked asset as
        # coverage worth defending, so EventRider could never be retired
        # because it nominally covers CRUDEOIL, which nobody trades. Stamped
        # rather than read live so a retirement decision stays reproducible
        # from the snapshot alone, like `geometry`.
        "parked_assets": sorted(_parked_now()),
        "windows": windows,
        "failed_symbols": failed,
        "lineup": lineup,
        "measurements": measurements,
        # The leagues `pooled` is keyed by, and which assets each one pools.
        # evolution.plan() maps a decided asset to its league to find the
        # module-wide reading; stamped for the same reason as `geometry` and
        # `parked_assets`, so a retirement stays reproducible from the
        # snapshot alone rather than from whatever LEAGUES happens to say
        # months later.
        "leagues": {name: list(assets) for name, assets in LEAGUES},
        # WIRED INTO TIER 1 on 2026-10-31, and only as a VETO. Until then this
        # was an extra key by design - plan() read lineup and measurements
        # only - and the consequence was that a module-wide retirement was
        # justified by a single CELL. On 2026-10-31 that meant EventRider
        # cleared on its CRUDEOIL cell: a parked asset it has never traded.
        # The pooled t is an upper bound on significance, so it may BLOCK a
        # retirement the per-cell rule cleared and may never clear one itself.
        "pooled": pool(raw_hold),
    }

    history = previous_snapshots(2, exclude=today)
    report = build_report(current, history)
    text = render(current, report)

    # A module that fires nine times a quarter on one index can never reach
    # significance per asset. Pooled across its league it can, which is how
    # MacroBreakout turned out to be the only index module that does not look
    # like noise.
    pooled = current.get("pooled") or {}
    if pooled:
        lines = ["", "-" * 60, "POOLED ACROSS EACH LEAGUE"]
        for league, mods in pooled.items():
            lines.append("  " + league)
            for name, s in sorted(mods.items(), key=lambda kv: -kv[1]["t"]):
                lines.append("    %-26s n=%-5d edge=%+.3f  t=%+.2f"
                             % (name, s["n"], s["edge_atr"], s["t"]))
        lines += ["", POOLED_CAVEAT]
        text += chr(10) + chr(10).join(lines)

    # Coverage first: a strategy measuring badly is a question about the
    # lineup, but an asset nobody can trade is a hole in the arena itself, and
    # it is silent. Report it above the evolution verdict.
    # A parked asset is deliberately absent from the orphan list, so it needs
    # its own section or it is never spoken about again.
    text += chr(10) + parked_watch(measurements)

    gaps = coverage_gaps(lineup)
    if gaps:
        text += ("\n\n" + "-" * 60 + "\nORPHANED ASSETS\n"
                 + "\n".join(f"  {g}" for g in gaps)
                 + "\n\nThese raise no error and fill no order. They just never trade.")

    # Phase 2: run the evolution policy over the same snapshots and say what it
    # would do. Nothing is applied while evolution.AUTONOMOUS_ENABLED is False —
    # the first cycle is observed, not acted on.
    try:
        from bots.autonomous import evolution

        decisions = evolution.plan([current] + history)
        verdict = evolution.summarise(decisions)
        if verdict:
            text += "\n\n" + "-" * 60 + "\nEVOLUTION POLICY\n" + verdict
            if not evolution.AUTONOMOUS_ENABLED:
                text += ("\n\n(Autonomy is not armed yet. This is a report of what "
                         "Hokage WOULD do; the lineup is unchanged.)")
            # A retirement the policy has CLEARED becomes a PENDING proposal,
            # in the same table the knob sweep writes to, so there is one place
            # the commander rules on changes.
            #
            # IT IS NOT APPLIED HERE, and that is not timidity. This job runs at
            # 23:45 while Hokage is RUNNING, and a running Hokage rewrites
            # hokage_brain/portfolio/*.json from memory — on 2026-08-26 that
            # silently reverted the CRUDEOIL park within hours and he traded a
            # parked asset all day. An archive written underneath a live process
            # would be undone exactly the same way, and would report success
            # while doing nothing. Applying it is a deliberate act taken with
            # Hokage stopped.
            if not dry_run:
                text += "\n" + _record_retirements(decisions)
    except Exception as exc:
        text += f"\n\n(evolution policy failed to run: {exc})"

    # The middle step Hokage never had. The audit above re-SCORES the lineup as
    # it stands and the evolution policy PRUNES what has stopped working;
    # neither can look at a module that works and ask whether one of its own
    # knobs would work better. Until 2026-08-26 that question was only ever
    # answered by Claude, by hand, in a chat session — 117 autopsies on disk and
    # zero improvement proposals ever written.
    #
    # Nothing here is applied. Proposals land as PENDING rows for the commander,
    # and anything tiered ASK is printed and not written at all.
    swept: list = []
    if not dry_run:
        try:
            import sweep_lab

            proposals, asked = sweep_lab.sweep()
            fresh = [p for p in proposals if not sweep_lab.already_answered(p)]
            swept = fresh + asked
            if fresh or asked:
                lines = ["", "-" * 60, "KNOB SWEEP"]
                for p in fresh:
                    lines.append("  PROPOSE  " + p["rationale"])
                    lines.append("           -> " + sweep_lab.write_proposal(p))
                for r in asked:
                    lines.append("  ASK      " + r)
                lines.append("")
                lines.append("Nothing is applied. Review with /proposals.")
                text += chr(10) + chr(10).join(lines)
        except Exception as exc:
            text += f"\n\n(knob sweep failed to run: {exc})"

    print("\n" + text + "\n")

    if not dry_run:
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        (SNAPSHOT_DIR / f"{today}.json").write_text(
            json.dumps(current, indent=2), encoding="utf-8"
        )
        print(f"snapshot written: hokage_brain/research/snapshots/{today}.json")

    if telegram:
        # A knob proposal is a decision waiting on the commander, so it counts
        # as news even in a week where nothing else moved. Without this the loop
        # would close and then talk to a log file nobody reads.
        worth_sending = bool(report["demotions"] or report["revivals"]
                             or report["moves"] or swept)
        if not worth_sending:
            print("telegram: nothing changed, staying quiet.")
        else:
            try:
                from integrations.notifications.telegram_bot import TelegramBotUplink

                bot = TelegramBotUplink()
                if bot.enabled:
                    bot.send_message(text)
                    print("telegram: sent.")
                else:
                    print("telegram: uplink disabled.")
            except Exception as exc:
                print(f"telegram: failed ({exc})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
