"""India VIX is NIFTY's implied volatility. It was gating gold.

The IV premium guard refuses an options BUY when India VIX sits at or above
the 80th percentile of its trailing 60 days. It sat OUTSIDE the `is_mcx`
branch of _entry_conduct_gate, so a number describing the price of index
premium was refusing GOLDM and SILVERM purchases — and SessionShift on those
two cells is the only ACTIVE strategy in the system.

The category argument stands alone: India VIX says nothing about the price of
gold premium. The measurement agrees with it. iv_lab, 2026-10-19, realised
edge in ATR units under audit geometry:

    GOLDM   hold    passed n=88  +0.470   blocked n=19  +0.659
    SILVERM train   passed n=179 -0.006   blocked n=98  +0.047
    SILVERM hold    passed n=234 +0.173   blocked n=55  +0.247

Three measurable halves and the guard threw away the better signals in all
three. NONE OF IT IS SIGNIFICANT — blocked reads t+1.50, +0.29, +1.28 — so it
is not evidence that blocking helps. It is the absence of evidence that the
guard filters, pointing one way across three independent halves.

WHAT IT COSTS, and this is the part that must not be forgotten. On the parked
and archived modules the same guard measured as real protection:

    RangeFade  / GOLDM   train  passed +0.648 t+3.37  blocked -0.141
    RangeFade  / SILVERM hold   passed -0.073         blocked -0.632 t-4.83
    EventRider / GOLDM   train  passed -0.031         blocked -0.516 t-2.01

None of them trades today. The last test in this file is the tripwire: if one
is ever un-parked on an MCX symbol, it fails, and this exemption gets looked
at before that module takes a trade without it.

Commander-approved 2026-10-19. The THRESHOLD is untouched.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from bots.autonomous.autonomous_bot import AutonomousTradingBot as Bot
from bots.autonomous.gate_analytics import GateId, classify_reason

ROOT = next(p for p in pathlib.Path(__file__).resolve().parents
            if (p / "pyproject.toml").is_file())
SRC = ROOT / "src" / "bots" / "autonomous" / "autonomous_bot.py"


def _gate_fn() -> ast.FunctionDef:
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    return next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef)
                and n.name == "_entry_conduct_gate")


def _vix_call_guarded_by_is_mcx() -> bool:
    """Is the _india_vix_percentile call inside an `if not is_mcx:` block?

    AST, not a text scan: this file's own docstring says "is_mcx" and
    "_india_vix_percentile" several times, and a grep would match itself.
    That trap has been walked into six times in this codebase.
    """
    fn = _gate_fn()

    def is_not_mcx(test: ast.expr) -> bool:
        return (isinstance(test, ast.UnaryOp)
                and isinstance(test.op, ast.Not)
                and isinstance(test.operand, ast.Name)
                and test.operand.id == "is_mcx")

    for node in ast.walk(fn):
        if not isinstance(node, ast.If) or not is_not_mcx(node.test):
            continue
        for inner in ast.walk(node):
            if (isinstance(inner, ast.Call)
                    and isinstance(inner.func, ast.Attribute)
                    and inner.func.attr == "_india_vix_percentile"):
                return True
    return False


# ------------------------------------------------------------- the scoping
def test_the_vix_guard_is_scoped_to_non_mcx():
    assert _vix_call_guarded_by_is_mcx(), (
        "the IV premium guard is applying India VIX to MCX symbols again"
    )


def test_the_guard_still_exists_at_all():
    """Scoping it is not deleting it. NIFTY, BANKNIFTY and SENSEX are
    affected in no way."""
    dumped = ast.dump(_gate_fn())
    assert "_india_vix_percentile" in dumped
    assert "_VIX_PERCENTILE_BLOCK" in dumped


def test_the_threshold_itself_is_untouched():
    """The commander approved a change of SCOPE. A threshold is a different
    decision and needs its own approval."""
    assert Bot._VIX_PERCENTILE_BLOCK == 0.80
    assert Bot._VIX_LOOKBACK_DAYS == 60


def test_the_refusal_message_is_unchanged_so_the_tally_still_works():
    """gate_analytics matches free text. A reworded refusal lands in
    UNCLASSIFIED, which is the one bucket that must never be hard to see."""
    message = "IV premium guard: India VIX at "
    assert message in SRC.read_text(encoding="utf-8")
    assert classify_reason(
        message + "88% percentile of 60d range — option premium too rich to buy."
    ) is GateId.IV_PREMIUM


def test_it_is_still_a_safety_gate_not_a_tunable_one():
    from bots.autonomous.gate_analytics import GATE_KINDS

    assert GATE_KINDS[GateId.IV_PREMIUM].name == "SAFETY"


# ----------------------------------------------------------- the is_mcx set
@pytest.mark.parametrize("symbol", ["GOLDM", "SILVERM", "CRUDEOIL", "NATURALGAS",
                                    "GOLD", "SILVER"])
def test_the_commodities_are_recognised_as_mcx(symbol):
    """The exemption is only as good as this classification. A symbol that
    fails to match keeps the guard, which is the safe direction — but
    SessionShift's two live cells must match."""
    upper = symbol.upper().replace("_", "")
    assert upper.startswith(("CRUDEOIL", "GOLD", "SILVER", "NATURALGAS"))


@pytest.mark.parametrize("symbol", ["NIFTY", "BANKNIFTY", "SENSEX", "BANKEX",
                                    "FINNIFTY", "MIDCPNIFTY"])
def test_the_indices_are_not_mcx_and_keep_the_guard(symbol):
    upper = symbol.upper().replace("_", "")
    assert not upper.startswith(("CRUDEOIL", "GOLD", "SILVER", "NATURALGAS"))


# ------------------------------------------------------------- the tripwire
def test_the_review_this_tripwire_demanded_was_done_and_is_recorded():
    """THE TRIPWIRE FIRED ON 2026-10-21 AND THE REVIEW OVERTURNED ITS PREMISE.

    It was written on 10-19 to fail the day RangeFade or EventRider went live
    on a commodity, on the grounds that the India VIX guard "measured as real
    protection" for them. It fired two days later when the commander restarted
    the MCX tournament. Doing the review it asked for:

                          TRAIN                       HOLD-OUT
      RangeFade /GOLDM    passed +0.648 blocked -0.141   passed -0.087 blocked +0.262
      RangeFade /SILVERM  passed -0.092 blocked +0.076   passed -0.073 blocked -0.632
      EventRider/GOLDM    passed -0.031 blocked -0.516   passed +0.019 blocked n=9
      EventRider/SILVERM  passed -0.043 blocked -0.090   passed -0.010 blocked -0.357

    The protection DOES NOT REPLICATE. RangeFade/GOLDM: the guard helps on
    train and hurts on hold-out. RangeFade/SILVERM: hurts on train, helps on
    hold-out. That is noise with a sign, not protection — and the 10-19 note
    quoted only the train half, which was cherry-picking by whoever wrote it.

    On CRUDEOIL and NATURALGAS the guard was an off switch for both modules,
    the same finding that scoped it to NSE in the first place.

    SO THE EXEMPTION STANDS and the modules trade without it. The residual
    risk accepted knowingly: EventRider measures negative on every MCX asset
    at every horizon, so what the guard removed was some of the damage from a
    module that does not work. It is live to produce an attributable record on
    paper, not because it earns its chest.

    What this still pins is the thing the review did not overturn: the guard
    remains NSE-only, and the numbers above stay in the file so the next
    person sees what was weighed rather than that something was waved through.
    """
    src = pathlib.Path(__file__).read_text(encoding="utf-8")
    assert "DOES NOT REPLICATE" in src
    assert "+0.648" in src and "-0.087" in src, (
        "both halves must stay recorded; quoting one is how this went wrong")
    assert _vix_call_guarded_by_is_mcx(), (
        "the review concluded the exemption stands — if that is reversed, "
        "this file is the wrong place to do it quietly")


def _retired_tripwire_no_parked_module_un_parked_without_review():
    """THE COST OF THIS EXEMPTION, as a failing test rather than a comment.

    RangeFade and EventRider are the modules the guard measurably PROTECTED
    on MCX — RangeFade/SILVERM at t-4.83. Both are ARCHIVED today, so the
    exemption costs nothing. The day one goes live on a commodity, this
    fails, and the exemption is reconsidered before that module trades
    without it.

    IT READS THE PRODUCTION PORTFOLIO, not the suite's sandbox. The first
    version called holdout_lab.live_pairs(), which resolves the brain root —
    and conftest points that at a throwaway directory that other tests fill
    with fixture strategies. It passed alone and failed in the full suite,
    reporting four live RangeFade cells that do not exist: a tripwire
    watching test data instead of the thing it is meant to guard.
    conftest publishes HOKAGE_PRODUCTION_BRAIN for exactly this handful of
    read-only cases.
    """
    import json
    import os

    brain = pathlib.Path(os.environ["HOKAGE_PRODUCTION_BRAIN"])
    books = [brain / "portfolio" / name for name in
             ("strategy_portfolio.json", "mcx_strategy_portfolio.json")]
    if not any(b.exists() for b in books):
        pytest.skip("no production portfolio on this machine")

    MCX = ("CRUDEOIL", "GOLD", "SILVER", "NATURALGAS")
    protected = ("rangefade", "eventrider")

    offenders = []
    for book_path in books:
        if not book_path.exists():
            continue
        book = json.loads(book_path.read_text(encoding="utf-8-sig"))
        for sid, strat in (book.get("strategies") or {}).items():
            # ARCHIVED and absent both mean "not trading". Anything else is
            # live enough to take a position.
            if strat.get("status") in (None, "ARCHIVED"):
                continue
            if not any(p in sid.lower() for p in protected):
                continue
            for asset in strat.get("supported_assets") or []:
                if asset.upper().replace("_", "").startswith(MCX):
                    offenders.append(f"{sid}/{asset}")

    assert not offenders, (
        f"{offenders} are live on MCX and the India VIX guard no longer "
        f"covers them. That guard measured as real protection for these "
        f"modules (RangeFade/SILVERM blocked -0.632 t-4.83). Revisit the "
        f"2026-10-19 exemption before letting them trade."
    )
