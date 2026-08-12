"""Keep the host awake while Hokage is trading.

WHY THIS EXISTS
On 2026-08-12 the machine slept twice mid-session and the trading loop recorded
both as gaps:

    13:49 IST sleep -> 14:49 wake   (62-minute loop gap, 1 position unmanaged)
    19:51 IST sleep -> 20:24 wake   (35-minute loop gap)

Neither was a crash, a battery event or a network fault. The Windows System log
puts the bot's uptime before each at 5h08m and 5h02m, against a STANDBYIDLE
setting of 18000 seconds — the idle timer, firing exactly on schedule. Hokage
runs headless, so from Windows' point of view nobody had touched the machine
for five hours and it did the correct thing.

A suspended host is not a paused bot. Stops do not fire, targets do not fire,
and an open position rides the whole gap unmanaged. On 2026-08-12 the
NATURALGAS PE sat through the entire 62-minute suspension. An earlier sleep
(recorded in memory) ran 7.5 hours.

WHY NOT JUST CHANGE THE POWER PLAN
Editing the user's global settings would keep the laptop awake forever, long
after Hokage exits, which is a battery decision that is not ours to make.
SetThreadExecutionState is scoped to this process: Windows stops counting idle
time while Hokage holds the request, and the moment he exits — cleanly or not —
the request dies with the process and normal power behaviour returns.

WHAT IT DOES NOT COVER
ES_SYSTEM_REQUIRED suppresses the IDLE timer only. It cannot stop a lid close,
a critical-battery suspend, or a deliberate Sleep from the Start menu. The
display is deliberately left free to sleep (ES_DISPLAY_REQUIRED is NOT set) —
a dark screen costs nothing and the point is to keep the CPU scheduling the
trading loop, not to burn the panel.
"""
from __future__ import annotations

import logging
import sys

logger = logging.getLogger("Hokage.Power")

#: Informs the system the state being set should remain in effect until the
#: next call that uses ES_CONTINUOUS and one of the state flags is cleared.
_ES_CONTINUOUS = 0x80000000
#: Forces the system to be in the working state by resetting the system idle
#: timer. Display is intentionally not included.
_ES_SYSTEM_REQUIRED = 0x00000001

_held = False


def _set_state(flags: int) -> bool:
    """Call SetThreadExecutionState. Returns True when Windows accepted it.

    The API is per-THREAD and the state dies with the thread that set it, so
    callers must re-assert from a thread that lives as long as the trading
    loop. Re-asserting is idempotent and costs a single syscall.
    """
    if not sys.platform.startswith("win"):
        return False
    try:
        import ctypes

        result = ctypes.windll.kernel32.SetThreadExecutionState(flags)
    except Exception as exc:  # pragma: no cover - platform specific
        logger.debug(f"SetThreadExecutionState unavailable: {exc}")
        return False
    # Returns the PREVIOUS state, or 0 on failure.
    return result != 0


def hold_system_awake(announce: bool = False) -> bool:
    """Ask Windows not to idle-sleep the host. Safe to call every loop.

    `announce` logs at INFO the first time it succeeds, so the session log
    records that the guard is actually in force rather than silently absent.
    """
    global _held
    ok = _set_state(_ES_CONTINUOUS | _ES_SYSTEM_REQUIRED)
    if ok and not _held:
        _held = True
        if announce:
            logger.info(
                "Host sleep guard ON — Windows will not idle-suspend this machine "
                "while Hokage is running. Lid close and critical battery are NOT "
                "covered; keep the laptop open and plugged in."
            )
    elif not ok and _held:
        _held = False
        logger.warning(
            "Host sleep guard was REFUSED by Windows. The machine can idle-suspend "
            "mid-session and open positions would ride the gap unmanaged."
        )
    return ok


def release_system_awake() -> None:
    """Return the host to normal power behaviour. Called on clean shutdown;
    an unclean exit achieves the same thing by ending the process."""
    global _held
    if _held:
        _set_state(_ES_CONTINUOUS)
        _held = False
        logger.info("Host sleep guard released — normal power behaviour restored.")


def is_holding() -> bool:
    """True when this process currently holds the wake request."""
    return _held
