"""Which gate is actually starving the tape?

Every no-trade decision carries free-text reasons. Read one at a time on a
dashboard they say nothing about *systematic* starvation: the 0.80x volume bar
that blocked CRUDE_OIL all evening on 2026-07-15 was only caught because the
commander happened to read a screenshot. This module turns that pile of prose
into a per-gate tally so the bottleneck is measured instead of noticed.

Two rules drive the design:

1. **Classification is exhaustive.** An unrecognised reason lands in
   ``UNCLASSIFIED`` and is reported with its raw text — never dropped, never
   guessed into a neighbouring bucket. A silently discarded reason would
   under-count the very gate we are hunting.
2. **Safety gates are labelled, not just counted.** A gate that exists to
   protect capital (liquidity traps, rich premium, cash, war chest) must never
   be "tuned" because a tally says it blocks a lot — blocking is its job. The
   ``tunable`` flag keeps that distinction in the data rather than in whoever
   is reading it.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Iterable, Mapping


class GateId(StrEnum):
    """Canonical identity of each pre-trade gate that can refuse an entry."""

    DAY_ISOLATOR = "DAY_ISOLATOR"
    OBSERVATION_WINDOW = "OBSERVATION_WINDOW"
    RISK_OFF = "RISK_OFF"
    CAPITAL_PRESERVATION = "CAPITAL_PRESERVATION"
    CASH = "CASH"
    SESSION_BEHAVIOR = "SESSION_BEHAVIOR"
    SESSION_TIME = "SESSION_TIME"
    VOLUME = "VOLUME"
    LIQUIDITY = "LIQUIDITY"
    BIAS = "BIAS"
    IV_PREMIUM = "IV_PREMIUM"
    ENTRY_SIGNAL = "ENTRY_SIGNAL"
    OPTIONS_ROUTING = "OPTIONS_ROUTING"
    WAR_CHEST = "WAR_CHEST"
    COMMITTEE = "COMMITTEE"
    ALLOCATION_ZERO = "ALLOCATION_ZERO"
    REENTRY_COOLDOWN = "REENTRY_COOLDOWN"
    REENTRY_CAP = "REENTRY_CAP"
    CORRELATION_CAP = "CORRELATION_CAP"
    REENTRY_WATERMARK = "REENTRY_WATERMARK"
    SCAN_PIPELINE = "SCAN_PIPELINE"
    UNCLASSIFIED = "UNCLASSIFIED"


class GateKind(StrEnum):
    """Why a gate exists — decides whether it may ever be loosened.

    SAFETY: protects capital. Blocking is the feature. Never tune to raise
        trade count; a high tally here is information about the market, not a
        defect in the gate.
    QUALITY: filters setup quality. Legitimately tunable against evidence when
        a tally shows it is starving a strategy it was never meant to bind.
    INFRA: something upstream failed (no contract, no quote). Neither a safety
        rule nor a preference — a bug signal.
    """

    SAFETY = "SAFETY"
    QUALITY = "QUALITY"
    INFRA = "INFRA"


#: Ordered (substring, gate) rules. Order matters: the first match wins, so
#: specific phrases must precede generic ones. Substrings are matched against
#: the reason text case-insensitively.
_RULES: tuple[tuple[str, GateId], ...] = (
    ("day-of-week isolator", GateId.DAY_ISOLATOR),
    ("opening bell observation", GateId.OBSERVATION_WINDOW),
    ("risk-off", GateId.RISK_OFF),
    ("capital preservation mode is no trade", GateId.CAPITAL_PRESERVATION),
    ("insufficient account cash", GateId.CASH),
    ("sessionbehaviorengine", GateId.SESSION_BEHAVIOR),
    ("midday chop blackout", GateId.SESSION_TIME),
    ("late-session cutoff", GateId.SESSION_TIME),
    ("volumeengine", GateId.VOLUME),
    ("thin_tape", GateId.VOLUME),
    ("fake_breakout", GateId.VOLUME),
    ("liquidityengine", GateId.LIQUIDITY),
    ("liquidity_trap", GateId.LIQUIDITY),
    ("bias engine", GateId.BIAS),
    ("iv premium guard", GateId.IV_PREMIUM),
    ("entrysignal", GateId.ENTRY_SIGNAL),
    ("optionsrouter", GateId.OPTIONS_ROUTING),
    ("war chest exhausted", GateId.WAR_CHEST),
    ("allocation sized to 0%", GateId.ALLOCATION_ZERO),
    ("committee", GateId.COMMITTEE),
    ("re-entry cooldown", GateId.REENTRY_COOLDOWN),
    ("re-entry cap", GateId.REENTRY_CAP),
    ("correlationcap", GateId.CORRELATION_CAP),
    ("reentrywatermark", GateId.REENTRY_WATERMARK),
    ("scan pipeline error", GateId.SCAN_PIPELINE),
    # League stand-aside rows are journaled with the entry module's id as the
    # prefix ("entry-malfoy-momentum-v1: ..."); without this rule they tally
    # as UNCLASSIFIED/INFRA and look like bugs instead of judged stand-asides.
    # Must stay AFTER the re-entry rules ("re-entry ..." must not fall through
    # here) — order matters, first match wins.
    ("entry-", GateId.ENTRY_SIGNAL),
)

GATE_KINDS: Mapping[GateId, GateKind] = {
    GateId.DAY_ISOLATOR: GateKind.QUALITY,
    GateId.OBSERVATION_WINDOW: GateKind.QUALITY,
    GateId.RISK_OFF: GateKind.SAFETY,
    GateId.CAPITAL_PRESERVATION: GateKind.SAFETY,
    GateId.CASH: GateKind.SAFETY,
    GateId.SESSION_BEHAVIOR: GateKind.QUALITY,
    GateId.SESSION_TIME: GateKind.QUALITY,
    GateId.VOLUME: GateKind.QUALITY,
    GateId.LIQUIDITY: GateKind.SAFETY,
    GateId.BIAS: GateKind.QUALITY,
    GateId.IV_PREMIUM: GateKind.SAFETY,
    GateId.ENTRY_SIGNAL: GateKind.QUALITY,
    GateId.OPTIONS_ROUTING: GateKind.INFRA,
    GateId.WAR_CHEST: GateKind.SAFETY,
    GateId.COMMITTEE: GateKind.QUALITY,
    GateId.ALLOCATION_ZERO: GateKind.SAFETY,
    GateId.REENTRY_COOLDOWN: GateKind.QUALITY,
    GateId.REENTRY_CAP: GateKind.QUALITY,
    GateId.CORRELATION_CAP: GateKind.SAFETY,
    GateId.REENTRY_WATERMARK: GateKind.QUALITY,
    GateId.SCAN_PIPELINE: GateKind.INFRA,
    GateId.UNCLASSIFIED: GateKind.INFRA,
}

#: Plain-language description, so the dashboard can explain a tally without a
#: reader needing to know the codebase.
GATE_LABELS: Mapping[GateId, str] = {
    GateId.DAY_ISOLATOR: "Day-of-week sector isolator",
    GateId.OBSERVATION_WINDOW: "Opening bell observation (pre-09:30)",
    GateId.RISK_OFF: "Global RISK-OFF state",
    GateId.CAPITAL_PRESERVATION: "Capital preservation: NO TRADE",
    GateId.CASH: "Insufficient cash balance",
    GateId.SESSION_BEHAVIOR: "Session behaviour (setup vs session phase)",
    GateId.SESSION_TIME: "Time-of-day window (blackout / late cutoff)",
    GateId.VOLUME: "Volume confirmation",
    GateId.LIQUIDITY: "Liquidity trap (spread / book depth)",
    GateId.BIAS: "Underlying bias alignment",
    GateId.IV_PREMIUM: "IV premium guard (VIX percentile)",
    GateId.ENTRY_SIGNAL: "Entry modules stood aside (league)",
    GateId.OPTIONS_ROUTING: "Options contract routing failure",
    GateId.WAR_CHEST: "Strategy war chest exhausted",
    GateId.COMMITTEE: "Investment committee vote",
    GateId.ALLOCATION_ZERO: "Position sized to zero",
    GateId.REENTRY_COOLDOWN: "Post-exit re-entry cooldown",
    GateId.REENTRY_CAP: "Daily re-entry cap per symbol",
    GateId.CORRELATION_CAP: "Index-family same-direction cap (one macro bet, not three)",
    GateId.REENTRY_WATERMARK: "Post-win re-entry watermark (no buying our own dip)",
    GateId.SCAN_PIPELINE: "Scan pipeline error (research/backtest crash)",
    GateId.UNCLASSIFIED: "Unclassified reason",
}


def classify_reason(reason: str) -> GateId:
    """Map one free-text no-trade reason onto its canonical gate.

    Unrecognised text returns ``UNCLASSIFIED`` rather than a best guess — a
    wrong bucket would quietly corrupt the very tally used to decide which
    gate to tune.
    """
    if not reason:
        return GateId.UNCLASSIFIED
    text = reason.casefold()
    for needle, gate in _RULES:
        if needle in text:
            return gate
    return GateId.UNCLASSIFIED


@dataclass(frozen=True, slots=True)
class GateStat:
    """Rejection tally for a single gate over the analysed window."""

    gate: GateId
    label: str
    kind: GateKind
    count: int
    share_pct: float
    assets: tuple[str, ...]
    #: Verbatim samples, for gates whose threshold detail lives in the text
    #: (e.g. the observed volume ratio). Capped — this is a signal, not a log.
    samples: tuple[str, ...]

    @property
    def tunable(self) -> bool:
        """Only QUALITY gates may be loosened against evidence.

        SAFETY gates blocking often is them working; INFRA means fix the bug.
        """
        return self.kind is GateKind.QUALITY

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate": self.gate.value,
            "label": self.label,
            "kind": self.kind.value,
            "count": self.count,
            "share_pct": self.share_pct,
            "assets": list(self.assets),
            "samples": list(self.samples),
            "tunable": self.tunable,
        }


def _parse_ts(value: Any) -> datetime | None:
    """Best-effort ISO timestamp parse; unparseable means 'unknown', not now."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def tally_gate_rejections(
    decisions: Iterable[Mapping[str, Any]],
    since: datetime | None = None,
    max_samples: int = 3,
) -> dict[str, Any]:
    """Aggregate no-trade decisions into a per-gate rejection scoreboard.

    Args:
        decisions: no-trade records (``asset``, ``timestamp``, ``reasons``) as
            returned by the journal.
        since: only count decisions at or after this instant. Records with an
            unreadable timestamp are counted when no window is requested and
            skipped when one is — an unknown time cannot be claimed to fall
            inside a window.
        max_samples: verbatim reason samples retained per gate.

    Returns:
        ``{"total_rejections", "decisions_analysed", "gates": [...],
        "top_gate", "unclassified_count"}`` with gates ranked by count.
        Every reason lands in exactly one gate, so counts sum to the total.
    """
    counts: Counter[GateId] = Counter()
    assets: dict[GateId, set[str]] = {}
    samples: dict[GateId, list[str]] = {}
    analysed = 0

    for decision in decisions:
        when = _parse_ts(decision.get("timestamp"))
        if since is not None and (when is None or when < since):
            continue
        raw_reasons = decision.get("reasons") or []
        if isinstance(raw_reasons, str):
            raw_reasons = [raw_reasons]
        asset = str(decision.get("asset") or "UNKNOWN")
        analysed += 1

        for reason in raw_reasons:
            text = str(reason)
            gate = classify_reason(text)
            counts[gate] += 1
            assets.setdefault(gate, set()).add(asset)
            bucket = samples.setdefault(gate, [])
            if len(bucket) < max_samples and text not in bucket:
                bucket.append(text)

    total = sum(counts.values())
    stats = [
        GateStat(
            gate=gate,
            label=GATE_LABELS.get(gate, gate.value),
            kind=GATE_KINDS.get(gate, GateKind.INFRA),
            count=count,
            share_pct=round(count / total * 100.0, 1) if total else 0.0,
            assets=tuple(sorted(assets.get(gate, ()))),
            samples=tuple(samples.get(gate, ())),
        )
        for gate, count in counts.most_common()
    ]

    return {
        "total_rejections": total,
        "decisions_analysed": analysed,
        "gates": [s.to_dict() for s in stats],
        "top_gate": stats[0].gate.value if stats else None,
        "unclassified_count": counts.get(GateId.UNCLASSIFIED, 0),
    }
