"""Theta was the last unmeasured term in the cost of a round trip, and the
first version of the measurement was wrong twice in the same way.

2026-11-09. Three cells were funded because a measured edge exceeded a measured
round trip, and both labs that produced those costs said in writing that decay
over the holding period was NOT included. This is that term.

TWICE THE SAME BUG, ONE LEVEL APART. The archive holds 926 usable contract
pairs over twelve days. Treating each contract as an observation gave SENSEX
t = -15.17; clustering by day gave t = -3.69. Then, pairing every day with
every other day inside a four-day window took NIFTY's eleven independent
day-pairs to twenty-three and its t from -1.23 to -2.37 - across the
significance bar on no new information, because (19->21), (20->21) and
(19->20) are three views of two days.

Both are the same error: counting correlated readings as independent ones. The
tests below pin the construction rather than the output, because the numbers
will move as the archive grows and the construction must not.

WHAT A COST MEASUREMENT MUST NEVER DO IS FLATTER ITSELF. A stale spot looks
exactly like decay, a vega rally looks exactly like negative decay, and an
unmeasurable asset must say so rather than return zero - a zero cost is the
cheapest possible lie about cost.
"""
from __future__ import annotations

import datetime as dt
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "research"))

import theta_lab  # noqa: E402

from hokage.research import funded_cells  # noqa: E402


# ============================================ the independence of observations
def test_each_day_appears_in_at_most_one_forward_difference():
    """The bug: every-pair-within-a-window double counts days.

    Five consecutive days must give four differences, not ten.
    """
    days = {"2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05",
            "2026-11-06"}
    pairs = theta_lab.adjacent_pairs(days)
    assert len(pairs) == 4
    firsts = [a for a, _ in pairs]
    assert len(set(firsts)) == len(firsts)
    seconds = [b for _, b in pairs]
    assert len(set(seconds)) == len(seconds)


def test_a_day_pairs_with_the_next_day_and_not_the_one_after():
    days = {"2026-11-02", "2026-11-03", "2026-11-04"}
    assert theta_lab.adjacent_pairs(days) == [
        ("2026-11-02", "2026-11-03"), ("2026-11-03", "2026-11-04")]


def test_a_weekend_still_pairs_because_it_is_the_next_session():
    """Friday to Monday is a three-day gap and the adjacent session. Dropping
    it would discard one difference in five on a five-session week."""
    pairs = theta_lab.adjacent_pairs({"2026-11-06", "2026-11-09"})
    assert pairs == [("2026-11-06", "2026-11-09")]


def test_a_long_gap_is_dropped_rather_than_divided():
    """Across three weeks the implied-volatility drift is the larger part of
    the change, so dividing by the day count would report drift as decay."""
    assert theta_lab.adjacent_pairs({"2026-10-19", "2026-11-09"}) == []


def test_a_single_day_yields_no_difference():
    assert theta_lab.adjacent_pairs({"2026-11-09"}) == []
    assert theta_lab.adjacent_pairs(set()) == []


def test_clustering_collapses_many_contracts_to_one_reading():
    """Twenty contracts captured the same evening share that evening's one
    volatility shock. They are one observation, not twenty."""
    obs = [{"day": "2026-11-02", "to": "2026-11-03", "pct_per_day": p}
           for p in (-1.0, -3.0, -5.0, -7.0)]
    obs += [{"day": "2026-11-03", "to": "2026-11-04", "pct_per_day": p}
            for p in (-2.0, -4.0)]
    daily = theta_lab.by_day(obs)
    assert len(daily) == 2
    assert daily == pytest.approx([-4.0, -3.0])


def test_the_t_statistic_is_computed_over_days_not_contracts():
    """Same mean, ten times the contracts, and the t must not move."""
    few = [{"day": f"2026-11-{d:02d}", "to": f"2026-11-{d + 1:02d}",
            "pct_per_day": v}
           for d, v in zip(range(2, 7), (-1.0, -3.0, -2.0, -4.0, -2.5))]
    many = [dict(row, pct_per_day=row["pct_per_day"] + shift)
            for row in few for shift in (-0.5, 0.0, 0.5)]
    a = theta_lab.summarise(theta_lab.by_day(few))
    b = theta_lab.summarise(theta_lab.by_day(many))
    assert a["days"] == b["days"] == 5
    assert b["t"] == pytest.approx(a["t"], rel=1e-6)


# ===================================================== the spot corroboration
@pytest.fixture
def archive(tmp_path, monkeypatch):
    """A chain archive with one day whose spot nothing confirms.

    This is 2026-10-20 as it really is in the live archive: a chain was
    captured, Hokage was down, and the capture carried the previous day's spot
    forward unchanged while the premiums moved.
    """
    monkeypatch.setenv("HOKAGE_BRAIN_ROOT", str(tmp_path / "brain"))
    from hokage.memory import option_archive as oa

    con = oa.connect()
    con.execute("CREATE TABLE IF NOT EXISTS candles (symbol TEXT, ts TEXT, "
                "contract TEXT, open REAL, high REAL, low REAL, close REAL, "
                "volume REAL)")
    rows = []
    for day, spot, call, put in (("2026-11-02", 24000.0, 300.0, 290.0),
                                 ("2026-11-03", 24000.0, 270.0, 320.0),
                                 ("2026-11-04", 24050.0, 250.0, 300.0)):
        for kind, price in (("CE", call), ("PE", put)):
            rows.append(("NIFTY", day, "2026-11-26", 24000.0, kind,
                         f"{day}T23:40:00+05:30", price, None, None, spot,
                         None, None))
    con.executemany(
        "INSERT INTO option_chain (symbol, day, expiry, strike, option_type, "
        "captured_at, last_price, oi, volume, spot, bid, ask) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    # No candle for 2026-11-03: that is the day he slept through.
    for day, close in (("2026-11-02", 24000.0), ("2026-11-04", 24050.0)):
        con.execute("INSERT INTO candles (symbol, ts, contract, close) "
                    "VALUES (?,?,?,?)",
                    ("NIFTY", f"{day}T15:29:00+05:30", "NIFTY 50", close))
    con.commit()
    return con


def test_a_day_without_a_candle_is_not_usable(archive):
    """The archived spot has to be confirmed by something that did not come
    from the same capture."""
    good = theta_lab.corroborated_days(archive, "NIFTY")
    assert good == {"2026-11-02", "2026-11-04"}


def test_a_stale_spot_day_is_excluded_from_the_difference(archive):
    """With 11-03 dropped, 11-02 and 11-04 are four days apart and still
    adjacent, so exactly one difference survives - not two."""
    obs = theta_lab.straddle_observations(archive, "NIFTY")
    assert {(o["day"], o["to"]) for o in obs} == {
        ("2026-11-02", "2026-11-04")}


def test_the_difference_is_divided_by_the_gap(archive):
    """590 to 550 over two days is 20 a day, not 40."""
    obs = theta_lab.straddle_observations(archive, "NIFTY")
    assert len(obs) == 1
    assert obs[0]["gap_days"] == 2
    assert obs[0]["pct_per_day"] == pytest.approx(
        (550.0 - 590.0) / 590.0 / 2 * 100.0)


# ============================================ what the straddle can and cannot
def test_a_one_legged_straddle_is_refused(tmp_path, monkeypatch):
    """A call without its put is a directional position carrying the delta
    this construction exists to cancel."""
    monkeypatch.setenv("HOKAGE_BRAIN_ROOT", str(tmp_path / "brain2"))
    from hokage.memory import option_archive as oa

    con = oa.connect()
    con.execute("CREATE TABLE IF NOT EXISTS candles (symbol TEXT, ts TEXT, "
                "contract TEXT, open REAL, high REAL, low REAL, close REAL, "
                "volume REAL)")
    for day, price in (("2026-11-02", 300.0), ("2026-11-03", 280.0)):
        con.execute(
            "INSERT INTO option_chain (symbol, day, expiry, strike, "
            "option_type, captured_at, last_price, spot) "
            "VALUES (?,?,?,?,?,?,?,?)",
            ("NIFTY", day, "2026-11-26", 24000.0, "CE",
             f"{day}T23:40:00+05:30", price, 24000.0))
        con.execute("INSERT INTO candles (symbol, ts, contract, close) "
                    "VALUES (?,?,?,?)",
                    ("NIFTY", f"{day}T15:29:00+05:30", "NIFTY 50", 24000.0))
    con.commit()
    assert theta_lab.corroborated_days(con, "NIFTY") == {"2026-11-02",
                                                         "2026-11-03"}
    assert theta_lab.straddle_observations(con, "NIFTY") == []
    con.close()


def test_a_positive_day_is_kept_because_it_is_the_error_bar():
    """A straddle that GAINED over a day cannot be decay - it is vega. Dropping
    those days would turn an honest range into a flattering constant."""
    daily = [-9.5, 8.8, -3.0, -1.0]
    stat = theta_lab.summarise(daily)
    assert stat["hi"] == pytest.approx(8.8)
    assert abs(stat["t"]) < 2.0


def test_the_lab_states_that_vega_is_not_removed():
    src = (ROOT / "tools" / "research" / "theta_lab.py").read_text(
        encoding="utf-8")
    flat = " ".join(src.split())
    assert "VEGA IS NOT REMOVED" in flat
    assert "theta plus vega" in flat


# =============================================== absence is reported as absence
def test_an_unmeasurable_asset_costs_nothing_rather_than_zero():
    """GOLDM has the widest funded margin and two non-consecutive archive
    days. A lab that returned 0.0 for it would report the best cell as the one
    with no decay."""
    assert theta_lab.cost_over_hold([], 40.0, "MCX") == (0.0, 0.0)
    src = (ROOT / "tools" / "research" / "theta_lab.py").read_text(
        encoding="utf-8")
    assert "no measurable decay" in src
    assert "funded but theta unmeasurable" in src


def test_the_bracket_spans_conventions_and_buckets():
    """Low bound: gentlest bucket over 24 hours. High bound: harshest bucket
    inside the session. A single mid-point would hide which assumption made
    the cell look survivable."""
    lo, hi = theta_lab.cost_over_hold([-1.0, -9.0], 40.0, "NSE")
    assert lo == pytest.approx(1.0 * 40.0 / 1440.0)
    assert hi == pytest.approx(9.0 * 40.0 / 375.0)
    assert hi > lo * 10


def test_the_harsh_bound_is_the_trading_session_not_the_clock():
    """A shut market cannot reprice, so the session is the harsher and more
    realistic denominator. MCX is open far longer, so its session bound is
    correspondingly gentler - and that difference must come from the table
    rather than from a single hardcoded number."""
    assert theta_lab.SESSION_MINUTES["NSE"] == 375      # 09:15-15:30
    assert theta_lab.SESSION_MINUTES["MCX"] == 870      # 09:00-23:30
    nse = theta_lab.cost_over_hold([-5.0], 60.0, "NSE")[1]
    mcx = theta_lab.cost_over_hold([-5.0], 60.0, "MCX")[1]
    assert nse > mcx


def test_a_bucket_with_too_few_days_states_no_number():
    stat = theta_lab.summarise([-3.0, -4.0])
    assert stat["days"] == 2
    assert stat["days"] < theta_lab.MIN_DAYS_FOR_A_NUMBER


def test_one_observation_carries_no_t_statistic():
    stat = theta_lab.summarise([-3.0])
    assert stat["days"] == 1
    assert stat["t"] is None


# ============================================== the holding period it scales by
def test_the_hold_comes_from_positions_not_trades():
    """`trades` is the exit writer's dead table and has never held a real
    entry; `positions` is the ledger. Reading the wrong one has produced three
    wrong answers already."""
    src = (ROOT / "tools" / "research" / "theta_lab.py").read_text(
        encoding="utf-8")
    body = src.split("def hold_minutes")[1].split("def cost_over_hold")[0]
    assert "FROM positions" in body
    assert "FROM trades" not in body


def test_the_underlying_is_parsed_out_of_the_contract_symbol():
    """`positions.market` stores the contract, not the underlying, so the hold
    for GOLDM is spread across every GOLDM strike ever traded."""
    import re

    pattern = r"^([A-Z]+?)(?=\d{2}[A-Z]{3}|\d{2}\d)"
    for symbol, want in (("GOLDM26AUG161000PE", "GOLDM"),
                         ("NIFTY2672124250CE", "NIFTY"),
                         ("CRUDEOIL26JUL7750CE", "CRUDEOIL"),
                         ("SENSEX2681378500PE", "SENSEX"),
                         ("NATURALGAS26NOV300PE", "NATURALGAS")):
        hit = re.match(pattern, symbol)
        assert hit is not None, symbol
        assert hit.group(1) == want


# ====================================== the edges and costs live in one place
def test_every_decided_asset_has_its_measurement_recorded():
    """The numbers that chose the family were prose only. A second reader
    needing them had to re-type them, which is how two copies of one fact
    start to disagree."""
    named = (funded_cells.funded_assets()
             | set(funded_cells.PARKED_FOR_COST)
             | set(funded_cells.TRADED_FOR_THE_RECORD))
    assert named <= set(funded_cells.MEASURED)


def test_the_funded_set_is_exactly_the_set_that_beats_its_cost():
    """This is the funding rule as an executable statement. If someone funds a
    cell whose edge does not cover a round trip, or parks one whose edge does,
    the prose and the decision have parted company and this fails."""
    beats = {a for a in funded_cells.MEASURED
             if funded_cells.beats_its_cost(a)}
    assert beats == funded_cells.funded_assets()


def test_gas_is_in_the_table_and_does_not_beat_its_cost():
    """Traded by directive, for the tape. The measurement stands against it
    and stays visible."""
    assert funded_cells.beats_its_cost("NATURALGAS") is False
    assert "NATURALGAS" in funded_cells.TRADED_FOR_THE_RECORD
    assert not funded_cells.is_funded_asset("NATURALGAS")


def test_an_unmeasured_asset_answers_none_not_false():
    """Absent is not false. A cell nobody has measured must not read as a cell
    that failed."""
    assert funded_cells.beats_its_cost("BANANA") is None


def test_the_costs_in_the_table_exclude_theta_and_say_so():
    src = (ROOT / "src" / "hokage" / "research" / "funded_cells.py").read_text(
        encoding="utf-8")
    flat = " ".join(src.split())
    assert "THETA IS NOT IN THESE COSTS" in flat
    assert "theta_lab" in flat


def test_asset_funding_and_cell_funding_are_different_questions():
    assert funded_cells.is_funded_asset("goldm") is True
    assert funded_cells.is_funded("strat-sessionshift-mcx-v1", "GOLDM") is True
    # Same asset, a module that does not hold it.
    assert funded_cells.is_funded("strat-trendrider-v1", "GOLDM") is False
    assert funded_cells.is_funded_asset("GOLDM") is True
