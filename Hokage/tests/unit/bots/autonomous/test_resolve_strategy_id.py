"""Ten places asked a strategy record for its own name by subscript.

Found while reading the entry path after EIAReaction's record turned out to
be a 7-field stub with no `strategy_id` (see test_strategy_record_audit.py).
The audit shipped first and names the thin record at boot. This is the other
half: what the entry path does when one reaches it anyway.

    MCX    4 sites   order attribution, war chest, the log line, tracking
    Index  6 sites   committee ledger, chest x3, tracking

Every one of them read `selected_strat["strategy_id"]`. On 2026-10-29
EIAReaction won the 20:30 NATURALGAS auction and was stopped by the bias gate
one line earlier; had that gate waved it through, the arena scan would have
raised KeyError in the middle of a loop over the universe rather than traded.

AND THE LENIENT READING IS WORSE THAN THE CRASH. `_strategy_available_capital`
does not raise on an id it cannot find - it falls through to
STRATEGY_STARTING_CAPITAL and returns a FULL FRESH CHEST. A `.get()` at each
site would have turned a loud KeyError into a strategy silently funded as if
it had never traded. Unresolvable must mean stand aside, loudly.

WHAT THIS FILE PINS: that the id resolves from the key when the record does
not carry it, that identity decides which key, that unresolvable stays None
rather than guessing - and, since the commander approved it on 2026-10-30,
that the four counter-trend gate call sites read the resolved id, with the
blast radius measured: only modules already carrying COUNTER_TREND skip the
trend-join gate, and only EIAReaction's behaviour changes, because it owns
the only record in either league that cannot name itself.
"""
from __future__ import annotations

from pathlib import Path

from bots.autonomous.autonomous_bot import AutonomousTradingBot as Bot


def _bot():
    return object.__new__(Bot)


# ---------------------------------------------------- 1. it resolves the name
def test_the_stored_field_is_used_when_it_is_there():
    rec = {"strategy_id": "strat-trendrider-mcx-v1", "name": "TrendRider"}
    assert _bot()._resolve_strategy_id(rec, {"some-other-key": rec}) == \
        "strat-trendrider-mcx-v1"


def test_the_key_answers_when_the_record_cannot():
    """THE WHOLE POINT, in the shape it actually occurred."""
    stub = {"name": "EIAReaction", "status": "ACTIVE"}
    strategies = {"strat-eiareaction-mcx-v1": stub,
                  "strat-trendrider-mcx-v1": {"strategy_id": "strat-trendrider-mcx-v1"}}
    assert _bot()._resolve_strategy_id(stub, strategies) == "strat-eiareaction-mcx-v1"


def test_identity_decides_which_key_not_equality():
    """Two strategies can hold equal dicts. The question is which key THIS
    object is filed under, so `is` rather than `==`."""
    first = {"name": "Twin", "status": "ACTIVE"}
    second = {"name": "Twin", "status": "ACTIVE"}
    assert first == second
    strategies = {"strat-first-mcx-v1": first, "strat-second-mcx-v1": second}
    bot = _bot()
    assert bot._resolve_strategy_id(second, strategies) == "strat-second-mcx-v1"
    assert bot._resolve_strategy_id(first, strategies) == "strat-first-mcx-v1"


def test_an_empty_string_id_falls_back_to_the_key():
    """An empty id is not an id. It would reach
    `_strategy_available_capital` and draw a fresh chest."""
    rec = {"strategy_id": "", "name": "Blank"}
    assert _bot()._resolve_strategy_id(rec, {"strat-blank-mcx-v1": rec}) == \
        "strat-blank-mcx-v1"


# ------------------------------------------- 2. it never guesses when it can't
def test_a_record_in_no_portfolio_resolves_to_nothing():
    """None is the signal to stand aside. Returning a plausible-looking id
    here is how a strategy gets funded as something it is not."""
    orphan = {"name": "Orphan", "status": "ACTIVE"}
    assert _bot()._resolve_strategy_id(orphan, {"strat-other-v1": {}}) is None


def test_a_missing_portfolio_is_not_an_error():
    assert _bot()._resolve_strategy_id({"name": "X"}, None) is None
    assert _bot()._resolve_strategy_id({"name": "X"}, {}) is None


def test_a_non_dict_record_resolves_to_nothing():
    bot = _bot()
    assert bot._resolve_strategy_id("not a record", {"k": "not a record"}) is None
    assert bot._resolve_strategy_id(None, {}) is None


def test_a_non_string_stored_id_is_returned_as_a_string():
    """Callers index dicts and format log lines with it."""
    rec = {"strategy_id": 7}
    assert _bot()._resolve_strategy_id(rec, {}) == "7"


# --------------------------- 3. the gates read it too, since 2026-10-30
def test_the_counter_trend_gates_read_the_resolved_id():
    """THE FIX THE COMMANDER APPROVED on 2026-10-30.

    All four gate call sites - conduct and cluster, in both leagues - now
    pass the resolved id. Passing `selected_strat.get("strategy_id")` there
    is what kept a shipped exemption shut for a week, so if the blind form
    comes back, this fails.
    """
    import bots.autonomous.autonomous_bot as mod
    src = Path(mod.__file__).read_text(encoding="utf-8")
    assert src.count("_is_counter_trend_strategy(selected_sid)") == 4
    assert '_is_counter_trend_strategy(selected_strat.get("strategy_id"))' not in src


def test_a_stub_record_now_reaches_its_own_counter_trend_flag():
    """END TO END, on the real registries and the real id.

    This is the whole chain that was broken: the record cannot name itself ->
    the key names it -> the entry module registry is keyed by that id -> the
    module carries COUNTER_TREND. Any link breaking puts EIAReaction back
    behind the trend-join gate, which is where it spent 2026-10-22 and
    2026-10-29.
    """
    from bots.strategy.components.mcx_entries import MCX_ENTRY_MODULES
    stub = {"name": "EIAReaction", "status": "ACTIVE"}
    bot = _bot()
    sid = bot._resolve_strategy_id(stub, {"strat-eiareaction-mcx-v1": stub})
    assert sid in MCX_ENTRY_MODULES
    assert bot._is_counter_trend_strategy(sid) is True
    # and the blind form it replaced still says the opposite, which is the
    # bug in one line.
    assert bot._is_counter_trend_strategy(stub.get("strategy_id")) is False


def test_the_fix_does_not_exempt_anything_that_was_not_already_flagged():
    """A gate loosening has to have a measured blast radius. Only modules
    carrying COUNTER_TREND skip the trend-join gate; resolving an id does not
    confer the flag on a trend-follower."""
    bot = _bot()
    for sid in ("strat-trendrider-mcx-v1", "strat-sessionshift-mcx-v1",
                "strat-eventrider-mcx-v1", "strat-ridertrend-mcx-v1"):
        assert bot._is_counter_trend_strategy(sid) is False
    for sid in ("strat-rangefade-mcx-v1", "strat-eiareaction-mcx-v1",
                "strat-faderange-mcx-v1", "strat-meanreversion-sideways-v1"):
        assert bot._is_counter_trend_strategy(sid) is True


def test_nothing_in_the_entry_path_subscripts_the_id_any_more():
    """The crash this file exists for. A stub reaching the entry path must
    stand aside, not raise KeyError mid-scan."""
    import bots.autonomous.autonomous_bot as mod
    src = Path(mod.__file__).read_text(encoding="utf-8")
    code = [ln for ln in src.splitlines()
            if 'selected_strat["strategy_id"]' in ln or "selected_strat['strategy_id']" in ln]
    # The only survivor is the explanation in the resolver's own docstring.
    assert [ln for ln in code if not ln.lstrip().startswith(("#", "path reads"))] == []
