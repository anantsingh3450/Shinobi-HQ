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
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger("Hokage.CodeVersion")

#: The commit this process booted on. Set once, by record_boot().
_BOOT_COMMIT: str | None = None


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


def record_boot(root: Path | None = None) -> str | None:
    """Remember the commit on disk right now. Called once, at boot.

    Idempotent on purpose: a second call must not overwrite the first with a
    commit made while the process was already running, which is exactly the
    value this exists to detect.
    """
    global _BOOT_COMMIT
    if _BOOT_COMMIT is None:
        _BOOT_COMMIT = head_commit(root)
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
    """
    booted = _BOOT_COMMIT
    now = head_commit(root)
    if not booted or not now:
        return False, booted, now
    return booted != now, booted, now


def describe(root: Path | None = None) -> str:
    """One line for a log or the morning checklist."""
    behind, booted, now = staleness(root)
    if booted is None:
        return "code version unknown (no readable .git)"
    if behind:
        return (f"running {short(booted)}, repo HEAD is {short(now)} - "
                f"RESTART PENDING to load it")
    if now is None:
        return f"running {short(booted)} (repo HEAD unreadable now)"
    return f"running {short(booted)} (current)"
