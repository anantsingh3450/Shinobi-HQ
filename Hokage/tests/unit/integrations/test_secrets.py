from __future__ import annotations

import json
from pathlib import Path
from integrations.brokers.secrets import SecretManager


def test_secret_manager_test_mode_isolation(tmp_path: Path):
    """Verify that SecretManager operates with mock storage in test mode and isolates the real keyring."""
    secrets_file = tmp_path / "secrets.json"
    
    # Instantiate with test_mode=True
    sm = SecretManager(secrets_file_path=secrets_file, test_mode=True)
    assert sm.test_mode is True
    
    # Set and get secret
    sm.set_secret("api_key", "my_secret_key", broker="zerodha")
    assert sm.get_secret("api_key", broker="zerodha") == "my_secret_key"
    
    # Verify that it is in the mock keyring, not the real OS keyring
    # (Since we are in test mode, sm._mock_keyring must contain the value)
    assert sm._mock_keyring["zerodha:api_key"] == "my_secret_key"


def test_secret_manager_migration(tmp_path: Path):
    """Verify that plaintext credentials in secrets.json are migrated on initialization and masked."""
    secrets_file = tmp_path / "secrets.json"
    
    # Bootstrap a secrets file containing plaintext credentials
    plaintext_data = {
        "api_key": "actual_api_key_123",
        "api_secret": "actual_api_secret_456",
        "access_token": "YOUR_ACCESS_TOKEN"  # placeholder, should NOT migrate
    }
    with secrets_file.open("w", encoding="utf-8") as fh:
        json.dump(plaintext_data, fh, indent=2)
        
    # Initialize SecretManager (which runs migration on startup)
    sm = SecretManager(secrets_file_path=secrets_file, test_mode=True)
    
    # 1. Plaintext secrets must be migrated to the secure keyring (mock keyring in tests)
    assert sm.get_secret("api_key") == "actual_api_key_123"
    assert sm.get_secret("api_secret") == "actual_api_secret_456"
    assert sm.get_secret("access_token") is None  # Placeholder not migrated
    
    # 2. The plaintext secrets in the JSON file must be masked as 'MIGRATED_TO_KEYRING'
    with secrets_file.open("r", encoding="utf-8") as fh:
        updated_data = json.load(fh)
        
    assert updated_data["api_key"] == "MIGRATED_TO_KEYRING"
    assert updated_data["api_secret"] == "MIGRATED_TO_KEYRING"
    assert updated_data["access_token"] == "YOUR_ACCESS_TOKEN"  # Unchanged


def test_secret_manager_rollback(tmp_path: Path):
    """Verify the rollback strategy: restores credentials from Keyring to plaintext secrets.json and cleans Keyring."""
    secrets_file = tmp_path / "secrets.json"
    
    # 1. Setup a migrated state
    migrated_data = {
        "api_key": "MIGRATED_TO_KEYRING",
        "api_secret": "MIGRATED_TO_KEYRING",
        "access_token": "YOUR_ACCESS_TOKEN"
    }
    with secrets_file.open("w", encoding="utf-8") as fh:
        json.dump(migrated_data, fh, indent=2)
        
    sm = SecretManager(secrets_file_path=secrets_file, test_mode=True)
    
    # Load secrets into the keyring (mock keyring)
    sm.set_secret("api_key", "real_key_val")
    sm.set_secret("api_secret", "real_secret_val")
    
    # Verify they are in the keyring
    assert sm.get_secret("api_key") == "real_key_val"
    assert sm.get_secret("api_secret") == "real_secret_val"
    
    # 2. Execute Rollback
    sm.rollback_to_json(broker="zerodha")
    
    # 3. Verify secrets.json has plaintext restored
    with secrets_file.open("r", encoding="utf-8") as fh:
        restored_data = json.load(fh)
        
    assert restored_data["api_key"] == "real_key_val"
    assert restored_data["api_secret"] == "real_secret_val"
    assert restored_data["access_token"] == "YOUR_ACCESS_TOKEN"  # Unchanged
    
    # 4. Verify secrets are deleted from keyring
    assert sm.get_secret("api_key") is None
    assert sm.get_secret("api_secret") is None


def test_secret_manager_future_broker_support(tmp_path: Path):
    """Verify that secrets for different brokers do not clash and are stored independently."""
    secrets_file = tmp_path / "secrets.json"
    sm = SecretManager(secrets_file_path=secrets_file, test_mode=True)
    
    # Store api_key for zerodha and binance
    sm.set_secret("api_key", "zerodha_key", broker="zerodha")
    sm.set_secret("api_key", "binance_key", broker="binance")
    
    assert sm.get_secret("api_key", broker="zerodha") == "zerodha_key"
    assert sm.get_secret("api_key", broker="binance") == "binance_key"
    
    # Delete zerodha key, binance key must remain
    sm.delete_secret("api_key", broker="zerodha")
    assert sm.get_secret("api_key", broker="zerodha") is None
    assert sm.get_secret("api_key", broker="binance") == "binance_key"


def test_secret_manager_load_secrets_fallback(tmp_path: Path):
    """Verify load_secrets returns the combined actual credentials while maintaining template fallback."""
    secrets_file = tmp_path / "secrets.json"
    
    # Write template to secrets.json
    template = {
        "api_key": "MIGRATED_TO_KEYRING",
        "api_secret": "YOUR_API_SECRET",  # missing / placeholder
        "access_token": "MIGRATED_TO_KEYRING"
    }
    with secrets_file.open("w", encoding="utf-8") as fh:
        json.dump(template, fh, indent=2)
        
    sm = SecretManager(secrets_file_path=secrets_file, test_mode=True)
    sm.set_secret("api_key", "my_key")
    sm.set_secret("access_token", "my_token")
    
    # load_secrets should return resolved keyring values + placeholders for missing ones
    secrets = sm.load_secrets()
    assert secrets["api_key"] == "my_key"
    assert secrets["api_secret"] == "YOUR_API_SECRET"
    assert secrets["access_token"] == "my_token"
