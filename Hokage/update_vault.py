import sys
import os
sys.path.append(os.path.join(os.getcwd(), 'src'))

try:
    from integrations.brokers.secrets import SecretManager
    mgr = SecretManager()
    
    print("="*40)
    print("       HOKAGE VAULT UPDATER       ")
    print("="*40)
    print("Note: If you don't want to change a value, just press Enter.\n")
    
    new_key = input("Paste your API Key (or press Enter to skip): ").strip()
    new_token = input("Paste today's Access Token (or press Enter to skip): ").strip()
    
    if new_key:
        mgr.set_secret("api_key", new_key, broker="zerodha")
        print("⚡ API Key successfully updated in secure storage.")
        
    if new_token:
        mgr.set_secret("access_token", new_token, broker="zerodha")
        print("⚡ Access Token successfully updated in secure storage.")
        
    print("\n[Done] Vault updated. Run 'python test_broker.py' to verify.")
    print("="*40)

except Exception as e:
    print(f"\nAn error occurred while updating the Vault: {e}")