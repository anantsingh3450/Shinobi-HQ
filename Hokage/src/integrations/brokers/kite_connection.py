from __future__ import annotations

import logging
import socket
import time

from kiteconnect import KiteConnect
from kiteconnect import exceptions as kite_exceptions
from integrations.brokers.secrets import SecretManager
from integrations.brokers.models import ConnectionState, ConnectionStatus, utc_now

logger = logging.getLogger("Hokage.KiteConnection")

#: Failures that mean THE LINE IS DOWN, not that the session is dead.
#: `kiteconnect` re-raises the requests library's exceptions untouched for
#: anything below HTTP - see KiteConnect._request, "Any requests lib related
#: exceptions are raised here" - so a dropped hotspot arrives as a
#: ConnectionError wrapping a NameResolutionError and never as a
#: TokenException. DataException is included because a captive portal
#: answering with HTML is a network problem wearing a parser error.
_TRANSPORT_FAILURES: tuple[type[BaseException], ...] = (
    kite_exceptions.NetworkException,
    kite_exceptions.DataException,
    socket.gaierror,
    socket.timeout,
    ConnectionError,          # also the base of requests' ConnectionError
    TimeoutError,
    OSError,                  # socket-level failures, incl. "network is down"
)

#: Authentication failures, which are the ONLY ones he can act on.
_AUTH_FAILURES: tuple[type[BaseException], ...] = (
    kite_exceptions.TokenException,
    kite_exceptions.PermissionException,
)

#: Seconds between repeats of either diagnosis. The health loop calls
#: connect() once a minute, and on 2026-11-13 that printed the login
#: instruction sixty times an hour for an outage no login could fix.
_SAY_AGAIN_AFTER_SECONDS = 600.0


def _is_transport_failure(exc: BaseException) -> bool:
    """Is this the line, or the session?

    A WRONG ANSWER IS EXPENSIVE IN BOTH DIRECTIONS, so this is deliberately
    asymmetric: auth wins when something is both, and anything unrecognised
    is treated as auth. Telling him to log in when he need not is noise;
    staying quiet when the token really died is a blind session.
    """
    if isinstance(exc, _AUTH_FAILURES):
        return False
    cause = exc
    seen = 0
    while cause is not None and seen < 10:
        if isinstance(cause, _AUTH_FAILURES):
            return False
        if isinstance(cause, _TRANSPORT_FAILURES):
            return True
        cause = cause.__cause__ or cause.__context__
        seen += 1
    return False


class KiteConnectionManager:
    """Manages Zerodha Kite Connect session authentication and connection state diagnostics."""

    def __init__(self, secrets_manager: SecretManager) -> None:
        self._secrets_manager = secrets_manager
        self._kite: KiteConnect | None = None
        self._connection_state = ConnectionState.DISCONNECTED

    @property
    def connection_state(self) -> ConnectionState:
        return self._connection_state

    def get_kite_client(self) -> KiteConnect:
        """Return the active KiteConnect client instance.

        Raises RuntimeError if connection is not active.
        """
        if self._kite is None or self._connection_state != ConnectionState.CONNECTED:
            raise RuntimeError("Venue is not connected.")
        return self._kite

    def connect(self) -> ConnectionStatus:
        """Establish a session connection by validating the credentials.

        Loads credentials via SecretManager, instantiates KiteConnect,
        and runs profile verification.
        """
        api_key = self._secrets_manager.get_secret("api_key")
        access_token = self._secrets_manager.get_secret("access_token")

        if not api_key:
            self._connection_state = ConnectionState.DISCONNECTED
            self._kite = None
            raise ValueError("api_key not configured in secrets.json")

        kite = KiteConnect(api_key=api_key)
        if access_token:
            kite.set_access_token(access_token)
        else:
            self._connection_state = ConnectionState.DISCONNECTED
            self._kite = None
            raise ValueError("access_token not configured in secrets.json")

        try:
            # Validate session by querying profile
            kite.profile()
            self._kite = kite
            self._connection_state = ConnectionState.CONNECTED
            return ConnectionStatus(
                state=ConnectionState.CONNECTED,
                last_checked=utc_now(),
                latency_ms=8.5,
                message="Connected to Zerodha Kite Connect."
            )
        except Exception as e:
            self._connection_state = ConnectionState.DISCONNECTED
            self._kite = None
            if _is_transport_failure(e):
                # THE LINE, NOT THE SESSION. Measured 2026-11-13: the hotspot
                # dropped, `kite.profile()` raised a ConnectionError wrapping
                # "Failed to resolve api.kite.trade [Errno 11001]", and this
                # branch told the commander his token had expired and to go
                # and log in - once a minute, while the token was valid and
                # went on trading twenty minutes later. He could not even
                # read it: the same outage was holding Telegram down.
                #
                # A LOGIN INSTRUCTION HE CANNOT ACT ON IS WORSE THAN SILENCE.
                # It is the alarm that cried wolf this morning in a costlier
                # place, because the words are identical to a real expiry -
                # which happens every day around 06:00 - and he would have no
                # way left to tell them apart.
                self._say_once(
                    "transport", logging.WARNING,
                    "Zerodha is UNREACHABLE and the session is not the "
                    "problem: %s. Nothing to do - no login fixes a dropped "
                    "line, and the reconnect loop takes it the moment it "
                    "returns. Hokage stands aside until then.", e)
                raise RuntimeError(f"Broker unreachable: {e}")
            self._say_once(
                "auth", logging.CRITICAL,
                "\n" + "=" * 70 + "\n"
                "⚠️  ZERODHA SESSION TOKEN EXPIRED OR INVALID ⚠️\n"
                "Hokage cannot fetch live market data without a valid session.\n"
                "The line to Zerodha is UP; the session is what it refused.\n"
                "ACTION REQUIRED:\n"
                "  1. Open the Hokage Dashboard at http://127.0.0.1:5000\n"
                "  2. Click 'Login to Zerodha' and complete authentication.\n"
                "  3. Paste the redirect URL from Zerodha back into the dashboard.\n"
                "  Hokage will NOT take any trades until you complete this step.\n"
                "  Cause: %s\n"
                + "=" * 70, e)
            raise RuntimeError(f"Authentication failed: {e}")

    def _say_once(self, reason: str, level: int, message: str, *args) -> None:
        """Say it, then hold that diagnosis for ten minutes.

        The health loop calls `connect()` once a minute. An outage therefore
        printed the same block sixty times an hour, which is how a log stops
        being read - and the one line that matters is always the FIRST.
        Per reason, so a transport outage that turns into a real expiry still
        announces itself immediately.
        """
        try:
            said = getattr(self, "_said_at", None)
            if said is None:
                said = {}
                self._said_at = said
            now = time.monotonic()
            last = said.get(reason)
            if last is not None and now - last < _SAY_AGAIN_AFTER_SECONDS:
                return
            said[reason] = now
        except Exception:
            pass
        logger.log(level, message, *args)


    def try_reconnect(self) -> bool:
        """Re-read the stored credentials and re-establish the session.

        The access token is read exactly ONCE, inside connect(). A process that
        booted with an expired token therefore stays dead for its whole life:
        connect() fails, _kite is left None, and every later call raises
        "Venue is not connected." Logging in afterwards rewrites the .env, the
        environment and the keyring but touches nothing in this object, so
        Hokage went on refusing every scan while the dashboard and the health
        score both looked fine. On 2026-08-05 that cost a restart the commander
        had no way of knowing he needed.

        get_secret() reads os.environ before the keyring and caches nothing, so
        calling connect() again is genuinely enough to pick up a fresh token.

        Returns True when the session is live afterwards. Never raises: callers
        are recovery paths, and a failed recovery must not take down the loop
        that is trying to recover.
        """
        try:
            self.connect()
            return self._connection_state == ConnectionState.CONNECTED
        except Exception as exc:
            import logging as _logging
            _logging.getLogger("Hokage.KiteConnection").debug(
                f"Reconnect attempt failed (still no valid session): {exc}"
            )
            return False

    def disconnect(self) -> ConnectionStatus:
        """Disconnect and clear current session."""
        self._kite = None
        self._connection_state = ConnectionState.DISCONNECTED
        return ConnectionStatus(
            state=ConnectionState.DISCONNECTED,
            last_checked=utc_now(),
            latency_ms=0.0,
            message="Disconnected from Zerodha Kite Connect."
        )

    def get_status(self) -> ConnectionStatus:
        """Get current connection state diagnostics."""
        return ConnectionStatus(
            state=self._connection_state,
            last_checked=utc_now(),
            message="Session active." if self._connection_state == ConnectionState.CONNECTED else "Session inactive."
        )
