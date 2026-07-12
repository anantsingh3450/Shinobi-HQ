import sys
import os
import urllib.parse
import subprocess
sys.path.append(os.path.join(os.getcwd(), 'src'))
from integrations.brokers.secrets import SecretManager
from kiteconnect import KiteConnect

mgr = SecretManager()
api_key = mgr.get_secret("api_key", broker="zerodha")
api_secret = mgr.get_secret("api_secret", broker="zerodha")

print("=========================================")
print(" MANUAL LOGIN OVERRIDE")
print("=========================================")
print("\nSTEP 1: Hold 'Ctrl' and click this link to open it in your browser:")
print(f"https://kite.trade/connect/login?v=3&api_key={api_key}")

full_url = input("\nSTEP 2: Log in. When you hit the broken page, paste the ENTIRE web address here and press Enter: ").strip()

try:
    if "request_token=" in full_url:
        parsed = urllib.parse.urlparse(full_url)
        request_token = urllib.parse.parse_qs(parsed.query).get('request_token', [None])[0]
    else:
        request_token = full_url

    kite = KiteConnect(api_key=api_key)
    session_data = kite.generate_session(request_token, api_secret=api_secret)
    final_access_token = session_data["access_token"]
    
    mgr.set_secret("access_token", final_access_token, broker="zerodha")
    
    print("\n✅ SUCCESS: Token locked in Vault! Booting main engine...")
    subprocess.Popen(["python", "start.py"])
except Exception as e:
    print(f"\n❌ ERROR: {e}")