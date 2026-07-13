"""Permanent tripwire: production code under src/ must never detect or branch on
a test environment (Project Law, Phase 1.5 — De-Mock the Production Tree).

Two guarantees:
  1. ZERO tolerance for environment sniffs — `"pytest"/"unittest" in sys.modules`,
     `sys.argv` pytest scans, and `isinstance(x, Mock/MagicMock)`. Any occurrence
     fails the build.
  2. A ratchet on the remaining `type(x).__name__ in ("MagicMock", ...)` guards:
     only the known, documented registry guards are allowed. A NEW one fails; the
     count may only shrink toward zero (see ALLOWED_MOCK_NAME_GUARDS).

If a test needs different behavior from real code, fix the TEST or add a real
injectable seam (DI / config flag with a production-safe default) — never a sniff.
"""
from __future__ import annotations

import re
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"

# --- Patterns that must NEVER appear in src/ (zero tolerance) ------------------
FORBIDDEN_PATTERNS: dict[str, re.Pattern[str]] = {
    "pytest-in-sys.modules": re.compile(r"""["']pytest["']\s+in\s+sys\.modules"""),
    "unittest-in-sys.modules": re.compile(r"""["']unittest["']\s+in\s+sys\.modules"""),
    "pytest-in-argv": re.compile(r"""["']pytest["']\s+in\s+arg\b"""),
    "isinstance-Mock": re.compile(r"""isinstance\([^)]*,\s*(?:Mock|MagicMock|NonCallableMagicMock)\s*\)"""),
}

# --- Ratchet: fully tightened. Phase 1.5 complete — ZERO type-name guards are
# tolerated in src/. Adding one requires explicit commander review and a very
# good reason (there isn't one — use a real DI/config seam instead).
ALLOWED_MOCK_NAME_GUARDS: set[str] = set()
MAX_ALLOWED_GUARDS = 0

MOCK_NAME_GUARD = re.compile(r"""\.__name__\s+in\s+\(\s*["'](?:MagicMock|Mock)["']""")


def _src_files() -> list[Path]:
    return [p for p in SRC_ROOT.rglob("*.py")]


def test_no_environment_sniffs_in_src() -> None:
    """No production file may detect the test environment."""
    violations: list[str] = []
    for path in _src_files():
        text = path.read_text(encoding="utf-8")
        for name, pattern in FORBIDDEN_PATTERNS.items():
            for i, line in enumerate(text.splitlines(), start=1):
                if pattern.search(line):
                    rel = path.relative_to(SRC_ROOT.parent)
                    violations.append(f"{rel}:{i}  [{name}]  {line.strip()}")
    assert not violations, (
        "Environment-sniffing detected in production src/ (Project Law violation).\n"
        "Fix the test or add a real DI/config seam — never sniff.\n\n"
        + "\n".join(violations)
    )


def test_mock_name_guards_do_not_grow() -> None:
    """The remaining type(...).__name__ in ('MagicMock', ...) guards are a ratchet."""
    found: list[tuple[str, int, str]] = []
    for path in _src_files():
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if MOCK_NAME_GUARD.search(line):
                rel = str(path.relative_to(SRC_ROOT.parent))
                found.append((rel, i, line.strip()))

    unknown = [f"{rel}:{i}  {txt}" for rel, i, txt in found if txt not in ALLOWED_MOCK_NAME_GUARDS]
    assert not unknown, (
        "New mock-type-name guard introduced in src/ (not in the allowed ratchet set).\n"
        "Do not add environment sniffs; drive the existing set toward zero instead.\n\n"
        + "\n".join(unknown)
    )
    assert len(found) <= MAX_ALLOWED_GUARDS, (
        f"Mock-type-name guard count grew to {len(found)} (max {MAX_ALLOWED_GUARDS}). "
        "The ratchet may only shrink."
    )
