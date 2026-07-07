from __future__ import annotations

import json
import logging
import os
import platform
import sys
from pathlib import Path
import keyring

logger = logging.getLogger("Hokage.SecretManager")


class SecretManager:
    """Manages secure loading of broker credentials using OS-native keyring or in-memory fallback for testing."""

    def __init__(self, secrets_file_path: Path | None = None, test_mode: bool = False) -> None:
        """Initialize the SecretManager.

        Args:
            secrets_file_path: Optional custom path override. If None, resolves
                               automatically based on the host operating system.
            test_mode: Explicit flag to force isolated in-memory credentials for tests.
        """
        self._secrets_file_path = secrets_file_path or self.resolve_default_secrets_path()
        # Detect test mode: explicitly requested, running under pytest, or environment override
        self.test_mode = (
            test_mode
            or ("pytest" in sys.modules)
            or (os.environ.get("HOKAGE_TEST_MODE") == "true")
        )

        if self.test_mode:
            # Use an isolated in-memory dictionary instead of OS native keyring
            self._mock_keyring = {}
            logger.info("SecretManager initialized in TEST MODE with isolated mock credential storage.")
        else:
            logger.info("SecretManager initialized with OS-native keyring storage.")

        # Load environment variables from local .env wrapper at the project root
        self._load_dotenv()

        # Run controlled migration if the JSON file contains plaintext secrets
        self._migrate_if_needed()

    def _load_dotenv(self) -> None:
        """Load variables from secure local .env configuration file if present."""
        dotenv_path = Path(__file__).resolve().parents[3] / ".env"
        if dotenv_path.exists():
            try:
                with dotenv_path.open("r", encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if "=" in line:
                            k, v = line.split("=", 1)
                            k = k.strip()
                            v = v.strip()
                            # Strip quotes if present
                            if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                                v = v[1:-1]
                            os.environ[k] = v
                logger.info(f"Loaded variables from secure local env wrapper: {dotenv_path}")
            except Exception as e:
                logger.error(f"Failed to load environment variables from {dotenv_path}: {e}")

    @property
    def secrets_file_path(self) -> Path:
        """The resolved path to the secrets.json file."""
        return self._secrets_file_path

    @staticmethod
    def resolve_default_secrets_path() -> Path:
        """Resolve the canonical platform-specific secret location on the host."""
        system = platform.system()
        if system == "Windows":
            appdata = os.environ.get("APPDATA")
            if appdata:
                return Path(appdata) / "Hokage" / "secrets.json"
            return Path.home() / "AppData" / "Roaming" / "Hokage" / "secrets.json"
        elif system == "Darwin":  # macOS
            return Path.home() / "Library" / "Application Support" / "Hokage" / "secrets.json"
        else:  # Linux / Unix / other
            config_home = os.environ.get("XDG_CONFIG_HOME")
            if config_home:
                return Path(config_home) / "hokage" / "secrets.json"
            return Path.home() / ".config" / "hokage" / "secrets.json"

    def _migrate_if_needed(self) -> None:
        """Migrate any plaintext credentials from secrets.json to the secure keyring."""
        if not self._secrets_file_path.exists():
            return

        try:
            with self._secrets_file_path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:
            # If JSON is corrupt or unreadable, we skip migration to avoid crashing on initialization
            return

        if not isinstance(data, dict):
            return

        migrated_any = False
        placeholders = {"YOUR_API_KEY", "YOUR_API_SECRET", "YOUR_ACCESS_TOKEN", "MIGRATED_TO_KEYRING"}

        for key, val in data.items():
            val_str = str(val).strip()
            # If it's a real secret and not a placeholder/marker, migrate it
            if val_str and val_str not in placeholders:
                self.set_secret(key, val_str, broker="zerodha")
                data[key] = "MIGRATED_TO_KEYRING"
                migrated_any = True

        if migrated_any:
            # Rewrite secrets.json with values masked as 'MIGRATED_TO_KEYRING'
            try:
                with self._secrets_file_path.open("w", encoding="utf-8") as fh:
                    json.dump(data, fh, indent=2)
                logger.info("Plaintext credentials migrated to secure OS-native credential storage.")
            except Exception as e:
                logger.error(f"Failed to update secrets.json after migration: {e}")

    def load_secrets(self) -> dict[str, str]:
        """Load and return credentials. Maintains backward compatibility with legacy calls.

        Retrieves credentials from keyring, falling back to secrets.json placeholders if missing.
        """
        # Bootstrap a secure template if secrets.json doesn't exist
        if not self._secrets_file_path.exists():
            self._secrets_file_path.parent.mkdir(parents=True, exist_ok=True)
            template = {
                "api_key": "YOUR_API_KEY",
                "api_secret": "YOUR_API_SECRET",
                "access_token": "YOUR_ACCESS_TOKEN",
            }
            with self._secrets_file_path.open("w", encoding="utf-8") as fh:
                json.dump(template, fh, indent=2)
            raise FileNotFoundError(
                f"Secrets file not found. Created a secure credential template at {self._secrets_file_path}. "
                "Please fill in your API key, secret, and access token."
            )

        # For backward compatibility, load structure from JSON, then fill actual values from Keyring
        with self._secrets_file_path.open("r", encoding="utf-8") as fh:
            try:
                data = json.load(fh)
                if not isinstance(data, dict):
                    return {}

                resolved = {}
                for key in data.keys():
                    secret_val = self.get_secret(key, broker="zerodha")
                    if secret_val:
                        resolved[key] = secret_val
                    else:
                        # Fallback to whatever is in the JSON file if not in keyring (e.g. placeholders)
                        resolved[key] = str(data[key])
                return resolved
            except json.JSONDecodeError as e:
                raise ValueError(f"Secrets file is not valid JSON: {e}")

    def get_secret(self, key: str, broker: str = "zerodha") -> str | None:
        """Retrieve a specific secret value by key, returning None if not found or placeholder."""
        # 1. Prioritize environment variable configuration (.env/os.environ)
        import sys
        if not self.test_mode and "pytest" not in sys.modules:
            env_key = f"{broker.upper()}_{key.upper()}"
            if env_key in os.environ:
                val = os.environ[env_key]
                if val not in (None, "", f"YOUR_{key.upper()}", "YOUR_API_KEY", "YOUR_API_SECRET", "YOUR_ACCESS_TOKEN", "MIGRATED_TO_KEYRING"):
                    return val

        # 2. Keyring lookup fallback
        username = f"{broker}:{key}"

        if self.test_mode:
            val = self._mock_keyring.get(username)
        else:
            try:
                val = keyring.get_password("Hokage", username)
            except Exception as e:
                logger.error(f"Failed to fetch secret from keyring: {e}")
                val = None

        if val in (None, "", "YOUR_API_KEY", "YOUR_API_SECRET", "YOUR_ACCESS_TOKEN", "MIGRATED_TO_KEYRING"):
            return None
        return val

    def set_secret(self, key: str, value: str, broker: str = "zerodha") -> None:
        """Save a specific secret value into the secure vault."""
        username = f"{broker}:{key}"

        if self.test_mode:
            self._mock_keyring[username] = value
        else:
            try:
                keyring.set_password("Hokage", username, value)
            except Exception as e:
                raise RuntimeError(f"Failed to write secret to OS keyring: {e}")

        # Sync back to secrets.json if it exists to maintain structure
        if self._secrets_file_path.exists():
            try:
                with self._secrets_file_path.open("r", encoding="utf-8") as fh:
                    data = json.load(fh)
                if isinstance(data, dict):
                    data[key] = "MIGRATED_TO_KEYRING"
                    with self._secrets_file_path.open("w", encoding="utf-8") as fh:
                        json.dump(data, fh, indent=2)
            except Exception:
                pass

    def delete_secret(self, key: str, broker: str = "zerodha") -> None:
        """Delete a specific secret from the secure vault."""
        username = f"{broker}:{key}"

        if self.test_mode:
            self._mock_keyring.pop(username, None)
        else:
            try:
                keyring.delete_password("Hokage", username)
            except Exception:
                pass

        # Sync back to secrets.json if it exists
        if self._secrets_file_path.exists():
            try:
                with self._secrets_file_path.open("r", encoding="utf-8") as fh:
                    data = json.load(fh)
                if isinstance(data, dict) and key in data:
                    data[key] = "YOUR_" + key.upper()
                    with self._secrets_file_path.open("w", encoding="utf-8") as fh:
                        json.dump(data, fh, indent=2)
            except Exception:
                pass

    def rollback_to_json(self, broker: str = "zerodha") -> None:
        """Execute rollback strategy: retrieves all secrets from Keyring and writes them back to secrets.json."""
        if not self._secrets_file_path.exists():
            logger.warning("No secrets.json file exists. Rollback cannot restore original keys.")
            return

        try:
            with self._secrets_file_path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as e:
            raise RuntimeError(f"Cannot read secrets.json for rollback: {e}")

        if not isinstance(data, dict):
            return

        rolled_back = []
        for key in data.keys():
            val = self.get_secret(key, broker=broker)
            if val:
                data[key] = val
                rolled_back.append(key)

        # Write plaintext secrets back to the JSON file
        try:
            with self._secrets_file_path.open("w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
        except Exception as e:
            raise RuntimeError(f"Failed to write secrets back to JSON: {e}")

        # Delete secrets from Keyring only AFTER successful write to JSON
        for key in rolled_back:
            username = f"{broker}:{key}"
            if self.test_mode:
                self._mock_keyring.pop(username, None)
            else:
                try:
                    keyring.delete_password("Hokage", username)
                except Exception:
                    pass

        logger.info(f"Rollback complete. Restored {len(rolled_back)} secrets to plaintext in secrets.json.")
