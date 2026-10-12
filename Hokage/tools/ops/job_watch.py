"""Notice when Hokage stops LEARNING or stops EVOLVING.

2026-10-12, Monday morning. The weekly audit had been scheduled for Friday
23:45 and its task reported `LastTaskResult = 1`. It wrote no log, sent no
Telegram, and nothing anywhere said a word. The only reason a 2026-10-09
snapshot exists at all is that the audit was run by hand earlier that evening;
without it the newest measurement would have been 2026-09-22, twenty days old,
and the commander would have found out whenever somebody next looked.

The liveness probe watches whether Hokage is ALIVE. Nothing watched whether he
was still learning anything. Those are different failures and the second one
is quieter: a bot that dies stops answering, a bot that stops learning keeps
answering perfectly while its evidence rots.

WHY THIS WATCHES OUTPUT, NOT THE SCHEDULER

`Get-ScheduledTaskInfo` reports the last run's exit code, which answers "did
the task run" and not "did the work happen". A task can exit 0 having skipped
everything, be renamed, be disabled, or sit on a machine that was switched off
for three weeks — all invisible. So this measures the artefacts instead:

    LEARNING   the newest candle in candles.db
    EVOLVING   the newest dated snapshot in research/snapshots/

Those are the things that must keep moving. If they are current, the pipeline
worked however it was invoked; if they are stale, it did not, whatever any
exit code claims.

WHY THE THRESHOLDS ARE GENEROUS

A watch that cries on a market holiday teaches the commander to ignore it, the
same reasoning that put CRUDEOIL in PARKED_ASSETS rather than letting the
orphan audit scream on every boot. India's exchange holidays fall on weekdays
and cluster around Diwali, so a two- or three-weekday gap in the tape can be
perfectly correct. The bar is set where no legitimate holiday run can reach it
and real breakage still shows up within one cycle.

Nothing here is allowed to be noisy, and nothing here is allowed to be silent.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

try:
    # The one answer to "where is the brain". Reads HOKAGE_BRAIN_ROOT from the
    # environment and, failing that, from .env — which matters because this is
    # launched by the scheduler, never through the bot's entry point.
    from hokage.memory.resolver import brain_root as _brain_root
except Exception:  # pragma: no cover - degraded, but still a watch
    def _brain_root() -> Path:
        configured = (os.environ.get("HOKAGE_BRAIN_ROOT") or "").strip()
        return Path(configured).resolve() if configured else ROOT / "hokage_brain"


BRAIN = _brain_root()
CANDLES_DB = BRAIN / "candles.db"
SNAPSHOT_DIR = BRAIN / "research" / "snapshots"
STATE_PATH = BRAIN / "state" / "job_watch.json"

#: Weekdays the candle tape may fall behind before this says anything.
#:
#: One missed weekday is an exchange holiday. Two is a long weekend holiday.
#: Four in a row has never been a holiday run on the Indian calendar, so at
#: that point the sync is genuinely broken — and four trading days of lost tape
#: is worth a message, because a futures roll deletes history that was never
#: captured and no later run can recover it.
MAX_CANDLE_WEEKDAYS_STALE = 4

#: Days the newest audit snapshot may age before this says anything.
#:
#: The audit runs weekly. Missing one run puts fourteen days between
#: snapshots, so a bar of ten catches a single miss within the following
#: cycle. Retirement evidence is "two consecutive audits agreeing", so a
#: silently skipped audit does not corrupt the clock — it stops it, which is
#: exactly as bad and much harder to see.
MAX_SNAPSHOT_DAYS_STALE = 10


@dataclass
class State:
    """Alarm once per episode, re-arm on recovery."""
    alerted: bool = False
    last_reason: str = ""

    @classmethod
    def load(cls, path: Path) -> "State":
        try:
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            # A corrupt state file must not stop the watch. Worst case it
            # repeats one message.
            return cls()
        return cls(alerted=bool(raw.get("alerted", False)),
                   last_reason=str(raw.get("last_reason", "")))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "alerted": self.alerted,
            "last_reason": self.last_reason,
            "checked_at": datetime.now().isoformat(timespec="seconds"),
        }, indent=2), encoding="utf-8")


def weekdays_between(start: date, end: date) -> int:
    """Mon-Fri days strictly after `start`, up to and including `end`.

    Calendar days would count a normal weekend as two days of breakage, which
    is how a watch starts crying every Monday.
    """
    if end <= start:
        return 0
    n = 0
    day = start + timedelta(days=1)
    while day <= end:
        if day.weekday() < 5:
            n += 1
        day += timedelta(days=1)
    return n


def newest_candle_date(db_path: Path) -> date | None:
    """The most recent candle in the archive, or None if it cannot be read.

    None means UNKNOWN, never "today". Returning a date here on failure would
    report a healthy archive for a database that does not open.
    """
    if not db_path.exists():
        return None
    try:
        # as_uri() so the Windows drive letter and backslashes survive; the
        # naive f"file:{path}" form builds a URI sqlite silently mishandles.
        # mode=ro because a watch must never be able to write to the thing it
        # is watching.
        conn = sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True)
        try:
            # The column is `ts`, not `date`. The first version of this queried
            # MAX(date), the query raised, and the function dutifully reported
            # UNREADABLE for an archive that opens perfectly well. Failing
            # closed saved it from claiming the archive was fresh, which is the
            # whole reason None means UNKNOWN here and never "today".
            row = conn.execute("SELECT MAX(ts) FROM candles").fetchone()
        finally:
            conn.close()
    except Exception:
        return None
    if not row or not row[0]:
        return None
    try:
        return datetime.fromisoformat(str(row[0])).date()
    except ValueError:
        try:
            return datetime.strptime(str(row[0])[:10], "%Y-%m-%d").date()
        except ValueError:
            return None


def newest_snapshot_date(snapshot_dir: Path) -> date | None:
    """The newest dated audit snapshot, by FILENAME not mtime.

    mtime moves when a file is copied, and the brain was copied wholesale to a
    new disk on 2026-10-09. The filename is the measurement date and does not
    lie about when the work happened.
    """
    if not snapshot_dir.is_dir():
        return None
    best: date | None = None
    for path in snapshot_dir.glob("*.json"):
        try:
            stamp = datetime.strptime(path.stem, "%Y-%m-%d").date()
        except ValueError:
            continue
        if best is None or stamp > best:
            best = stamp
    return best


def assess(today: date, candle_day: date | None,
           snapshot_day: date | None) -> list[str]:
    """Every complaint worth making, as plain sentences. Empty means healthy.

    A pure function of (clock, two dates), so it can be tested without a
    database, a scheduler, or three weeks of waiting.
    """
    problems: list[str] = []

    if candle_day is None:
        problems.append(
            "The candle archive cannot be read at all. Hokage measures "
            "everything against this tape; without it the labs and the weekly "
            f"audit have nothing to work from. Expected at {CANDLES_DB}."
        )
    else:
        stale = weekdays_between(candle_day, today)
        if stale > MAX_CANDLE_WEEKDAYS_STALE:
            problems.append(
                f"The candle archive has not grown in {stale} trading days — "
                f"newest candle is {candle_day:%Y-%m-%d}. He is not learning. "
                f"A futures roll deletes history that was never captured, and "
                f"no later run can recover it."
            )

    if snapshot_day is None:
        problems.append(
            "There are no audit snapshots at all, so nothing can be compared "
            "week to week and no strategy can ever be retired on evidence."
        )
    else:
        age = (today - snapshot_day).days
        if age > MAX_SNAPSHOT_DAYS_STALE:
            problems.append(
                f"The weekly audit has not produced a snapshot in {age} days — "
                f"newest is {snapshot_day:%Y-%m-%d}. He is not evolving. "
                f"Retirement needs two consecutive audits that agree, so a "
                f"skipped run does not just delay a decision, it stops the "
                f"clock that justifies one."
            )

    return problems


def _send(text: str) -> bool:
    try:
        from integrations.notifications.telegram_bot import TelegramBotUplink
    except Exception:
        return False
    try:
        return bool(TelegramBotUplink().send_message(text))
    except Exception:
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--report", action="store_true",
                    help="print the state and change nothing")
    ap.add_argument("--check", action="store_true",
                    help="alert on Telegram if stale; for the scheduler")
    args = ap.parse_args()
    if not args.report and not args.check:
        ap.print_help()
        return 1

    today = date.today()
    candle_day = newest_candle_date(CANDLES_DB)
    snapshot_day = newest_snapshot_date(SNAPSHOT_DIR)
    problems = assess(today, candle_day, snapshot_day)

    cs = f"{candle_day:%Y-%m-%d}" if candle_day else "UNREADABLE"
    ss = f"{snapshot_day:%Y-%m-%d}" if snapshot_day else "NONE"
    cd = weekdays_between(candle_day, today) if candle_day else "?"
    sd = (today - snapshot_day).days if snapshot_day else "?"

    print(f"{today:%Y-%m-%d}  brain={BRAIN}")
    print(f"  LEARNING  newest candle   {cs}  ({cd} trading days ago, "
          f"bar {MAX_CANDLE_WEEKDAYS_STALE})")
    print(f"  EVOLVING  newest snapshot {ss}  ({sd} days ago, "
          f"bar {MAX_SNAPSHOT_DAYS_STALE})")
    print(f"  -> {'OK' if not problems else 'STALE'}")
    for p in problems:
        print(f"     - {p}")

    if not args.check:
        return 0

    state = State.load(STATE_PATH)
    if problems:
        reason = " | ".join(problems)
        if not state.alerted or reason != state.last_reason:
            body = "\n\n".join(f"- {p}" for p in problems)
            _send(
                "HOKAGE IS NOT LEARNING\n\n" + body +
                "\n\nThis watches the work, not the scheduler: a task can exit "
                "0 having done nothing. Check the newest log under logs\\ and "
                "re-run the job by hand."
            )
            state.alerted = True
            state.last_reason = reason
    elif state.alerted:
        _send("Recovered: the candle archive and the audit snapshots are "
              "both current again.")
        state.alerted = False
        state.last_reason = ""

    state.save(STATE_PATH)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
