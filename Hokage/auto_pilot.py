import os
import sys
import time
import requests
import subprocess
from urllib.parse import urlparse, parse_qs
from dotenv import load_dotenv

# Silence warnings
import logging
logging.disable(logging.CRITICAL)

sys.path.append(os.path.join(os.getcwd(), 'src'))
from integrations.brokers.secrets import SecretManager
from kiteconnect import KiteConnect

# Load Environment Variables
load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") 
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": text})

def get_latest_telegram_message():
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?offset=-1"
    try:
        response = requests.get(url).json()
        if response.get("result"):
            return response["result"][0]["message"]["text"]
    except Exception:
        pass
    return ""

print("=========================================")
print("🤖 HOKAGE MORNING AUTO-PILOT INITIATED 🤖")
print("=========================================")

# 1. Get Zerodha Keys
mgr = SecretManager()
api_key = mgr.get_secret("api_key", broker="zerodha")
api_secret = mgr.get_secret("api_secret", broker="zerodha")

if not api_key or not BOT_TOKEN or not CHAT_ID:
    print("Missing API keys or Telegram credentials in .env file.")
    sys.exit()

kite = KiteConnect(api_key=api_key)
login_url = kite.login_url()

# 2. Dispatch to Telegram
dispatch_msg = (
    "☀️ Good morning, Elder.\n\n"
    "Market prep sequence initiated. Please authenticate today's session:\n\n"
    f"{login_url}\n\n"
    "Reply to this message with the final redirect link."
)
send_telegram_message(dispatch_msg)
print("\n[+] Login link dispatched to your Telegram.")
print("[+] Awaiting your reply with the final link...")

# 3. Listen for the token
token_found = False
last_msg = get_latest_telegram_message()

while not token_found:
    time.sleep(3) # Check every 3 seconds
    current_msg = get_latest_telegram_message()
    
    if current_msg != last_msg and "request_token=" in current_msg:
        print("\n[+] Link received from Telegram! Extracting token...")
        
        # Parse the URL to get the request_token
        parsed_url = urlparse(current_msg)
        request_token = parse_qs(parsed_url.query).get('request_token', [None])[0]
        
        if request_token:
            try:
                # Generate new access token
                data = kite.generate_session(request_token, api_secret=api_secret)
                access_token = data["access_token"]
                
                # Lock in Vault
                mgr.set_secret("access_token", access_token, broker="zerodha")
                
                success_msg = "✅ Authentication confirmed. Token locked in Vault. Booting Main Engine..."
                send_telegram_message(success_msg)
                print(success_msg)
                token_found = True
                
                # Launch Antigravity Main Engine
                print("\n🚀 IGNITING MAIN HOKAGE ENGINE 🚀")
                time.sleep(2)
                subprocess.Popen(["python", "start.py"])
                sys.exit()
                
            except Exception as e:
                error_msg = f"❌ Token generation failed: {e}"
                send_telegram_message(error_msg)
                print(error_msg)
                last_msg = current_msg
        else:
            print("Invalid link format. Still waiting...")
            last_msg = current_msg