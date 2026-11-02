"""Redact credentials already written to log files on disk.

`shared.utils.log_redaction` stops NEW lines from carrying a secret. It cannot
reach the ones already written: on 2026-11-02 that was 29 request_tokens
across 18 files, one per Zerodha login since the callback route was added.
This is the one-off that cleans them, and the tool to re-run after any future
leak is found.

HOW IT DECIDES WHAT IS SAFE TO TOUCH
A rewrite is truncate-then-write. A process appending to that same file keeps
its own byte offset, so rewriting a log Hokage currently holds open leaves a
hole of NUL bytes and loses whatever it wrote in between. So:

  * `--all` REFUSES to run while a Hokage process is alive. Both the live
    stderr log and the rotating hokage.log are open for the whole session.
  * Named paths are allowed, because the operator is asserting which files are
    historical - but a file modified in the last 15 minutes is still reported
    as a warning, since that is what an open log looks like.

Every file is backed up beside itself with a timestamp before it is rewritten,
and the rewrite is atomic (temp file, then replace), so an interrupted run
cannot leave a half-written log.

Dry run by default. Nothing is written without `--apply`.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from shared.utils.log_redaction import redact  # noqa: E402

#: Where Hokage's logs live: the launcher's per-session pair under the repo,
#: and the rotating handler's file in the brain.
_LOG_DIRS = (
    ROOT / "logs",
    Path(r"C:\Hokage\hokage_brain\logs"),
)

_FRESH = timedelta(minutes=15)


#: The ONE definition of "which processes are Hokage", dot-sourced rather than
#: reimplemented. His command line is `python.exe start.py` and contains the
#: word "hokage" nowhere, so a check that greps for it reports him DOWN while
#: he is serving - which is how this function was first written, and the
#: reason it is now a call into the canonical helper instead.
_PROCESS_HELPER = ROOT / "tools" / "ops" / "HokageProcess.ps1"


def hokage_is_running() -> bool:
    """True if Hokage holds the dashboard, via Get-HokageProcess.

    On any failure this answers YES. Being wrong in that direction costs a
    refusal the operator can override; being wrong the other way rewrites a
    log he is appending to.
    """
    try:
        out = subprocess.run(
            # -ExecutionPolicy Bypass: without it the dot-source is refused,
            # and PowerShell reports that on stderr while STILL EXITING 0 with
            # "0" on stdout. That parses as "Hokage is not running", which is
            # the one answer this function must never give by accident.
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
             f". '{_PROCESS_HELPER}'; @(Get-HokageProcess).Count"],
            capture_output=True, text=True, timeout=60,
        )
        stderr = (out.stderr or "").strip()
        if out.returncode != 0 or stderr:
            print(f"  liveness check could not answer: {stderr[:200]}; assuming YES")
            return True
        answer = (out.stdout or "").strip()
        if not answer.isdigit():
            print(f"  liveness check returned {answer!r}, which is not a count; assuming YES")
            return True
        return int(answer) > 0
    except Exception as exc:  # pragma: no cover - diagnostic path
        print(f"  could not determine whether Hokage is running ({exc}); assuming YES")
        return True


def collect(paths: list[str]) -> list[Path]:
    if paths:
        return [Path(p).resolve() for p in paths]
    found: list[Path] = []
    for d in _LOG_DIRS:
        if d.is_dir():
            found.extend(sorted(d.glob("*.log")))
    return found


def _write_atomically(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", errors="replace", newline="") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("paths", nargs="*", help="specific log files; default is every log")
    ap.add_argument("--all", action="store_true",
                    help="sweep every log file (refused while Hokage is running)")
    ap.add_argument("--apply", action="store_true", help="write the changes")
    args = ap.parse_args()

    if not args.paths and not args.all:
        ap.error("name the files, or pass --all")
    if args.all and hokage_is_running():
        print("REFUSED: Hokage is running, and he holds his stderr log and "
              "hokage.log open for the whole session. Rewriting a file being "
              "appended to loses the appends. Stop him, or name the "
              "historical files explicitly.")
        return 2

    now = datetime.now(timezone.utc)
    total_files = total_lines = 0
    backups_written: list[Path] = []

    for path in collect(args.paths):
        if not path.is_file():
            print(f"  missing: {path}")
            continue
        original = path.read_text(encoding="utf-8", errors="replace")
        cleaned = redact(original)
        if cleaned == original:
            continue

        changed = sum(1 for a, b in zip(original.splitlines(), cleaned.splitlines()) if a != b)
        total_files += 1
        total_lines += changed
        mtime = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        fresh = " [WARNING: modified in the last 15 min - is this log open?]" \
            if now - mtime < _FRESH else ""
        print(f"  {changed:>4} line(s)  {path}{fresh}")

        if args.apply:
            # A BACKUP OF A REDACTION STILL CONTAINS THE CREDENTIAL. So it
            # goes in one directory, not beside the log, and it does NOT end
            # in .log - a ".20261102_081500.bak.log" name is matched by the
            # tool's own sweep, so the first run left 19 plaintext copies in
            # the directory it had just cleaned and then counted them as
            # failures. Verify the rewrite, then delete these.
            vault = path.parent / "redaction_backups"
            vault.mkdir(exist_ok=True)
            stamp = now.astimezone().strftime("%Y%m%d_%H%M%S")
            (vault / f"{path.stem}.{stamp}.bak").write_text(
                original, encoding="utf-8", newline="")
            _write_atomically(path, cleaned)
            backups_written.append(vault / f"{path.stem}.{stamp}.bak")

    verb = "redacted" if args.apply else "would redact"
    print(f"\n{verb} {total_lines} line(s) across {total_files} file(s)")
    if not args.apply and total_files:
        print("dry run - nothing written. Re-run with --apply.")
    if backups_written:
        print(f"\n{len(backups_written)} backup(s) written to redaction_backups/ -- THESE STILL "
              f"HOLD THE CREDENTIAL IN PLAINTEXT.\nCheck the rewrite, then delete them:")
        print(f"  {backups_written[0].parent}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
