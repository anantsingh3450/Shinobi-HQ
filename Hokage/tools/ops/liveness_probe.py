"""Notice when Hokage stops trading. From OUTSIDE Hokage.

2026-08-27, 07:44. Hokage had been dead since 04:14 — three hours and thirty-nine
minutes — and the last thing he ever said was:

    04:14:36 [INFO] Watchdog: Overall Health Score: 100.0/100.

No traceback, no shutdown line, no alert. His own watchdog cannot report that he
is gone, for the obvious reason: it dies with him. And on the same morning the
Zerodha token had expired, so even a living Hokage would have been scanning a
market he could not see.

THIS IS THE THIRD TIME THIS CLASS OF FAILURE HAS COST A SESSION:
    July      nine days scanning against a dead token, zero trades, zero alerts
    2026-08-2x a critical-battery sleep suspended him 7.5h with a position open
    2026-08-27 dead process, 3h39m, health score 100/100 to the last line

Every one was invisible while it happened and obvious afterwards. Today is a
Thursday, which for natural gas means the week's only scheduled event lands at
20:00 IST — a silent death at 19:00 would cost the whole week and nothing would
say so.

TWO WAYS TO BE NOT-TRADING, and this checks both:
    the process is gone          -> the dashboard does not answer
    the process is blind         -> the broker session is expired

A living process with a dead token is the more dangerous of the two, because
every dashboard is green and every log line says INFO.

WHY IT ALARMS THE WAY IT DOES
  * THREE consecutive bad checks, never one. A single missed poll during a
    restart is normal; alarming on it produced a false "Hokage is dead" report
    on 2026-08-24 that cost real trust in the alert.
  * ONLY during MCX hours. An alarm at 03:00 for a bot that is supposed to be
    off is noise, and noise is how a real alarm gets ignored — the same
    reasoning that put CRUDEOIL in PARKED_ASSETS instead of letting the orphan
    audit scream every boot.
  * ONCE PER OUTAGE. It re-arms only after a recovery, so a four-hour outage is
    one message, not sixteen.
  * IT NEVER RESTARTS HIM. Reviving a bot that is crash-looping would turn one
    outage into a hundred, and a bot the commander stopped on purpose must stay
    stopped. This reports; the human decides.

The decision is a pure function of (clock, reachability, session state, previous
state) so it can be tested without a market, a broker, or a dead Hokage.
"""
from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]

STATE_PATH = ROOT / "hokage_brain" / "state" / "liveness.json"
DASHBOARD = "http://127.0.0.1:5000/"

#: MCX runs 09:00-23:30 IST. Outside it, silence is correct behaviour.
MARKET_OPEN = time(9, 0)
MARKET_CLOSE = time(23, 30)

#: Consecutive bad checks before anything is said.
STRIKES = 3

#: Seconds to wait for the dashboard. Generous: a busy scan can block the
#: Flask thread briefly, and calling that "dead" is the false alarm again.
TIMEOUT = 12


@dataclass
class State:
    strikes: int = 0
    alerted: bool = False
    last_reason: str = ""
    history: list = field(default_factory=list)

    @classmethod
    def load(cls, path: Path = STATE_PATH) -> "State":
        try:
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            return cls()
        return cls(strikes=int(raw.get("strikes", 0)),
                   alerted=bool(raw.get("alerted", False)),
                   last_reason=str(raw.get("last_reason", "")),
                   history=list(raw.get("history", []))[-50:])

    def save(self, path: Path = STATE_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "strikes": self.strikes, "alerted": self.alerted,
            "last_reason": self.last_reason, "history": self.history[-50:],
        }, indent=2), encoding="utf-8")


def in_market_hours(now: datetime) -> bool:
    """MCX trades Monday to Friday. A weekend silence is not an outage."""
    if now.weekday() >= 5:
        return False
    return MARKET_OPEN <= now.time() < MARKET_CLOSE


def assess(now: datetime, reachable: bool, session: str, state: State) -> tuple[str, State]:
    """(message to send, new state). Empty message means stay quiet.

    `session` is check_broker_session's verdict: LIVE..., EXPIRED,
    NO_CREDENTIALS, or UNKNOWN when the check itself could not run.
    """
    healthy = reachable and session.startswith("LIVE")

    if healthy:
        recovered = state.alerted
        state.strikes = 0
        state.alerted = False
        state.last_reason = ""
        if recovered:
            state.history.append({"at": now.isoformat(), "event": "recovered"})
            return ("Hokage is back. Dashboard answering and the broker session "
                    "is live."), state
        return "", state

    if not in_market_hours(now):
        # Do not accumulate strikes overnight; the first in-hours check should
        # start from zero rather than alarming instantly at 09:00.
        state.strikes = 0
        return "", state

    if not reachable:
        reason = "the dashboard is not answering on port 5000 — the process is gone"
    elif session == "EXPIRED":
        reason = ("the process is UP but the Zerodha session has EXPIRED — he is "
                  "scanning a market he cannot see")
    elif session == "NO_CREDENTIALS":
        reason = "the process is up but no broker credentials are configured"
    else:
        reason = f"the broker session check could not run ({session})"

    state.strikes += 1
    state.last_reason = reason
    if state.strikes < STRIKES or state.alerted:
        return "", state

    state.alerted = True
    state.history.append({"at": now.isoformat(), "event": "outage", "reason": reason})
    return (
        f"HOKAGE IS NOT TRADING.\n\n{reason}.\n\n"
        f"Checked {STRIKES} times running from {now.strftime('%H:%M')} back. "
        f"He will not trade, and he will not tell you himself — his own watchdog "
        f"dies with him.\n\n"
        f"Restart:  powershell -File \"{ROOT}\\Start-Hokage.ps1\""
    ), state


# ------------------------------------------------------------------- probes
def dashboard_answers(url: str = DASHBOARD, timeout: int = TIMEOUT) -> bool:
    try:
        with urlopen(url, timeout=timeout) as resp:
            return 200 <= resp.status < 500
    except URLError:
        return False
    except Exception:
        return False


def broker_session() -> str:
    """LIVE.../EXPIRED/NO_CREDENTIALS, or UNKNOWN if the check cannot run.

    Delegates to tools/check_broker_session.py, which does a real profile()
    round trip and never prints a token or any other credential.
    """
    try:
        out = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "check_broker_session.py")],
            capture_output=True, text=True, timeout=60,
        )
        verdict = (out.stdout or "").strip().splitlines()
        return verdict[-1].strip() if verdict else "UNKNOWN"
    except Exception:
        return "UNKNOWN"


def send(message: str) -> bool:
    try:
        sys.path.insert(0, str(ROOT / "src"))
        from integrations.notifications.telegram_bot import TelegramBotUplink

        bot = TelegramBotUplink()
        if not bot.enabled:
            return False
        bot.send_message(message)
        return True
    except Exception as exc:
        print(f"telegram failed: {exc}")
        return False


def main() -> int:
    now = datetime.now()
    state = State.load()
    reachable = dashboard_answers()
    session = broker_session() if reachable else "UNKNOWN"

    message, state = assess(now, reachable, session, state)
    state.save()

    status = "OK" if (reachable and session.startswith("LIVE")) else "BAD"
    print(f"{now:%Y-%m-%d %H:%M:%S}  dashboard={'up' if reachable else 'down'}  "
          f"session={session}  strikes={state.strikes}  -> {status}")

    if message:
        print(message)
        print("telegram: sent" if send(message) else "telegram: NOT sent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
