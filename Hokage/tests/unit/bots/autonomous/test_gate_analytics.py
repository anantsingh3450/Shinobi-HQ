"""The gate tally is the instrument we tune gates by — so it must not lie.

The dangerous failure here is not a crash, it is a quiet misclassification: a
reason silently counted under the wrong gate would send us tuning a threshold
that was never the bottleneck. These tests pin the verbatim strings the
production code emits, so a reworded reason fails here instead of rotting into
an UNCLASSIFIED bucket nobody reads.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from bots.autonomous.gate_analytics import (
    GATE_KINDS,
    GATE_LABELS,
    GateId,
    GateKind,
    classify_reason,
    tally_gate_rejections,
)


#: Verbatim reason strings as emitted by autonomous_bot.py / intelligence.py.
#: If production rewords one of these, this table must be updated with it.
REAL_REASONS: list[tuple[str, GateId]] = [
    ("Day-of-Week Isolator: NIFTY (index) is blocked on Monday.", GateId.DAY_ISOLATOR),
    (
        "Opening Bell Observation Protocol: Prohibited from executing entry orders until 09:30 AM IST.",
        GateId.OBSERVATION_WINDOW,
    ),
    ("Fast Trading Brain: Cached risk state is RISK-OFF.", GateId.RISK_OFF),
    ("Fast Trading Brain: Capital Preservation Mode is NO TRADE.", GateId.CAPITAL_PRESERVATION),
    ("Insufficient account cash balance.", GateId.CASH),
    (
        "SessionBehaviorEngine: Breakout trades suspended during mid-session mean-reverting environment.",
        GateId.SESSION_BEHAVIOR,
    ),
    ("Midday chop blackout (11:30-13:30 IST): new entries suspended.", GateId.SESSION_TIME),
    ("Late-session cutoff (14:00 IST): no new entries into the close.", GateId.SESSION_TIME),
    (
        "VolumeEngine: THIN_TAPE: Volume ratio 0.35x < required 0.80x (trend entry).",
        GateId.VOLUME,
    ),
    (
        "VolumeEngine: FAKE_BREAKOUT: Volume ratio 0.84x < required 1.20x (breakout entry).",
        GateId.VOLUME,
    ),
    (
        "LiquidityEngine: LIQUIDITY_TRAP: Bid-ask spread 0.30% exceeds max allowed 0.20%.",
        GateId.LIQUIDITY,
    ),
    (
        "LiquidityEngine: LIQUIDITY_TRAP: Extreme book depth imbalance (bid/ask ratio=7.00x).",
        GateId.LIQUIDITY,
    ),
    ("Bias engine: underlying tape is MIXED — standing aside.", GateId.BIAS),
    ("Bias engine: bearish entry against a BULLISH tape.", GateId.BIAS),
    ("Bias engine: bullish entry against a BEARISH tape.", GateId.BIAS),
    (
        "IV premium guard: India VIX at 85% percentile of 60d range — option premium too rich to buy.",
        GateId.IV_PREMIUM,
    ),
    ("OptionsRouter: No live CE contract found for NIFTY near 24075.", GateId.OPTIONS_ROUTING),
    (
        "War chest exhausted for strat-malfoy-momentum-v1: entry cost ₹60,000 exceeds remaining ₹12,000.",
        GateId.WAR_CHEST,
    ),
    (
        "Allocation sized to 0% by Capital Preservation sizing engine or active constraints: ['drawdown'].",
        GateId.ALLOCATION_ZERO,
    ),
    ("Committee Risk voted REJECT: Position risk exceeds boundary.", GateId.COMMITTEE),
    ("Committee rejections did not pass majority approval.", GateId.COMMITTEE),
]


@pytest.mark.parametrize("reason,expected", REAL_REASONS)
def test_every_production_reason_classifies_to_its_gate(reason: str, expected: GateId):
    assert classify_reason(reason) == expected


def test_unknown_reason_is_flagged_not_guessed():
    """A new gate message must surface as UNCLASSIFIED, never be forced into a
    neighbouring bucket — a wrong bucket corrupts the tuning decision."""
    assert classify_reason("Some brand new gate nobody has classified yet.") == GateId.UNCLASSIFIED
    assert classify_reason("") == GateId.UNCLASSIFIED


def test_every_gate_has_a_kind_and_a_label():
    for gate in GateId:
        assert gate in GATE_KINDS, f"{gate} has no safety/quality classification"
        assert gate in GATE_LABELS, f"{gate} has no human-readable label"


def test_capital_protecting_gates_are_never_marked_tunable():
    """The whole point of the kind flag: a tally must not invite loosening a
    gate that exists to protect capital, however often it blocks."""
    result = tally_gate_rejections(
        [
            {"asset": "NIFTY", "timestamp": "2026-07-15T10:00:00+00:00", "reasons": [r]}
            for r, _ in REAL_REASONS
        ]
    )
    by_gate = {g["gate"]: g for g in result["gates"]}

    for safety_gate in (
        GateId.LIQUIDITY,
        GateId.IV_PREMIUM,
        GateId.CASH,
        GateId.WAR_CHEST,
        GateId.RISK_OFF,
        GateId.CAPITAL_PRESERVATION,
        GateId.ALLOCATION_ZERO,
    ):
        assert by_gate[safety_gate.value]["tunable"] is False
        assert by_gate[safety_gate.value]["kind"] == GateKind.SAFETY.value

    assert by_gate[GateId.VOLUME.value]["tunable"] is True
    assert by_gate[GateId.BIAS.value]["tunable"] is True


def test_tally_ranks_the_starving_gate_first_and_counts_every_reason():
    """The 2026-07-15 CRUDE_OIL evening starvation, in miniature: the volume
    gate should stand out as the bottleneck without anyone reading prose."""
    decisions = [
        {
            "asset": "CRUDE_OIL",
            "timestamp": f"2026-07-15T{hour:02d}:00:00+00:00",
            "reasons": [f"VolumeEngine: THIN_TAPE: Volume ratio 0.3{hour}x < required 0.80x (trend entry)."],
        }
        for hour in range(10, 18)
    ] + [
        {
            "asset": "NIFTY",
            "timestamp": "2026-07-15T09:00:00+00:00",
            "reasons": ["Late-session cutoff (14:00 IST): no new entries into the close."],
        }
    ]

    result = tally_gate_rejections(decisions)

    assert result["top_gate"] == GateId.VOLUME.value
    assert result["total_rejections"] == 9
    assert result["decisions_analysed"] == 9
    assert result["unclassified_count"] == 0
    # Counts must sum to the total: no reason silently dropped.
    assert sum(g["count"] for g in result["gates"]) == result["total_rejections"]

    volume = next(g for g in result["gates"] if g["gate"] == GateId.VOLUME.value)
    assert volume["count"] == 8
    assert volume["share_pct"] == pytest.approx(88.9, abs=0.1)
    assert volume["assets"] == ["CRUDE_OIL"]
    # Samples keep the observed ratio, which is what a threshold call needs.
    assert any("0.80x" in s for s in volume["samples"])


def test_multi_reason_decision_counts_each_gate_once():
    result = tally_gate_rejections(
        [
            {
                "asset": "NIFTY",
                "timestamp": "2026-07-15T10:00:00+00:00",
                "reasons": [
                    "Bias engine: bullish entry against a BEARISH tape.",
                    "VolumeEngine: THIN_TAPE: Volume ratio 0.35x < required 0.80x (trend entry).",
                ],
            }
        ]
    )
    assert result["decisions_analysed"] == 1
    assert result["total_rejections"] == 2
    assert {g["gate"] for g in result["gates"]} == {GateId.BIAS.value, GateId.VOLUME.value}


class TestWindowing:
    def _decisions(self):
        now = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
        return now, [
            {
                "asset": "NIFTY",
                "timestamp": (now - timedelta(hours=1)).isoformat(),
                "reasons": ["Bias engine: bullish entry against a BEARISH tape."],
            },
            {
                "asset": "NIFTY",
                "timestamp": (now - timedelta(days=3)).isoformat(),
                "reasons": ["VolumeEngine: THIN_TAPE: Volume ratio 0.35x < required 0.80x (trend entry)."],
            },
        ]

    def test_since_excludes_older_decisions(self):
        now, decisions = self._decisions()
        result = tally_gate_rejections(decisions, since=now - timedelta(hours=6))
        assert result["total_rejections"] == 1
        assert result["top_gate"] == GateId.BIAS.value

    def test_no_window_counts_everything(self):
        _, decisions = self._decisions()
        assert tally_gate_rejections(decisions)["total_rejections"] == 2

    def test_unreadable_timestamp_is_skipped_when_a_window_is_requested(self):
        """An unknown time cannot be asserted to fall inside the window; count
        it only when the caller asked for all of history."""
        decisions = [{"asset": "NIFTY", "timestamp": "not-a-date", "reasons": ["Bias engine: MIXED."]}]
        windowed = tally_gate_rejections(decisions, since=datetime(2026, 1, 1, tzinfo=timezone.utc))
        assert windowed["total_rejections"] == 0
        assert tally_gate_rejections(decisions)["total_rejections"] == 1


def test_naive_timestamps_are_read_as_utc_not_dropped():
    decisions = [{"asset": "NIFTY", "timestamp": "2026-07-15T10:00:00", "reasons": ["Bias engine: MIXED."]}]
    result = tally_gate_rejections(decisions, since=datetime(2026, 7, 15, 9, 0, tzinfo=timezone.utc))
    assert result["total_rejections"] == 1


def test_empty_input_reports_nothing_rather_than_failing():
    result = tally_gate_rejections([])
    assert result == {
        "total_rejections": 0,
        "decisions_analysed": 0,
        "gates": [],
        "top_gate": None,
        "unclassified_count": 0,
    }
