"""There must be ONE answer to "where is the brain".

2026-10-09: the commander asked to move the brain out of OneDrive, where a
1.5 GB SQLite file was being synced while Hokage wrote to it. `PathResolver`
honoured `HOKAGE_BRAIN_ROOT`. Nine other places did not -- they each computed
`Path(__file__).parents[N] / "hokage_brain"` for themselves:

    tools/ops/liveness_probe.py          the stop marker and liveness state
    tools/ops/prune_audit_trail.py       the database it prunes
    tools/research/candle_archive.py     candles.db, "the compounding asset"
    tools/research/weekly_audit.py       snapshots, portfolio, the ledger
    tools/research/sweep_lab.py          the ledger
    tools/research/holdout_lab.py        the portfolio
    tools/research/affordability_check.py
    tools/maintenance/regrade_reviews.py
    src/bots/autonomous/hokage_tools.py
    src/integrations/llm/processor.py     CWD-relative, worse still
    Start-Hokage.ps1                     the stop marker, in PowerShell

So the move would have given Hokage a brain at the new path while every tool
read and WROTE the old one. Two divergent brains, silently -- precisely what
MIGRATION.md step 1 exists to prevent. The candle archive would have gone on
appending to a candles.db nobody read, and Start-Hokage.ps1 would have checked
for a stop marker in a directory Stop-Hokage.ps1 no longer wrote to, which
would have re-broken the "a deliberate stop means stopped" guard hours after
it shipped.

A first attempt gave the liveness probe and the prune tool their own
three-line copy of the lookup, so an ops tool would still run on a tree that
fails to import. That copy read the ENVIRONMENT only -- and nothing but
start.py loads `.env`. So minutes after the brain moved, Start-Hokage.ps1
asked the probe whether a deliberate stop was in force, the probe fell back to
the repo-relative default, and it answered from a stale marker still sitting in
OneDrive. Deleting the real marker changed nothing: the split brain reproduced
inside the fix for it.

Both now import the shared resolver -- which reads `.env` itself -- and keep
the hardcoded path only as a last-resort fallback behind `except Exception`.
"""
from __future__ import annotations

import ast
import os
import pathlib

import pytest

from hokage.memory.resolver import (
    BRAIN_ROOT_ENV,
    PathResolver,
    _parse_brain_root,
    brain_root,
)

#: Entry points launched by PowerShell and cron rather than start.py. They
#: import the shared resolver but keep a last-resort fallback, so each still
#: contains one `ROOT / "hokage_brain"` that the AST guard must tolerate.
FALLBACK_ALLOWED = {
    "tools/ops/liveness_probe.py": "the watchdog must run when src does not import",
    "tools/ops/prune_audit_trail.py": "an ops tool must run on a broken tree",
}


# --------------------------------------------------------- the shared answer
def test_the_env_var_relocates_the_brain(monkeypatch, tmp_path):
    monkeypatch.setenv(BRAIN_ROOT_ENV, str(tmp_path / "elsewhere"))
    assert brain_root() == (tmp_path / "elsewhere").resolve()


def test_an_unset_var_falls_back_to_a_relative_default(monkeypatch):
    monkeypatch.delenv(BRAIN_ROOT_ENV, raising=False)
    assert brain_root().name == "hokage_brain"


def test_a_blank_var_is_treated_as_unset(monkeypatch):
    """An empty value in .env must not resolve the brain to the filesystem
    root, which is what Path("").resolve() would hand back."""
    monkeypatch.setenv(BRAIN_ROOT_ENV, "   ")
    assert brain_root().name == "hokage_brain"


def test_path_resolver_and_brain_root_agree(monkeypatch, tmp_path):
    """PathResolver() with no argument IS brain_root(). If these diverge,
    half of Hokage uses one brain and half uses another."""
    monkeypatch.setenv(BRAIN_ROOT_ENV, str(tmp_path / "shared"))
    assert PathResolver().resolve_brain_root() == brain_root()


def test_an_explicit_root_still_wins_over_the_env(monkeypatch, tmp_path):
    """Test sandboxes pass tmp_path explicitly; that must override .env."""
    monkeypatch.setenv(BRAIN_ROOT_ENV, str(tmp_path / "production"))
    explicit = tmp_path / "sandbox"
    assert PathResolver(explicit).resolve_brain_root() == explicit.resolve()


# ---------------------------------- .env, for everything start.py never ran
def test_dotenv_supplies_the_root_when_the_environment_does_not():
    """THE BUG THIS PINS. start.py loads .env; nothing else does. The liveness
    probe, the prune tool, the candle archive and the weekly audit are launched
    by PowerShell and cron.

    On 2026-10-09, minutes after the brain moved to C:/Hokage,
    Start-Hokage.ps1 asked the probe whether a deliberate stop was in force.
    The probe found the variable unset, fell back to the repo-relative default,
    and read a stale marker still sitting in OneDrive. Deleting the real marker
    changed nothing -- the split brain reproduced inside the fix for it.
    """
    assert _parse_brain_root("HOKAGE_BRAIN_ROOT=C:/Hokage/hokage_brain") == \
        "C:/Hokage/hokage_brain"


@pytest.mark.parametrize("line,expected", [
    ('HOKAGE_BRAIN_ROOT="C:/q"', "C:/q"),
    ("HOKAGE_BRAIN_ROOT='C:/q'", "C:/q"),
    ("  HOKAGE_BRAIN_ROOT = C:/q  ", "C:/q"),
    ("# HOKAGE_BRAIN_ROOT=C:/commented", ""),
    ("HOKAGE_BRAIN_ROOT=", ""),
    ("SOMETHING_ELSE=C:/q", ""),
    ("no equals sign here", ""),
    ("", ""),
])
def test_the_dotenv_parse_handles_real_env_files(line, expected):
    assert _parse_brain_root(line) == expected


def test_the_parse_reads_only_the_one_key_it_needs():
    """Resolving a filesystem path must not inject a file full of credentials
    into the process. .env holds ZERODHA_API_SECRET and ZERODHA_TOTP_SECRET."""
    text = (
        "ZERODHA_API_KEY=should-never-be-read\n"
        "ZERODHA_TOTP_SECRET=should-never-be-read\n"
        "HOKAGE_BRAIN_ROOT=C:/Hokage/hokage_brain\n"
    )
    assert _parse_brain_root(text) == "C:/Hokage/hokage_brain"


def test_resolving_the_brain_never_writes_to_the_environment():
    before = dict(os.environ)
    brain_root()
    assert dict(os.environ) == before, "brain_root() mutated os.environ"


def test_the_environment_beats_dotenv(monkeypatch, tmp_path):
    """An explicit variable is a deliberate override -- a sandbox, a one-off
    run against a copy -- and must not be silently replaced by .env."""
    monkeypatch.setenv(BRAIN_ROOT_ENV, str(tmp_path / "explicit"))
    assert brain_root() == (tmp_path / "explicit").resolve()


def test_the_suite_has_the_dotenv_fallback_switched_off():
    """conftest.py sets CONSULT_DOTENV = False. Without it, any test that
    cleared HOKAGE_BRAIN_ROOT would fall through to .env and resolve the REAL
    brain -- the 2026-07-13 incident, where pytest runs planted ghost
    positions in the live ledger, by a different route.

    A config seam, not environment detection inside src: Project Law forbids
    the latter, and tests/test_no_mock_sniffing_in_src.py enforces it.
    """
    from hokage.memory import resolver

    assert resolver.CONSULT_DOTENV is False
    assert resolver._brain_root_from_dotenv() == ""


def test_clearing_the_variable_cannot_reach_the_production_brain(monkeypatch):
    """The specific hazard the seam closes."""
    monkeypatch.delenv(BRAIN_ROOT_ENV, raising=False)
    resolved = brain_root()
    assert resolved == (pathlib.Path.cwd() / "hokage_brain").resolve(), (
        f"a cleared variable resolved to {resolved}, outside the working tree"
    )


def test_the_fallback_is_on_by_default_for_production():
    """The flag must default to True in src. conftest flips it for the suite;
    a default of False would silently disable the fix in production, where
    PowerShell and cron entry points depend on it."""
    src = pathlib.Path("src/hokage/memory/resolver.py").read_text(encoding="utf-8")
    assert "CONSULT_DOTENV = True" in src


# ------------------------------- the fallback copies must still be correct
@pytest.mark.parametrize("rel", sorted(FALLBACK_ALLOWED))
def test_an_entry_point_resolves_the_same_root_as_everything_else(
    rel, monkeypatch, tmp_path
):
    """Load the module with the env var set and confirm it lands in the same
    place brain_root() would. If these diverge, the probe guards one brain
    while Hokage trades another."""
    import importlib
    import sys

    monkeypatch.setenv(BRAIN_ROOT_ENV, str(tmp_path / "moved"))
    monkeypatch.syspath_prepend(str(pathlib.Path(rel).parent))

    name = pathlib.Path(rel).stem
    sys.modules.pop(name, None)
    try:
        mod = importlib.import_module(name)
        assert mod.BRAIN == brain_root(), (
            f"{rel} resolves {mod.BRAIN}, brain_root() resolves {brain_root()}"
        )
    finally:
        sys.modules.pop(name, None)


@pytest.mark.parametrize("rel", sorted(FALLBACK_ALLOWED))
def test_an_entry_point_imports_the_shared_resolver(rel):
    """The fallback must be a fallback. A module that only ever computes its
    own path cannot read .env, which is the whole failure above."""
    src = pathlib.Path(rel).read_text(encoding="utf-8")
    assert "from hokage.memory.resolver import brain_root" in src, (
        f"{rel} must import the shared resolver, not just compute a path"
    )
    assert "sys.path.insert" in src, f"{rel} must put src on the path first"


@pytest.mark.parametrize("rel", sorted(FALLBACK_ALLOWED))
def test_an_entry_point_keeps_a_fallback(rel):
    """A watchdog that cannot start because the code it watches fails to
    import is worse than no watchdog."""
    src = pathlib.Path(rel).read_text(encoding="utf-8")
    assert "except Exception:" in src and "def _brain_root" in src


# --------------------------------------- nothing new may hardcode the path
def test_no_python_file_hardcodes_the_brain_path():
    """The regression guard. A new `ROOT / "hokage_brain"` anywhere puts a
    second brain back into the system."""
    offenders = []
    for base in ("src", "tools"):
        for path in pathlib.Path(base).rglob("*.py"):
            rel = path.as_posix()
            text = path.read_text(encoding="utf-8")
            try:
                tree = ast.parse(text)
            except SyntaxError:
                continue

            for node in ast.walk(tree):
                # Matches `<anything> / "hokage_brain"` and `Path("hokage_brain...")`
                if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
                    right = node.right
                    if (isinstance(right, ast.Constant)
                            and right.value == "hokage_brain"):
                        if rel in FALLBACK_ALLOWED or rel.endswith("memory/resolver.py"):
                            continue
                        offenders.append(f"{rel}:{node.lineno}")
                if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "Path":
                    for arg in node.args:
                        if (isinstance(arg, ast.Constant)
                                and isinstance(arg.value, str)
                                and arg.value.startswith("hokage_brain")):
                            offenders.append(f"{rel}:{node.lineno}")

    assert not offenders, (
        "these resolve the brain without honouring "
        f"{BRAIN_ROOT_ENV}: {offenders}"
    )


def test_the_fallback_allowlist_is_not_a_blank_cheque():
    """Every exempted file must actually exist and carry a stated reason, so
    the allowlist cannot quietly accumulate entries."""
    for rel, reason in FALLBACK_ALLOWED.items():
        assert pathlib.Path(rel).exists(), f"{rel} is allowlisted but missing"
        assert len(reason) > 20, f"{rel} needs a real reason, got {reason!r}"
