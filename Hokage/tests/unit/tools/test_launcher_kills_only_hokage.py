"""The launcher killed the login it was waiting for, and it killed it with a
shotgun.

2026-10-13 06:22:37. Start-Hokage.ps1's section 4 waited for the commander's
login by polling the TOKEN ON DISK, and the instant it appeared ran an
unconditional:

    Stop-Hokage          # Get-Process python | Stop-Process -Force
    Start-Hokage

The token appears on disk inside the dashboard callback, 0.3s BEFORE that
handler answers the browser. So the launcher shot the process mid-request. The
browser retried, the retry landed on the new process carrying a now-spent
single-use request_token, and the commander was shown "Authentication failed"
in red for a login that had completely succeeded.

TWO THINGS WERE WRONG.

1. THE RESTART WAS A STEP, NOT A FALLBACK. It is no longer needed: the
   callback calls refresh_broker_session() and the bot's own feed probe
   retries, so a running Hokage picks a new token up by himself. The launcher
   must now ASK HIM and restart only if he is still blind. It must ask the
   running process, not the .env - a token is valid the instant it is written
   and that says nothing about whether any running object has read it. That
   gap is the 2026-08-05 blind-all-day incident and the entire reason
   refresh_broker_session exists.

2. THE KILL WAS Get-Process python - every python on the machine. A candle
   sync mid-write, a sweep three hours in, a weekly audit. A candle sync
   killed mid-write is how the archive loses a day nobody notices until a lab
   answers n=3, and the archive is the only evidence that can un-park an asset.

These are text assertions over PowerShell, so every one of them strips
comments first. The comments here deliberately quote the old broken code, and
a scan that cannot tell a rule from a description of one is worse than no scan.
"""
from __future__ import annotations

import pathlib

import pytest

ROOT = pathlib.Path(".")
START = ROOT / "Start-Hokage.ps1"
STOP = ROOT / "Stop-Hokage.ps1"
SELECTOR = ROOT / "tools" / "ops" / "HokageProcess.ps1"


def live_code(path: pathlib.Path) -> str:
    """The script with comments removed.

    PowerShell comments run from an unquoted '#' to end of line. Quote state is
    tracked so that a '#' inside a string survives; neither script uses <# #>
    blocks, and this helper would not handle them, so that is asserted below.
    """
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        quote = None
        cut = len(line)
        for i, ch in enumerate(line):
            if quote:
                if ch == quote:
                    quote = None
            elif ch in "'\"":
                quote = ch
            elif ch == "#":
                cut = i
                break
        out.append(line[:cut])
    return "\n".join(out)


@pytest.mark.parametrize("path", [START, STOP, SELECTOR])
def test_no_block_comments_so_the_stripper_is_honest(path):
    text = path.read_text(encoding="utf-8")
    assert "<#" not in text, f"{path} grew a block comment this helper ignores"


@pytest.mark.parametrize("path", [START, STOP, SELECTOR])
def test_the_stripper_actually_strips(path):
    """A no-op stripper would make every assertion below vacuous."""
    assert "#" in path.read_text(encoding="utf-8")
    assert "#" not in live_code(path)


# ---------------------------------------------- 1. the kill is scoped
@pytest.mark.parametrize("path", [START, STOP])
def test_no_script_kills_every_python_on_the_machine(path):
    code = live_code(path)
    assert "Get-Process python" not in code, (
        f"{path} is back to killing every python process, which includes a "
        f"candle sync mid-write"
    )


@pytest.mark.parametrize("path", [START, STOP])
def test_both_scripts_use_the_one_shared_selector(path):
    """Two copies of 'what counts as Hokage' drift, and the half that drifts
    is whichever one nobody ran that week."""
    code = live_code(path)
    assert "HokageProcess.ps1" in code
    assert "Get-HokageProcess" in code


def test_the_selector_identifies_hokage_by_his_command_line():
    code = live_code(SELECTOR)
    assert r"start\.py" in code, "the selector no longer matches start.py"
    assert "Win32_Process" in code


def test_the_selector_has_a_second_identification():
    """Win32_Process.CommandLine returns nothing without privileges, and
    nothing would read as 'Hokage is not running' - leaving a stray that
    quietly trades the same paper account."""
    code = live_code(SELECTOR)
    assert "Get-NetTCPConnection" in code
    assert "5000" in code


def test_the_selector_is_defined_exactly_once():
    defs = sum(
        live_code(p).count("function Get-HokageProcess")
        for p in (START, STOP, SELECTOR)
    )
    assert defs == 1, f"Get-HokageProcess is defined {defs} times"


# ------------------------------- 2. the restart is a fallback, not a step
def test_the_launcher_probes_the_process_before_killing_it():
    """THE REGRESSION. Between detecting the login and killing anything, the
    launcher must ask the running process whether it already healed."""
    code = live_code(START)
    detected = code.index("'Login detected.'")
    after = code[detected:]
    probe = after.index("Test-ProcessSeesMarket")
    kill = after.index("Stop-Hokage\n")
    assert probe < kill, (
        "Start-Hokage.ps1 restarts on login detection without asking whether "
        "Hokage already picked the token up - this is the 06:22 race"
    )


def test_the_restart_is_inside_a_branch():
    code = live_code(START)
    assert "if ($healed)" in code
    assert code.index("if ($healed)") < code[code.index("'Login detected.'"):].index(
        "Stop-Hokage\n"
    ) + code.index("'Login detected.'")


def test_the_probe_asks_the_running_process_not_the_token_on_disk():
    """check_broker_session.py tests the .env. A fresh token is valid the
    instant it is written and says nothing about whether the running process
    has read it."""
    code = live_code(START)
    body = code[code.index("function Test-ProcessSeesMarket"):]
    body = body[: body.index("function Get-BrokerState")]
    assert "broker/zerodha/status" in body
    assert "process_sees_market" in body
    assert "check_broker_session" not in body


def test_the_restart_survives_as_a_fallback():
    """The self-heal is a code path like any other. If it ever stops working,
    a blind Hokage all day is the cost, so the restart must still exist."""
    code = live_code(START)
    assert "Stop-Hokage\n" in code
    assert "Start-Hokage)" in code


# ------------------------------------------- the cross-file contract
def test_the_field_the_launcher_reads_is_the_field_the_api_publishes():
    """A PowerShell script depending on a JSON key from a Flask route is a
    contract nothing else checks. Rename the key and the launcher silently
    restarts Hokage after every single login, forever."""
    api = (ROOT / "src" / "hokage" / "dashboard" / "api.py").read_text(
        encoding="utf-8"
    )
    assert '"process_sees_market"' in api, (
        "Start-Hokage.ps1 reads process_sees_market from "
        "/api/v1/broker/zerodha/status; the route no longer publishes it"
    )
    assert '"data_feed_connected"' in api
    assert '"last_quote_ok"' in api

def test_the_grace_window_covers_one_full_probe_cycle():
    """process_sees_market waits for a quote that actually came back, and that
    probe runs about once a minute. A window shorter than one cycle restarts a
    Hokage who was simply about to answer - the same unnecessary restart, just
    arrived at more honestly."""
    code = live_code(START)
    line = next(
        l for l in code.splitlines() if l.strip().startswith("$HealGraceSeconds")
    )
    seconds = int(line.split("=")[1].strip())
    assert seconds >= 90, (
        f"the heal grace is {seconds}s, shorter than the ~60s probe cycle"
    )
