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
def _clean_boot(monkeypatch, tmp_path):
    """Each test gets its own notion of what the process booted on.

    AND ITS OWN BRAIN. Resetting the process global was enough while the boot
    commit lived only in memory. Now that boot publishes a record to disk, a
    test asserting "nothing is running" will read whatever record any other
    test in the session left behind - and these two passed alone and failed in
    the full suite for exactly that reason. The isolation has to cover every
    place the answer can come from, not just the one it used to come from.
    """
    monkeypatch.setattr(cv, "_BOOT_COMMIT", None)
    private = tmp_path / "version-brain"
    private.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOKAGE_BRAIN_ROOT", str(private))


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
    assert "code_version.record_boot(publish=True)" in src
    assert 'logger.info("Code version: %s", code_version.describe())' in src


def test_only_the_bot_publishes_the_shared_record():
    """`publish` is a claim to BE the running bot, so it defaults to off.

    Published unconditionally, it wrote a fake sha and a pytest pid into a
    brain mid-suite and a later test read it back. In production the same hole
    lets any tool that records a boot overwrite the real bot's record with its
    own pid - after which the morning brief reports a tool's commit as the
    bot's, and reports nothing at all once the tool exits.
    """
    import inspect

    sig = inspect.signature(cv.record_boot)
    assert sig.parameters["publish"].default is False

    for tool in sorted((ROOT / "tools").rglob("*.py")):
        body = tool.read_text(encoding="utf-8", errors="replace")
        assert "record_boot(publish=True)" not in body, (
            f"{tool.name} claims to be the running bot")


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


# ============================== across a process boundary (added 2026-11-09)
# `_BOOT_COMMIT` is a process global, so only the bot could ever read it. The
# 06:30 morning brief runs as its own scheduled task, got None, and printed
# "code version unknown (no readable .git)" while the repository read
# perfectly - the one panel placed to say RESTART PENDING could not know, and
# blamed the repo for it.

@pytest.fixture
def brain(tmp_path, monkeypatch):
    monkeypatch.setenv("HOKAGE_BRAIN_ROOT", str(tmp_path / "brain"))
    (tmp_path / "brain").mkdir(parents=True, exist_ok=True)
    return tmp_path / "brain"


def test_publishing_lets_another_process_read_the_version(tmp_path, brain,
                                                          monkeypatch):
    root = _fake_repo(tmp_path, SHA_A)
    cv.record_boot(root, publish=True)
    # A fresh process: the global is gone, the file is not.
    monkeypatch.setattr(cv, "_BOOT_COMMIT", None)
    live = cv.running_version()
    assert live is not None
    assert live["commit"] == SHA_A


def test_the_brief_can_now_say_a_restart_is_pending(tmp_path, brain,
                                                    monkeypatch):
    """The whole point. Before the record existed, `behind` was False in the
    brief's process no matter what the repo had done."""
    root = _fake_repo(tmp_path, SHA_A)
    cv.record_boot(root, publish=True)
    (root / ".git" / "refs" / "heads" / "main").write_text(SHA_B,
                                                           encoding="utf-8")
    monkeypatch.setattr(cv, "_BOOT_COMMIT", None)
    behind, booted, now = cv.staleness(root)
    assert behind is True
    assert booted == SHA_A and now == SHA_B
    assert "RESTART PENDING" in cv.describe(root)


def test_a_dead_pid_reports_nothing_not_a_stale_version(tmp_path, brain,
                                                        monkeypatch):
    """A record outlives the process that wrote it. Read naively it reports a
    dead bot's commit as current - the cached CONNECTED flag again."""
    root = _fake_repo(tmp_path, SHA_A)
    cv.record_boot(root, publish=True)
    monkeypatch.setattr(cv, "_BOOT_COMMIT", None)
    monkeypatch.setattr(cv, "_pid_is_alive", lambda pid, started: False)
    assert cv.running_version() is None
    behind, booted, _ = cv.staleness(root)
    assert booted is None
    assert behind is False


def test_a_pid_that_cannot_be_checked_is_not_declared_dead(tmp_path, brain,
                                                           monkeypatch):
    """None is not False. A probe that cannot see the process table must not
    report the bot as gone."""
    root = _fake_repo(tmp_path, SHA_A)
    cv.record_boot(root, publish=True)
    monkeypatch.setattr(cv, "_BOOT_COMMIT", None)
    monkeypatch.setattr(cv, "_pid_is_alive", lambda pid, started: None)
    live = cv.running_version()
    assert live is not None
    assert live["commit"] == SHA_A
    assert live["pid_confirmed"] is False


def test_a_recycled_pid_does_not_pass_for_the_bot(brain, monkeypatch):
    """Windows reuses pids. A live process that started long after the record
    was written is not the process the record describes."""
    import os

    real_start = None
    try:
        import psutil

        real_start = psutil.Process(os.getpid()).create_time()
    except Exception:
        pytest.skip("psutil unavailable")
    assert cv._pid_is_alive(os.getpid(), real_start) is True
    assert cv._pid_is_alive(os.getpid(), real_start - 86400.0) is False


def test_an_unreadable_record_is_unknown_not_a_crash(brain):
    (brain / cv.BOOT_RECORD_NAME).write_text("{not json", encoding="utf-8")
    assert cv.running_version() is None


def test_a_record_without_a_pid_is_refused(brain):
    import json

    (brain / cv.BOOT_RECORD_NAME).write_text(
        json.dumps({"commit": SHA_A}), encoding="utf-8")
    assert cv.running_version() is None


def test_no_record_at_all_names_the_right_cause(tmp_path, brain, monkeypatch):
    """The message used to blame .git for a missing boot record, sending the
    reader to check a repository that was fine."""
    root = _fake_repo(tmp_path, SHA_A)
    monkeypatch.setattr(cv, "_BOOT_COMMIT", None)
    line = cv.describe(root)
    assert "no readable .git" not in line
    assert "recorded its version" in line
    assert cv.short(SHA_A) in line


def test_a_truly_unreadable_repo_still_says_no_git(tmp_path, brain,
                                                   monkeypatch):
    plain = tmp_path / "no-git-here"
    plain.mkdir()
    monkeypatch.setattr(cv, "_BOOT_COMMIT", None)
    monkeypatch.setattr(cv, "head_commit", lambda *a, **k: None)
    assert "no readable .git" in cv.describe(plain)


def test_the_record_never_leaves_a_brain_it_cannot_find(monkeypatch, tmp_path):
    """A version probe must never be the thing that stops the bot booting."""
    monkeypatch.setattr(cv, "_record_path", lambda: None)
    cv._write_boot_record(SHA_A)          # must not raise
    monkeypatch.setattr(cv, "_BOOT_COMMIT", None)
    root = _fake_repo(tmp_path, SHA_A)
    assert cv.record_boot(root, publish=True) == SHA_A
