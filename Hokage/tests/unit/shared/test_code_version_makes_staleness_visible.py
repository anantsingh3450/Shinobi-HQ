"""Nothing could say which code was running, and that cost two days.

2026-11-08/09. Hokage ran 44 hours on the 2026-11-07 build, through a Sunday
with a live Muhurat session whose calendar fix sat unloaded on disk, while the
commander said "restarted him" three times. Each time the process was the same
one, because `Start-ScheduledTask` will not replace a live process and returns
0 - the stop is the load-bearing step, and it never ran.

NO PANEL COULD REPORT IT, and the reason is structural: every panel asks the
running process how it is, and a stale process is perfectly healthy. The
question nobody could ask was "is this the code we shipped?"

The commit on disk at BOOT is the commit the process runs, because boot is
when the files were read. Everything here follows from that one fact.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from shared.ops import code_version as cv  # noqa: E402

SHA_A = "a" * 40
SHA_B = "b" * 40


@pytest.fixture(autouse=True)
def _clean_boot(monkeypatch):
    """Each test gets its own notion of what the process booted on."""
    monkeypatch.setattr(cv, "_BOOT_COMMIT", None)


def _code_only(text: str) -> str:
    """Source with comments stripped.

    Every rail in this file checks CODE, not prose. Three rails earlier today
    failed because a docstring explaining a trap contained the very string the
    rail was looking for - and a rail that fires on its own explanation is a
    rail that gets deleted rather than fixed.
    """
    return chr(10).join(line.split(chr(35))[0] for line in text.splitlines())


def _fake_repo(tmp_path: Path, sha: str, *, packed: bool = False,
               branch: str = "main") -> Path:
    root = tmp_path / "repo"
    git = root / ".git"
    (git / "refs" / "heads").mkdir(parents=True)
    (git / "HEAD").write_text(f"ref: refs/heads/{branch}\n", encoding="utf-8")
    if packed:
        (git / "packed-refs").write_text(
            f"# pack-refs with: peeled fully-peeled sorted \n"
            f"{sha} refs/heads/{branch}\n", encoding="utf-8")
    else:
        (git / "refs" / "heads" / branch).write_text(sha + "\n", encoding="utf-8")
    return root


# ================================================ reading the commit on disk
def test_a_loose_ref_is_read(tmp_path):
    root = _fake_repo(tmp_path, SHA_A)
    assert cv.head_commit(root) == SHA_A


def test_a_packed_ref_is_read(tmp_path):
    """A repository that has been gc'd has no loose ref file. Returning None
    there would read as "cannot say" forever on a perfectly normal repo."""
    root = _fake_repo(tmp_path, SHA_B, packed=True)
    assert cv.head_commit(root) == SHA_B


def test_a_detached_head_is_read(tmp_path):
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    (root / ".git" / "HEAD").write_text(SHA_A + "\n", encoding="utf-8")
    assert cv.head_commit(root) == SHA_A


def test_no_git_directory_is_unknown_not_stale(tmp_path):
    """A deployment without .git is a normal way to run, not a stale one."""
    plain = tmp_path / "no-git"
    plain.mkdir()
    assert cv.head_commit(plain) is None


def test_it_reads_the_real_repo():
    """The one that matters. A reader that works only on fixtures is a
    reader that has never been tried."""
    assert cv.repo_root() is not None
    sha = cv.head_commit()
    assert sha and len(sha) == 40
    assert all(c in "0123456789abcdef" for c in sha)


def test_no_subprocess_is_spawned():
    """Called at boot and from inside the trading loop. Depending on git being
    installed, on PATH and reachable through a shell - for a value four files
    away - is a dependency bought for nothing.

    ASKED OF THE AST, not of the text. The module's own docstring explains
    that it spawns nothing, so a substring rail fires on the explanation. Two
    other rails in this file did exactly that an hour ago.
    """
    import ast

    tree = ast.parse((ROOT / "src" / "shared" / "ops" / "code_version.py")
                     .read_text(encoding="utf-8"))
    banned = {"subprocess", "popen", "system", "spawn", "run"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] != "subprocess", alias.name
        if isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".")[0] != "subprocess", node.module
        if isinstance(node, ast.Attribute):
            assert node.attr.lower() not in banned, node.attr
        if isinstance(node, ast.Name):
            assert node.id.lower() != "subprocess", node.id


# ===================================================== what boot remembers
def test_record_boot_is_idempotent(tmp_path, monkeypatch):
    """THE WHOLE POINT. A second call must not overwrite the boot commit with
    one made while the process was already running - that value is exactly
    what this exists to detect."""
    root = _fake_repo(tmp_path, SHA_A)
    assert cv.record_boot(root) == SHA_A

    (root / ".git" / "refs" / "heads" / "main").write_text(SHA_B, encoding="utf-8")
    assert cv.record_boot(root) == SHA_A
    assert cv.boot_commit() == SHA_A


# ========================================================= the comparison
def test_a_moved_head_is_behind(tmp_path):
    root = _fake_repo(tmp_path, SHA_A)
    cv.record_boot(root)
    (root / ".git" / "refs" / "heads" / "main").write_text(SHA_B, encoding="utf-8")

    behind, booted, now = cv.staleness(root)
    assert behind is True
    assert booted == SHA_A
    assert now == SHA_B


def test_an_unchanged_head_is_current(tmp_path):
    root = _fake_repo(tmp_path, SHA_A)
    cv.record_boot(root)
    behind, _, _ = cv.staleness(root)
    assert behind is False


@pytest.mark.parametrize("boot_known,head_known", [(False, True), (True, False)])
def test_unknown_is_never_reported_as_stale(tmp_path, boot_known, head_known,
                                            monkeypatch):
    """Same rule as the trading calendar: the honest answer to "cannot say"
    is to change nothing. A false RESTART PENDING teaches him to ignore it."""
    root = _fake_repo(tmp_path, SHA_A)
    if boot_known:
        cv.record_boot(root)
    if not head_known:
        monkeypatch.setattr(cv, "head_commit", lambda *a, **k: None)
    behind, _, _ = cv.staleness(root)
    assert behind is False


# ============================================================ the wording
def test_a_pending_restart_says_so(tmp_path):
    root = _fake_repo(tmp_path, SHA_A)
    cv.record_boot(root)
    (root / ".git" / "refs" / "heads" / "main").write_text(SHA_B, encoding="utf-8")
    line = cv.describe(root)
    assert "RESTART PENDING" in line
    assert cv.short(SHA_A) in line
    assert cv.short(SHA_B) in line


def test_a_current_process_says_current(tmp_path):
    root = _fake_repo(tmp_path, SHA_A)
    cv.record_boot(root)
    assert "(current)" in cv.describe(root)
    assert "RESTART PENDING" not in cv.describe(root)


def test_an_unknown_version_says_unknown(tmp_path):
    plain = tmp_path / "no-git"
    plain.mkdir()
    assert "unknown" in cv.describe(plain)


# ======================================= it is reported, and it is not an alarm
def test_boot_logs_the_version():
    src = (ROOT / "src" / "bots" / "autonomous" / "autonomous_bot.py").read_text(
        encoding="utf-8")
    assert "code_version.record_boot()" in src
    assert 'logger.info("Code version: %s", code_version.describe())' in src


def test_the_morning_checklist_reports_it_without_failing_on_it():
    """HEAD moves on every commit, which is routine. A check that goes red
    every day is a check nobody reads - so the line is informational and must
    NOT touch checklist_passed."""
    src = (ROOT / "src" / "bots" / "autonomous" / "cron_reset.py").read_text(
        encoding="utf-8")
    assert "code_version.staleness()" in src
    assert 'f"Code: {code_line}' in src

    block = _code_only(src.split("WHICH CODE IS RUNNING")[1].split("msg = (")[0])
    assert "checklist_passed" not in block, (
        "a pending restart must not turn the morning check red")


def test_an_unreadable_version_does_not_break_the_checklist():
    src = (ROOT / "src" / "bots" / "autonomous" / "cron_reset.py").read_text(
        encoding="utf-8")
    block = _code_only(src.split("WHICH CODE IS RUNNING")[1].split("msg = (")[0])
    assert "except Exception:" in block
    assert 'code_line = "unknown"' in src
