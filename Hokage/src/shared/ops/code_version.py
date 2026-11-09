"""Which commit is this process actually running, and has the repo moved since?

2026-11-08/09. Hokage ran for 44 hours on code from 2026-11-07 13:16, through
a Sunday with a live Muhurat session whose calendar fix was sitting unloaded on
disk. The commander said "restarted him" three times. Each time the process was
the same one, because `Start-ScheduledTask` will not replace a live process and
returns 0 - the stop is the load-bearing step, and it had never run.

NOTHING IN THE SYSTEM REPORTED THE GAP. Every panel read healthy, because every
panel asks the running process how it is, and a stale process is perfectly
healthy. The question nobody could ask was "is this the code we shipped?"

So: the commit on disk at BOOT is the commit the process is running, because
boot is when the files were read. Compare it later against the repo's HEAD and
the difference is the restart you have not done yet.

WHY THIS IS NOT AN ALARM ON ITS OWN. HEAD moves whenever anything is committed,
which is routine and not a fault. The line says RESTART PENDING, not FAILURE -
the point is to make an invisible state visible, not to shout.

READ FROM .git DIRECTLY, no subprocess. This is called at boot and once a day
from inside the trading loop; spawning git there is a dependency on git being
installed, on PATH, and on a shell, for a value that is four files away. A
missing or unreadable .git returns None, and None is never reported as stale.

A PROCESS GLOBAL CANNOT ANSWER ACROSS A PROCESS BOUNDARY. `_BOOT_COMMIT` is
set at boot inside the trading loop, so only the bot itself could ever read it.
Every other caller - the 06:30 morning brief, which runs as its own scheduled
task - got None and printed "code version unknown (no readable .git)" while
the repository read perfectly. The one panel placed to tell the commander a
restart was pending was structurally unable to know, and it blamed the
repository for it. Added 2026-11-09: boot also writes the commit and the pid
to the brain, so another process can ask who is actually running.

THE RECORD IS ONLY TRUE WHILE THE PID IS ALIVE. A file saying "running
b94505c" outlives the process that wrote it, and read naively it would report
a dead bot's version as current - the same class of mistake as the cached
CONNECTED flag that claimed a live broker session for thirteen minutes after
the token died. So the pid is checked, and its start time is checked against
the recorded boot, because pids are reused.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger("Hokage.CodeVersion")

#: The commit this process booted on. Set once, by record_boot().
_BOOT_COMMIT: str | None = None

#: Where a booted process leaves its version for others to read.
BOOT_RECORD_NAME = "running_version.json"

#: A pid's start time must match the recorded boot to this many seconds. Wide
#: enough to absorb the gap between the process starting and the trading loop
#: reaching record_boot(); narrow enough that a recycled pid will not match.
PID_START_TOLERANCE_SEC = 600.0


def _record_path() -> Path | None:
    """The brain file, or None if the brain cannot be located.

    Imported lazily and guarded: this module is deliberately free of
    dependencies so it can be read at boot before anything else is up, and a
    version probe must never be the thing that stops the bot starting.
    """
    try:
        from hokage.memory.resolver import brain_root

        return Path(brain_root()) / BOOT_RECORD_NAME
    except Exception as exc:
        logger.debug("No brain root for the version record: %s", exc)
        return None


def _write_boot_record(commit: str | None) -> None:
    path = _record_path()
    if path is None or not commit:
        return
    try:
        import datetime as dt

        pid = os.getpid()
        started = None
        try:
            import psutil

            started = psutil.Process(pid).create_time()
        except Exception:
            pass
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "commit": commit,
            "pid": pid,
            "pid_started_at": started,
            "recorded_at": dt.datetime.now().astimezone().isoformat(),
        }, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.debug("Could not write the version record: %s", exc)


def _pid_is_alive(pid: int, started_at: float | None) -> bool | None:
    """True, False, or None for "cannot tell".

    None is not False. A probe that cannot see the process table must not
    report the bot as gone, exactly as an unreadable calendar does not make a
    day a holiday.
    """
    try:
        import psutil
    except Exception:
        return None
    try:
        proc = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return False
    except Exception:
        return None
    try:
        if started_at is not None:
            if abs(proc.create_time() - float(started_at)) > PID_START_TOLERANCE_SEC:
                return False          # the pid was reused by something else
    except Exception:
        return None
    return True


def running_version() -> dict | None:
    """What the live bot is running, from its own boot record, or None.

    None means "cannot say": no record, an unreadable one, or a pid that is
    gone. Never a guess.
    """
    path = _record_path()
    if path is None or not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        logger.debug("Unreadable version record: %s", exc)
        return None
    commit = data.get("commit")
    pid = data.get("pid")
    if not commit or not isinstance(pid, int):
        return None
    alive = _pid_is_alive(pid, data.get("pid_started_at"))
    if alive is False:
        return None
    return {"commit": commit, "pid": pid, "pid_confirmed": alive is True,
            "recorded_at": data.get("recorded_at")}


def repo_root(start: Path | None = None) -> Path | None:
    """The working tree containing this file, or None."""
    here = (start or Path(__file__)).resolve()
    for parent in [here, *here.parents]:
        if (parent / ".git").exists():
            return parent
    return None


def _read_ref(git_dir: Path, ref: str) -> str | None:
    """Resolve a ref to a sha, loose file first, then packed-refs."""
    loose = git_dir / ref
    if loose.is_file():
        value = loose.read_text(encoding="utf-8").strip()
        return value or None
    packed = git_dir / "packed-refs"
    if packed.is_file():
        for line in packed.read_text(encoding="utf-8").splitlines():
            if line.startswith("#") or not line.strip():
                continue
            parts = line.split()
            if len(parts) == 2 and parts[1] == ref:
                return parts[0]
    return None


def head_commit(root: Path | None = None) -> str | None:
    """The sha HEAD currently points at, or None if it cannot be read.

    None means "cannot say" and must never be treated as a mismatch: a
    deployment without a .git directory is a normal way to run, not a stale
    process.
    """
    try:
        root = root or repo_root()
        if root is None:
            return None
        git_dir = root / ".git"
        if git_dir.is_file():
            # A worktree or submodule: .git is a file pointing elsewhere.
            pointer = git_dir.read_text(encoding="utf-8").strip()
            if pointer.startswith("gitdir:"):
                git_dir = Path(pointer.split(":", 1)[1].strip())
                if not git_dir.is_absolute():
                    git_dir = (root / git_dir).resolve()
        head = (git_dir / "HEAD")
        if not head.is_file():
            return None
        value = head.read_text(encoding="utf-8").strip()
        if value.startswith("ref:"):
            return _read_ref(git_dir, value.split(":", 1)[1].strip())
        return value or None
    except Exception as exc:
        logger.debug("Could not read HEAD: %s", exc)
        return None


def record_boot(root: Path | None = None, publish: bool = False) -> str | None:
    """Remember the commit on disk right now. Called once, at boot.

    Idempotent on purpose: a second call must not overwrite the first with a
    commit made while the process was already running, which is exactly the
    value this exists to detect.

    `publish` WRITES THE SHARED RECORD, AND DEFAULTS TO OFF. Writing it is a
    claim to be the running bot, so only the bot may make it. The first
    version of this published unconditionally, and within one test run the
    suite had written a fake sha and a pytest pid into the live brain at
    C:\\Hokage\\hokage_brain - then a later test in the same file read it back
    and failed. Any tool that imported this module and recorded a boot would
    have done the same to the real bot's record in production.
    """
    global _BOOT_COMMIT
    if _BOOT_COMMIT is None:
        _BOOT_COMMIT = head_commit(root)
        if publish:
            _write_boot_record(_BOOT_COMMIT)
    return _BOOT_COMMIT


def boot_commit() -> str | None:
    return _BOOT_COMMIT


def short(sha: str | None) -> str:
    return sha[:7] if sha else "unknown"


def staleness(root: Path | None = None) -> tuple[bool, str | None, str | None]:
    """(is_behind, boot_commit, head_now).

    `is_behind` is True ONLY when both shas are known and they differ. Unknown
    is not stale, for the same reason an unknown calendar date is not a
    holiday: the honest answer to "cannot say" is to change nothing.

    IN-PROCESS FIRST, THEN THE LIVE BOT'S RECORD. Inside the bot, the process
    global is the authority - it is the commit whose files were actually read.
    Anywhere else it is None, and the question being asked is about the bot
    rather than about the asker, so the persisted record answers instead. That
    fallback is what lets the morning brief say RESTART PENDING at all; before
    it, `behind` was False in that process no matter what the repo had done.
    """
    booted = _BOOT_COMMIT
    if booted is None:
        live = running_version()
        if live is not None:
            booted = live["commit"]
    now = head_commit(root)
    if not booted or not now:
        return False, booted, now
    return booted != now, booted, now


def describe(root: Path | None = None) -> str:
    """One line for a log or the morning checklist.

    THE TWO UNKNOWNS ARE DIFFERENT AND USED TO READ THE SAME. "No boot was
    recorded" and "the repository cannot be read" both produced "no readable
    .git", which sent a reader to check the repository when the repository was
    fine. `_BOOT_COMMIT` is a process global, so every tool and test that
    imports this module without booting Hokage hits the first case - and it
    was reported as the second.

    A diagnostic that misstates why it cannot answer is worse than one that
    says nothing, because it spends the next reader's attention on the wrong
    thing. Both cases still mean "cannot say", and cannot-say is never stale.
    """
    behind, booted, now = staleness(root)
    if booted is None and now is None:
        return "code version unknown (no readable .git)"
    if booted is None:
        return (f"repo HEAD is {short(now)}; no running bot recorded its "
                f"version, so what it loaded cannot be said")
    if behind:
        return (f"running {short(booted)}, repo HEAD is {short(now)} - "
                f"RESTART PENDING to load it")
    if now is None:
        return f"running {short(booted)} (repo HEAD unreadable now)"
    return f"running {short(booted)} (current)"
