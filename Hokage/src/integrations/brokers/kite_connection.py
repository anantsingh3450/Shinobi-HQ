from __future__ import annotations

from kiteconnect import KiteConnect
from integrations.brokers.secrets import SecretManager
from integrations.brokers.models import ConnectionState, ConnectionStatus, utc_now


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
            import logging as _logging
            _logging.getLogger("Hokage.KiteConnection").critical(
                "\n" + "=" * 70 + "\n"
                "⚠️  ZERODHA SESSION TOKEN EXPIRED OR INVALID ⚠️\n"
                "Hokage cannot fetch live market data without a valid session.\n"
                "ACTION REQUIRED:\n"
                "  1. Open the Hokage Dashboard at http://127.0.0.1:5000\n"
                "  2. Click 'Login to Zerodha' and complete authentication.\n"
                "  3. Paste the redirect URL from Zerodha back into the dashboard.\n"
                "  Hokage will NOT take any trades until you complete this step.\n"
                + "=" * 70
            )
            raise RuntimeError(f"Authentication failed: {e}")


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
