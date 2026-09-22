"""The dashboard is a trading terminal. Lock it, and lock it the right way round.

89 routes, no authentication. 25 of them change state, including:

    POST /api/v1/portfolio/<account_id>/trade   place a trade
    POST /api/v1/positions/<symbol>/close       close any position
    POST /api/v1/broker/token                   write the broker access token
    POST /api/v1/commander/chat                 an LLM path that can trade and
                                                skips the risk gates entirely

On a laptop behind a home router nobody notices. On a public server that is a
stranger's trading terminal, and the migration runbook puts it on a public
server.

THE TWO MISTAKES THIS FILE EXISTS TO PREVENT, both of which fail silently:

  1. THE PROXY HOLE. Loopback is exempt so the laptop and `ssh -L 5000:...`
     keep working. But put nginx or Caddy in front for TLS — exactly what the
     runbook recommends — and EVERY request arrives from 127.0.0.1. A naive
     loopback check disables authentication completely at the precise moment
     the dashboard becomes reachable from the internet. Any forwarding header
     therefore disqualifies the exemption.

  2. FAILING OPEN. If the password is not configured, a remote request must be
     REFUSED, not served. Exposing the dashboard before setting a password has
     to produce a 503, never an open terminal. The dangerous default is the one
     that must stop.
"""
from __future__ import annotations

import pytest

from hokage.dashboard import auth


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    auth.reset_attempts()
    monkeypatch.delenv(auth.PASSWORD_HASH_ENV, raising=False)
    yield
    auth.reset_attempts()


class _Headers(dict):
    def get(self, key, default=None):          # case-insensitive, like Flask's
        for k, v in self.items():
            if k.lower() == key.lower():
                return v
        return default


# ------------------------------------------------------- the proxy hole
@pytest.mark.parametrize("header", [
    "X-Forwarded-For", "X-Real-IP", "Forwarded", "X-Forwarded-Host",
])
def test_a_proxied_request_is_never_treated_as_local(header):
    """THE trap. Behind nginx every request's remote_addr is 127.0.0.1, so a
    plain loopback check would switch auth off exactly when TLS was added."""
    headers = _Headers({header: "203.0.113.9"})
    assert not auth.is_local_request("127.0.0.1", headers)


def test_a_genuine_local_request_is_still_exempt():
    """The laptop workflow and the SSH tunnel must keep working untouched."""
    assert auth.is_local_request("127.0.0.1", _Headers())
    assert auth.is_local_request("::1", _Headers())


def test_a_remote_address_is_never_local():
    assert not auth.is_local_request("203.0.113.9", _Headers())
    assert not auth.is_local_request(None, _Headers())


def test_a_forwarded_header_from_a_REMOTE_address_is_also_not_local():
    assert not auth.is_local_request("203.0.113.9", _Headers({"X-Real-IP": "10.0.0.2"}))


def test_an_empty_forwarding_header_does_not_disqualify():
    """Some proxies send the header blank. An empty value proves nothing, and
    treating it as proof would lock the commander out of his own laptop."""
    assert auth.is_local_request("127.0.0.1", _Headers({"X-Forwarded-For": ""}))


# ------------------------------------------------------------ the password
def test_nothing_verifies_when_no_password_is_configured():
    assert not auth.is_configured()
    assert not auth.check_password("anything")
    assert not auth.check_password("")


def test_the_right_password_verifies_and_a_wrong_one_does_not(monkeypatch):
    from werkzeug.security import generate_password_hash

    monkeypatch.setenv(auth.PASSWORD_HASH_ENV,
                       generate_password_hash("correct horse battery staple"))
    assert auth.is_configured()
    assert auth.check_password("correct horse battery staple")
    assert not auth.check_password("Correct horse battery staple")
    assert not auth.check_password("")


def test_a_corrupt_hash_refuses_rather_than_raising(monkeypatch):
    """A malformed .env must not crash the app open OR closed with a traceback."""
    monkeypatch.setenv(auth.PASSWORD_HASH_ENV, "not-a-real-hash")
    assert not auth.check_password("anything")


def test_the_password_itself_is_never_a_stored_value(monkeypatch):
    from werkzeug.security import generate_password_hash

    secret = "correct horse battery staple"
    monkeypatch.setenv(auth.PASSWORD_HASH_ENV, generate_password_hash(secret))
    assert secret not in auth.password_hash()


# ------------------------------------------------------------ rate limiting
def test_repeated_failures_lock_the_address_out():
    for _ in range(auth.MAX_ATTEMPTS):
        auth.record_failure("203.0.113.9")
    assert auth.locked_out("203.0.113.9") > 0


def test_one_failure_short_of_the_limit_is_not_a_lockout():
    for _ in range(auth.MAX_ATTEMPTS - 1):
        auth.record_failure("203.0.113.9")
    assert auth.locked_out("203.0.113.9") == 0


def test_a_success_clears_the_count():
    for _ in range(auth.MAX_ATTEMPTS - 1):
        auth.record_failure("203.0.113.9")
    auth.clear_failures("203.0.113.9")
    assert auth.locked_out("203.0.113.9") == 0


def test_one_address_lockout_does_not_lock_out_another():
    for _ in range(auth.MAX_ATTEMPTS):
        auth.record_failure("203.0.113.9")
    assert auth.locked_out("198.51.100.4") == 0


def test_the_lockout_expires():
    import time

    for _ in range(auth.MAX_ATTEMPTS):
        auth.record_failure("203.0.113.9")
    auth._attempts["203.0.113.9"][1] = time.time() - auth.LOCKOUT_SECONDS - 1
    assert auth.locked_out("203.0.113.9") == 0


# ------------------------------------------------------------- the session
def test_a_missing_secret_key_still_produces_one():
    """Without a configured key sessions reset on restart — an annoyance, never
    an insecurity. An EMPTY secret key would be the insecurity."""
    assert len(auth.session_secret()) >= 32


def test_a_configured_secret_key_is_stable(monkeypatch):
    monkeypatch.setenv(auth.SECRET_KEY_ENV, "a" * 64)
    assert auth.session_secret() == auth.session_secret() == "a" * 64


def test_the_login_route_is_reachable_without_a_session():
    """Otherwise there is no way to ever log in."""
    assert "/login" in auth.PUBLIC_PATHS


# ------------------------------------------- the generator never leaks a secret
def test_the_password_tool_never_writes_the_password_anywhere():
    import ast
    import pathlib

    src = pathlib.Path("tools/ops/set_dashboard_password.py").read_text(encoding="utf-8")
    assert "getpass" in src, "the password must be typed hidden, never echoed"
    assert "generate_password_hash" in src

    tree = ast.parse(src)
    printed = [n for n in ast.walk(tree)
               if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "print"]
    for call in printed:
        for arg in call.args:
            if isinstance(arg, ast.Name) and arg.id in ("first", "second"):
                pytest.fail("the tool prints the raw password")
