"""A venue said CONNECTED on every boot without contacting anything.

2026-11-03, 21:21. The boot log printed:

    Connected venue 'groww_main': Connected to Groww via compliancy static
    proxy 103.45.122.9

`groww_venue.py` contained no network machinery at all — no requests, no
httpx, no urllib, no socket. `connect()` set `self._connection_state =
CONNECTED` and returned a hardcoded `latency_ms=12.0`. The IP, the port 8443
and the gateway `secure-retail-gateway.hokage.net` were literals inside a
block the code itself labelled "Default mock proxy config layer", and
`config/ip_whitelisting_proxy.json` never existed, so that default was what
ran. `hokage.net` is a parked domain that is not the commander's; the
subdomain resolved only because parked domains resolve everything.

It also set `"sebi_compliance_active": True`.

WHY THAT ONE IS WORSE THAN A STUB. The reason the live canary cannot run from
this laptop is the SEBI static-IP rule for API orders. That line reads as if
the blocker is solved. It is not. The file's own compliance guard could never
fire either — `if sebi_compliance_active and not enabled`, with `enabled`
defaulting True. And `get_account_balance()` returned a hardcoded 150,000 as a
BROKER balance: the data doctrine permits synthetic cash, not a venue
reporting it as a broker's.

In PAPER nothing consumed it. Every call site gates on `"paper" in venue_id`,
so it was excluded from balances, position sync and the duplicate-entry check,
and `place_order` raised before reaching a wire. The cost was the log line —
the same currency as "Health Score 100/100" while he was dead for 3h39m, and
as nine days blind on a token that was already expired. A system that reports
a connection it never made has taught its reader to trust the next one.

Deleted 2026-11-04 on the commander's word, with its two lines of pipeline
wiring. This test is the rail: the next one cannot arrive quietly.

ITS TWIN WENT THE SAME NIGHT. `institutional_venue.py` (`oanda_main`,
"Connected to institutional Forex testing feed") was the same shape — no
network imports, `connect()` returning CONNECTED with `latency_ms=5.0`, and
`get_account_balance()` returning a hardcoded 1,000,000: SEVEN TIMES the Groww
phantom, on an asset class outside the mandate entirely. It sat in
KNOWN_FABRICATED as recorded debt for about three hours and was then deleted
on his word, so that set is now empty. IT MAY ONLY SHRINK — a new module added
to it fails `test_the_known_list_is_exactly_what_we_know_about`, which is the
point: the exemption cannot become the door.

WHAT REPLACED IT IS A LOUD FAILURE, AND THAT IS THE WHOLE ARGUMENT. `oanda`
keeps its capability profile and its real `paper_oanda` venue, so paper is
untouched. What it no longer has is a registered `oanda_main`. Ask the broker
registry for a LIVE forex venue now and it raises KeyError — "Ensure
credentials and connection adapters are configured before enabling LIVE mode."
`alpaca_main` has sat in exactly that state all along, which is how we know
the state is survivable. A venue that cannot trade forex and says so beats one
that cannot trade forex and reports a million rupees.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

BROKERS = Path(__file__).resolve().parents[3] / "src" / "integrations" / "brokers"

#: Paper venues are *supposed* to connect to nothing; saying CONNECTED is the
#: truth for them. `base_venue` and the non-venue helpers are not venues.
EXEMPT = {"paper_venue.py", "base_venue.py"}

#: Modules that claim CONNECTED with no way to connect. Empty, and the only
#: legitimate edit to it is a deletion. ONLY EVER REMOVE FROM THIS SET.
KNOWN_FABRICATED: set[str] = set()

#: Evidence that a module can actually reach a broker: it speaks a protocol
#: itself, or it delegates to something that does (KiteVenue.connect is one
#: line — `return self._connection_manager.connect()`).
#:
#: THESE ARE DELIBERATELY NARROW. The first draft of this list held the bare
#: word "websocket", and both fabricated venues sailed through it on
#: `websocket_streaming=False` in their capability block — a declaration of
#: what the venue would support, matched as if it were a network call. The
#: rail would have passed the very file it was written for. A marker has to be
#: machinery, not a mention: an import, a call, or a delegation.
NETWORK_MARKERS = (
    "import urllib", "import requests", "import httpx", "import socket",
    "from urllib", "from requests", "http.client", "aiohttp",
    "kiteconnect", "urlopen", "connection_manager",
    "websocket.", "WebSocketApp",
)

#: Literals from the deleted file. They described infrastructure that does not
#: exist, so they must not reappear anywhere in the tree.
FICTIONS = (
    "103.45.122.9",
    "secure-retail-gateway",
    "sebi_compliance_active",
    "compliancy static proxy",
)


def _venue_modules() -> list[Path]:
    return sorted(p for p in BROKERS.glob("*_venue.py") if p.name not in EXEMPT)


def _claims_connected(source: str) -> bool:
    """True if this module's own `connect()` hands back CONNECTED.

    Parsed rather than grepped: `ConnectionState.CONNECTED` appears in almost
    every venue inside `get_status`, `disconnect` and error branches, and only
    its appearance in `connect` is a claim about a session existing.
    """
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "connect":
            body = ast.dump(node)
            if "'CONNECTED'" in body or '"CONNECTED"' in body:
                return True
    return False


def _can_reach_a_broker(source: str) -> bool:
    return any(marker in source for marker in NETWORK_MARKERS)


# ============================================ the rail
@pytest.mark.parametrize(
    "module", _venue_modules(), ids=lambda p: p.name)
def test_a_venue_that_says_connected_must_be_able_to_connect(module: Path):
    """CONNECTED is a claim about the world. Earn it or do not make it."""
    source = module.read_text(encoding="utf-8")
    if not _claims_connected(source):
        return                      # delegates, or never claims it — fine
    if module.name in KNOWN_FABRICATED:
        pytest.xfail(f"{module.name} is a known fabrication, reported, awaiting a decision")
    assert _can_reach_a_broker(source), (
        f"{module.name} returns CONNECTED but contains no way to contact a "
        f"broker. This is how 'Connected to Groww via compliancy static proxy "
        f"103.45.122.9' was printed on every boot for four months."
    )


def test_the_known_list_is_exactly_what_we_know_about():
    """The exemption is a record of debt, not a door.

    If a new module needs to be added here to make the suite pass, this test
    fails first and the addition has to be argued for out loud.
    """
    offenders = {
        m.name for m in _venue_modules()
        if _claims_connected(m.read_text(encoding="utf-8"))
        and not _can_reach_a_broker(m.read_text(encoding="utf-8"))
    }
    assert offenders == KNOWN_FABRICATED, (
        f"fabricated venues changed: {offenders} vs recorded {KNOWN_FABRICATED}. "
        f"If this shrank, delete the name from KNOWN_FABRICATED. If it grew, "
        f"the new one is the bug."
    )


def test_the_rail_catches_the_file_it_was_written_for():
    """Proof, not assertion. The deleted source is replayed out of git and put
    through the same two predicates, because a rail that cannot catch the
    original incident is decoration. This is also what exposed the "websocket"
    false positive above: the first version of the marker list passed this.
    """
    import subprocess
    rel = "Hokage/src/integrations/brokers/groww_venue.py"
    cwd = BROKERS.parents[3]          # the git root; Hokage is a subdirectory

    def git(*args: str):
        return subprocess.run(["git", *args], cwd=cwd,
                              capture_output=True, text=True)

    # The last commit to touch the path is the one that deleted it, so the
    # file lives in that commit's PARENT. Resolved rather than hardcoded: a
    # pinned sha would make this test rot the moment history is rewritten,
    # and a `HEAD:` read would simply skip forever now that it is gone.
    deleting = git("rev-list", "-n", "1", "HEAD", "--", rel).stdout.strip()
    if not deleting:
        pytest.skip("no history for the deleted file; the rail outlives it")
    out = git("show", f"{deleting}^:{rel}")
    if out.returncode != 0:
        pytest.skip("the deleted file is not reachable from history")
    source = out.stdout
    assert "static_proxy_ip" in source, "replayed the wrong file"
    assert _claims_connected(source), "connect() did return CONNECTED"
    assert not _can_reach_a_broker(source), (
        "the rail would NOT have caught groww_venue.py — it is decoration")


# ============================================ the specific deletion
def test_the_groww_venue_is_gone():
    assert not (BROKERS / "groww_venue.py").exists()


def test_nothing_registers_groww_any_more():
    pipeline = (BROKERS.parents[1] / "hokage" / "orchestrator" / "pipeline.py")
    source = pipeline.read_text(encoding="utf-8")
    assert "groww" not in source.lower(), "pipeline still wires the deleted venue"


def test_the_invented_infrastructure_appears_nowhere():
    """A parked domain, an IP nothing dials, and a compliance flag that was
    never true. None of it described anything real."""
    src = BROKERS.parents[1]
    found: list[str] = []
    for path in src.rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for fiction in FICTIONS:
            if fiction in text and path.name != Path(__file__).name:
                found.append(f"{path.relative_to(src)}: {fiction}")
    assert not found, f"invented infrastructure is back: {found}"


# ============================================ what it must not break
def test_the_venues_that_remain_are_still_registered():
    """Deleting one venue must not quietly unregister the real ones."""
    pipeline = (BROKERS.parents[1] / "hokage" / "orchestrator" / "pipeline.py")
    source = pipeline.read_text(encoding="utf-8")
    for venue in ("paper_main", "paper_mcx", "kite_main", "coindcx_main"):
        assert venue in source, f"{venue} is no longer registered"
    # The per-broker paper venues are not literals here — they are built in a
    # loop from `profile.paper_venue_id`, which is why `paper_oanda` survives
    # the deletion: it comes from the capability profile, not from the venue
    # class. `test_forex_keeps_its_paper_venue_and_its_profile` holds that end.
    assert "profile.paper_venue_id" in source


def test_the_institutional_venue_is_gone():
    assert not (BROKERS / "institutional_venue.py").exists()
    pipeline = (BROKERS.parents[1] / "hokage" / "orchestrator" / "pipeline.py")
    source = pipeline.read_text(encoding="utf-8")
    assert "InstitutionalVenue" not in source
    assert "oanda_main" not in source, "pipeline still registers the deleted venue"


def test_forex_keeps_its_paper_venue_and_its_profile():
    """Deleting the fake LIVE venue must not cost `oanda` its real paper one.

    `paper_oanda` is a genuine PaperVenue and several exit-loop tests count on
    it being registered. The capability profile stays too: the broker is still
    a real broker, it simply has no live adapter here.
    """
    import sys
    sys.path.insert(0, str(BROKERS.parents[1]))
    from integrations.brokers.broker_registry import _FALLBACK_BROKER_CAPABILITIES

    profile = _FALLBACK_BROKER_CAPABILITIES["oanda"]
    assert profile["paper_venue_id"] == "paper_oanda"
    assert profile["supported_exchanges"] == ["FOREX"]


def test_a_live_forex_request_now_fails_loudly_instead_of_inventing_a_million():
    """The replacement for a fabricated venue is an honest KeyError.

    `get_live_venue` resolves `profile.live_venue_id` and raises when it is not
    registered, naming the venue and telling the reader to configure
    credentials and adapters first. `alpaca_main` has been in that state all
    along, so this is the system's existing, survivable behaviour — not a new
    cliff introduced by the deletion. What is gone is the alternative: a
    `connect()` that said CONNECTED and a balance of 1,000,000 that no broker
    had ever confirmed.
    """
    registry_src = (BROKERS / "broker_registry.py").read_text(encoding="utf-8")
    assert '"live_venue_id": "oanda_main"' in registry_src, (
        "the profile still points at oanda_main, which is what makes the "
        "KeyError name the missing venue")
    assert "is not registered" in registry_src
    assert "before enabling LIVE mode" in registry_src
    assert not (BROKERS / "institutional_venue.py").exists(), (
        "nothing registers oanda_main any more, so that lookup now raises")


def test_pipeline_still_parses():
    """A line-range deletion is exactly the edit that leaves a dangling call."""
    pipeline = (BROKERS.parents[1] / "hokage" / "orchestrator" / "pipeline.py")
    ast.parse(pipeline.read_text(encoding="utf-8"))
