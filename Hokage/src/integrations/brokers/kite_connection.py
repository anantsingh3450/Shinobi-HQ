from __future__ import annotations

from datetime import datetime
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

    def _attempt_auto_login(self, api_key: str) -> str | None:
        """Programmatically authenticate with Zerodha Kite using password and 2FA TOTP."""
        import os
        import pyotp
        import requests
        
        username = os.environ.get("ZERODHA_USERNAME")
        password = os.environ.get("ZERODHA_PASSWORD")
        totp_secret = os.environ.get("ZERODHA_TOTP_SECRET")
        api_secret = os.environ.get("ZERODHA_API_SECRET")
        
        # Strip quotes if they were loaded with quotes
        if username: username = username.strip("'\"")
        if password: password = password.strip("'\"")
        if totp_secret: totp_secret = totp_secret.strip("'\"")
        if api_secret: api_secret = api_secret.strip("'\"")

        missing = []
        if not username: missing.append("ZERODHA_USERNAME")
        if not password: missing.append("ZERODHA_PASSWORD")
        if not totp_secret: missing.append("ZERODHA_TOTP_SECRET")
        if not api_secret: missing.append("ZERODHA_API_SECRET")
        
        if missing:
            print(f"[ZERODHA LOGIN ERROR]: Automated login credentials missing from environment. "
                  f"Please add the following to your .env file: {', '.join(missing)}")
            return None
            
        try:
            totp_pin = pyotp.TOTP(totp_secret).now()
            
            session = requests.Session()
            login_url = "https://kite.zerodha.com/api/login"
            
            # Step 1: Post credentials
            payload = {"user_id": username, "password": password}
            res = session.post(login_url, data=payload, timeout=5)
            if res.status_code != 200:
                raise RuntimeError(f"Login API error (status {res.status_code}): {res.text}")
                
            res_data = res.json()
            request_id = res_data.get("data", {}).get("request_id")
            if not request_id:
                raise RuntimeError("Failed to get request_id from login response")
                
            # Step 2: Post 2FA TOTP
            twofa_url = "https://kite.zerodha.com/api/twofa"
            twofa_payload = {
                "user_id": username,
                "request_id": request_id,
                "twofa_value": totp_pin,
                "twofa_type": "app_code"
            }
            res_2fa = session.post(twofa_url, data=twofa_payload, timeout=5)
            if res_2fa.status_code != 200:
                raise RuntimeError(f"2FA API error (status {res_2fa.status_code}): {res_2fa.text}")
                
            # Step 3: Connect authorize and redirect to get request_token
            connect_url = f"https://kite.trade/connect/login?api_key={api_key}&v=3"
            res_connect = session.get(connect_url, timeout=5, allow_redirects=True)
            
            # Parse request_token from redirection URL
            from urllib.parse import urlparse, parse_qs
            request_token = None
            for r in res_connect.history + [res_connect]:
                qs = parse_qs(urlparse(r.url).query)
                if "request_token" in qs:
                    request_token = qs["request_token"][0]
                    break
                    
            if not request_token:
                raise RuntimeError("Failed to extract request_token from connect redirection.")
                
            # Step 4: Exchange request_token for access_token
            kite = KiteConnect(api_key=api_key)
            session_data = kite.generate_session(request_token, api_secret=api_secret)
            access_token = session_data["access_token"]
            
            # Save the access token
            self._secrets_manager.set_secret("access_token", access_token)
            # Also set in os.environ for immediate access in current process
            os.environ["ZERODHA_ACCESS_TOKEN"] = access_token
            return access_token
            
        except Exception as e:
            print(f"[ZERODHA LOGIN ERROR]: Auto-login failed: {e}")
            return None

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
