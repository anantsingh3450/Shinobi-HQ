import sys
import os
import time
import subprocess
import pyotp
import requests
from urllib.parse import urlparse, parse_qs
from dotenv import load_dotenv

sys.path.append(os.path.join(os.getcwd(), 'src'))
from integrations.brokers.secrets import SecretManager
from kiteconnect import KiteConnect

print("=========================================")
print("🤖 HOKAGE GHOST-LOGIN SEQUENCE V3")
print("=========================================")

load_dotenv()
USERNAME = os.getenv("ZERODHA_USERNAME")
PASSWORD = os.getenv("ZERODHA_PASSWORD")
TOTP_SECRET = os.getenv("ZERODHA_TOTP_SECRET")

mgr = SecretManager()
api_key = mgr.get_secret("api_key", broker="zerodha")
api_secret = mgr.get_secret("api_secret", broker="zerodha")

if not USERNAME or not TOTP_SECRET:
    print("❌ ERROR: Username or TOTP Secret missing from .env file!")
    sys.exit()

session = requests.Session()

try:
    print("[1/4] Injecting credentials into Zerodha mainframe...")
    login_res = session.post("https://kite.zerodha.com/api/login", data={"user_id": USERNAME, "password": PASSWORD})
    
    if login_res.json().get("status") != "success":
        print(f"❌ Login Error: {login_res.json().get('message')}")
        sys.exit()
        
    req_id = login_res.json()["data"]["request_id"]
    
    print("[2/4] Generating Time-Based OTP internally...")
    totp_pin = pyotp.TOTP(TOTP_SECRET).now()
    
    # FIX: We removed the "twofa_type" parameter here. Zerodha only wants the value!
    twofa_res = session.post("https://kite.zerodha.com/api/twofa", data={
        "user_id": USERNAME,
        "request_id": req_id,
        "twofa_value": totp_pin
    })
    
    if twofa_res.json().get("status") != "success":
        print(f"❌ 2FA Error: {twofa_res.json().get('message')}")
        sys.exit()

    print("[3/4] Performing secure API handshake...")
    kite = KiteConnect(api_key=api_key)
    
    request_token = None
    try:
        # Properly catching the URL after the redirect completes
        res = session.get(kite.login_url(), allow_redirects=True, timeout=5)
        if "request_token=" in res.url:
            parsed = urlparse(res.url)
            request_token = parse_qs(parsed.query).get('request_token', [None])[0]
    except Exception as e:
        # If your local system rejects the connection, the token gets trapped in the error data
        if hasattr(e, 'request') and e.request and hasattr(e.request, 'url') and "request_token=" in str(e.request.url):
            parsed = urlparse(e.request.url)
            request_token = parse_qs(parsed.query).get('request_token', [None])[0]
        else:
            e_msg = str(e)
            if "request_token=" in e_msg:
                request_token = e_msg.split('request_token=')[1].split('&')[0].replace("'", "").replace("\"", "")

    if not request_token:
        print("❌ ERROR: Could not find request_token in the redirect.")
        sys.exit()

    print("[4/4] Exchanging for Master Access Token...")
    session_data = kite.generate_session(request_token, api_secret=api_secret)
    final_access_token = session_data["access_token"]
    
    mgr.set_secret("access_token", final_access_token, broker="zerodha")
    print("\n✅ VAULT SECURED: Master Token locked.")
    print("🚀 IGNITING HOKAGE MAIN ENGINE...")
    time.sleep(2)
    
    # Starts the main dashboard!
    subprocess.Popen(["python", "start.py"])

except Exception as e:
    print(f"\n❌ SCRIPT CRASHED: {e}")