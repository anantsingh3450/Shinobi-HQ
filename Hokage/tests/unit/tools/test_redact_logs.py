"""The sweep that reported the logs clean while 23 tokens sat beside them.

2026-11-03. `redact_logs.py --all` was run with Hokage stopped, announced "6
line(s) across 2 file(s)", and the follow-up sweep then found 23 request_tokens
still on disk — in `hokage.log.1` through `hokage.log.5`. `collect()` globbed
`*.log`, and RotatingFileHandler does not name its rolled files that way. The
tool had been reporting a subset as the whole.

The same run exposed a second fault. Backups are named from `path.stem`, and
every rotation of `hokage.log.N` has the stem `hokage.log`, so with one
timestamp for the whole run all five backups wrote to ONE filename and four
were silently overwritten. Nothing warned; the vault simply held two files
where it should have held seven, and four rewrites became unverifiable.

Both faults are the same shape as the one this tool exists to fix: a name that
LOOKS like it covers everything and quietly covers less.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

_spec = importlib.util.spec_from_file_location(
    "redact_logs", ROOT / "tools" / "maintenance" / "redact_logs.py"
)
rl = importlib.util.module_from_spec(_spec)
sys.modules["redact_logs"] = rl
_spec.loader.exec_module(rl)


#: An INVENTED token: same shape as the real one, derived from nothing. A test
#: fixture must not be built out of the secret it tests for.
_TOKEN = "Kw8sNpR3vLx6QmZt1Hbc"
_LINE = (
    '127.0.0.1 - - [03/Nov/2026 14:17:10] "GET /api/v1/broker/zerodha/callback'
    f"?status=success&request_token={_TOKEN}&action=login"
    ' HTTP/1.1" 200 -'
)

#: Every rotation the handler leaves behind, plus the live file.
_ROTATIONS = (
    "hokage.log", "hokage.log.1", "hokage.log.2",
    "hokage.log.3", "hokage.log.4", "hokage.log.5",
)


@pytest.fixture()
def log_dir(tmp_path, monkeypatch):
    d = tmp_path / "logs"
    d.mkdir()
    for name in _ROTATIONS:
        (d / name).write_text(_LINE + "\nordinary line\n", encoding="utf-8")
    monkeypatch.setattr(rl, "_LOG_DIRS", (d,))
    return d


@pytest.fixture()
def swept(log_dir, monkeypatch):
    """A completed --apply run with Hokage down."""
    monkeypatch.setattr(rl, "hokage_is_running", lambda: False)
    monkeypatch.setattr(sys, "argv", ["redact_logs.py", "--all", "--apply"])
    assert rl.main() == 0
    return log_dir


# =========================================================================
# What the sweep can see
# =========================================================================

def test_collect_finds_the_rotations(log_dir):
    """THE BUG: "*.log" matched one file in six."""
    assert {p.name for p in rl.collect([])} == set(_ROTATIONS)


def test_collect_does_not_descend_into_the_backup_vault(log_dir):
    """A backup holds the credential in plaintext. If the sweep reached it the
    tool would rewrite its own evidence and count it as a finding."""
    vault = log_dir / "redaction_backups"
    vault.mkdir()
    (vault / "hokage_log_1.20261103_142757.bak").write_text(_LINE, encoding="utf-8")
    assert all(p.parent == log_dir for p in rl.collect([]))


def test_named_paths_still_win_over_the_glob(log_dir):
    only = rl.collect([str(log_dir / "hokage.log.3")])
    assert [p.name for p in only] == ["hokage.log.3"]


# =========================================================================
# What the rewrite does
# =========================================================================

def test_every_rotation_is_cleaned(swept):
    for p in sorted(swept.glob("hokage.log*")):
        text = p.read_text(encoding="utf-8")
        assert _TOKEN not in text, f"{p.name} still holds the token"
        assert "request_token=<REDACTED>" in text


def test_the_rewrite_preserves_every_line(swept):
    """A truncate-then-write that loses a line would be invisible in a count of
    redactions, so the shape of the file is asserted separately."""
    for p in sorted(swept.glob("hokage.log*")):
        lines = p.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2, f"{p.name} lost or gained a line"
        assert lines[1] == "ordinary line"


def test_a_dry_run_writes_nothing(log_dir, monkeypatch):
    monkeypatch.setattr(rl, "hokage_is_running", lambda: False)
    monkeypatch.setattr(sys, "argv", ["redact_logs.py", "--all"])
    assert rl.main() == 0
    assert _TOKEN in (log_dir / "hokage.log.3").read_text(encoding="utf-8")
    assert not (log_dir / "redaction_backups").exists()


# =========================================================================
# The backups
# =========================================================================

def test_each_rotation_gets_its_own_backup(swept):
    """THE SECOND BUG: all six share the stem "hokage.log", so names built from
    the stem collided and four backups were lost inside one run."""
    backups = sorted((swept / "redaction_backups").glob("*.bak"))
    assert len(backups) == len(_ROTATIONS), [b.name for b in backups]
    assert len({b.name for b in backups}) == len(_ROTATIONS)


def test_a_backup_is_never_matched_by_the_sweep(swept):
    """The glob is "*.log*" now, so a backup must carry no ".log" in its name
    at all — the 2026-11-02 run named them "*.bak.log" and left 19 plaintext
    copies in the directory it had just cleaned."""
    for b in (swept / "redaction_backups").glob("*.bak"):
        assert ".log" not in b.name, b.name


def test_the_backup_holds_the_original_untouched(swept):
    bak = next((swept / "redaction_backups").glob("hokage_log_3*.bak"))
    assert _TOKEN in bak.read_text(encoding="utf-8")


def test_the_summary_names_every_vault(log_dir, tmp_path, monkeypatch, capsys):
    """Printing backups_written[0].parent named one of the two directories the
    logs live in, and the other's plaintext copies went unmentioned."""
    second = tmp_path / "brain_logs"
    second.mkdir()
    (second / "hokage.log").write_text(_LINE + "\n", encoding="utf-8")
    monkeypatch.setattr(rl, "_LOG_DIRS", (log_dir, second))
    monkeypatch.setattr(rl, "hokage_is_running", lambda: False)
    monkeypatch.setattr(sys, "argv", ["redact_logs.py", "--all", "--apply"])
    assert rl.main() == 0
    out = capsys.readouterr().out
    assert str(log_dir / "redaction_backups") in out
    assert str(second / "redaction_backups") in out


# =========================================================================
# The refusal
# =========================================================================

def test_all_is_refused_while_hokage_runs(log_dir, monkeypatch, capsys):
    """A rewrite is truncate-then-write and an appending process keeps its own
    byte offset, so the appends in between become NULs."""
    monkeypatch.setattr(rl, "hokage_is_running", lambda: True)
    monkeypatch.setattr(sys, "argv", ["redact_logs.py", "--all", "--apply"])
    assert rl.main() == 2
    assert "REFUSED" in capsys.readouterr().out
    assert _TOKEN in (log_dir / "hokage.log").read_text(encoding="utf-8")


def test_a_failed_liveness_check_counts_as_running(monkeypatch):
    """PowerShell exits 0 and prints "0" when the dot-source is refused by the
    execution policy. Anything short of a clean integer must assume YES."""
    class _Out:
        returncode = 0
        stdout = "0"
        stderr = "cannot be loaded because running scripts is disabled"

    monkeypatch.setattr(rl.subprocess, "run", lambda *a, **k: _Out())
    assert rl.hokage_is_running() is True


def test_a_clean_zero_means_he_is_down(monkeypatch):
    class _Out:
        returncode = 0
        stdout = "0\n"
        stderr = ""

    monkeypatch.setattr(rl.subprocess, "run", lambda *a, **k: _Out())
    assert rl.hokage_is_running() is False
