import sys
import os
sys.path.append(os.path.join(os.getcwd(), 'src'))

try:
    from integrations.brokers.secrets import SecretManager
    mgr = SecretManager()
    print("SUCCESS: The Vault manager is awake.")
    print(f"Looking for keys at: {mgr.secrets_file_path}")
    
    # Check what is currently loaded
    secrets = mgr.load_secrets()
    print("\n--- Current Status ---")
    for key, value in secrets.items():
        if "YOUR_" in str(value) or value == "MIGRATED_TO_KEYRING":
            print(f"  {key}: Not configured yet (Empty)")
        else:
            print(f"  {key}: Securely locked in!")
except Exception as e:
    print(f"\nStatus: {e}")