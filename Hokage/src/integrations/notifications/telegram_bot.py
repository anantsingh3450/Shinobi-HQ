from __future__ import annotations
import os
import time
import logging
import threading
from datetime import datetime, timezone
import requests
from urllib.parse import urlparse, parse_qs
import pyotp
from integrations.brokers.secrets import SecretManager
from kiteconnect import KiteConnect
from integrations.brokers.session_manager import KolkataTime
from integrations.llm.processor import LLMProcessor

logger = logging.getLogger("Hokage.TelegramBot")

class TelegramBotUplink:
    """Manages Telegram bot communications, TOTP token requests, fills/exits and EOD updates."""

    def __init__(self, bot_token: str | None = None, chat_id: str | None = None) -> None:
        self.bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID")
        self.enabled = bool(self.bot_token and self.chat_id)
        self._thread = None
        self._stop_event = threading.Event()
        self._last_totp_request_date = None
        self._last_confirmation_date = None
        self._last_update_id = 0
        self.latest_totp = None
        self.llm_processor = LLMProcessor()
        # Control-command handler (set by AutonomousTradingBot). Must expose
        # handle_remote_command(command: str) -> str.
        self.command_handler = None
    def start(self) -> None:
        """Start the background polling thread."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, name="HokageTelegramBotLoop", daemon=True)
        self._thread.start()
        logger.info("Telegram background thread started.")

    def stop(self) -> None:
        """Stop the background polling thread gracefully."""
        if self._thread is None:
            return
        self._stop_event.set()
        self._thread.join(timeout=5.0)
        self._thread = None
        logger.info("Telegram background thread stopped.")

    def send_message(self, text: str) -> bool:
        """Send a message to the configured Telegram chat."""
        if not self.enabled:
            logger.info(f"[MOCK TELEGRAM OUTBOX]: {text}")
            return True
            
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "Markdown"
        }
        try:
            res = requests.post(url, json=payload, timeout=10)
            if res.status_code == 200:
                return True
            logger.error(f"Telegram API error {res.status_code}: {res.text}")
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")
        return False

    def notify_fill(self, trade_details: dict) -> None:
        """Push a real-time order fill notification."""
        symbol = trade_details.get("symbol", "N/A")
        side = trade_details.get("side", "N/A")
        qty = trade_details.get("qty", 0.0)
        price = trade_details.get("price", 0.0)
        msg = (
            f"⚡ *TRADE FILL ALERT* ⚡\n"
            f"• *Asset*: {symbol}\n"
            f"• *Side*: {side}\n"
            f"• *Qty*: {qty}\n"
            f"• *Execution Price*: ₹{price:.2f}"
        )
        self.send_message(msg)

    def notify_stop_loss(self, trade_details: dict) -> None:
        """Push a stop-loss execution alert."""
        symbol = trade_details.get("symbol", "N/A")
        side = trade_details.get("side", "N/A")
        price = trade_details.get("price", 0.0)
        pnl = trade_details.get("pnl", 0.0)
        msg = (
            f"🛑 *STOP-LOSS HIT ALERT* 🛑\n"
            f"• *Asset*: {symbol}\n"
            f"• *Position Closed*: {side}\n"
            f"• *Price*: ₹{price:.2f}\n"
            f"• *PnL*: ₹{pnl:+.2f}"
        )
        self.send_message(msg)

    def send_eod_summary(self, pnl_details: dict) -> None:
        """Send End-of-Day P&L summary."""
        date_str = datetime.now().strftime("%Y-%m-%d")
        realized_pnl = pnl_details.get("realized_pnl", 0.0)
        unrealized_pnl = pnl_details.get("unrealized_pnl", 0.0)
        total_equity = pnl_details.get("total_equity", 0.0)
        trades_count = pnl_details.get("trades_count", 0)
        msg = (
            f"📊 *EOD P&L SUMMARY ({date_str})* 📊\n"
            f"• *Realized P&L*: ₹{realized_pnl:+.2f}\n"
            f"• *Unrealized P&L*: ₹{unrealized_pnl:+.2f}\n"
            f"• *Total Portfolio Equity*: ₹{total_equity:.2f}\n"
            f"• *Trades Completed Today*: {trades_count}"
        )
        self.send_message(msg)

    def notify_entry(self, symbol: str, cmp: float, target: float, edge: float) -> None:
        """Send a real-time entry notification."""
        msg = (
            f"🚀 *ENTERING POSITION: {symbol}*\n"
            f"• *CMP*: {cmp:.2f}\n"
            f"• *Target*: {target:.2f}\n"
            f"• *ML Edge Score*: {edge:.1f}%\n\n"
            "Entering the probability field. Outcome is unknown; risk is defined."
        )
        self.send_message(msg)

    def notify_exit(self, symbol: str, price: float, reason: str) -> None:
        """Send a real-time exit notification."""
        msg = (
            f"🛑 *EXITING POSITION: {symbol}*\n"
            f"• *Exit Price*: {price:.2f}\n"
            f"• *Reason*: {reason}\n\n"
            "Position closed. Logging autopsy for pattern analysis."
        )
        self.send_message(msg)

    def _run_loop(self) -> None:
        tz = KolkataTime()
        while not self._stop_event.is_set():
            try:
                # 1. Handle daily 06:30 AM IST TOTP request
                ist_now = datetime.now(timezone.utc).astimezone(tz)
                current_date_str = ist_now.strftime("%Y-%m-%d")
                
                if ist_now.hour > 6 or (ist_now.hour == 6 and ist_now.minute >= 30):
                    if self._last_totp_request_date != current_date_str:
                        self._last_totp_request_date = current_date_str
                        try:
                            mgr = SecretManager()
                            api_key = mgr.get_secret("api_key", broker="zerodha")
                            totp_secret = os.getenv("ZERODHA_TOTP_SECRET")
                            
                            login_url = f"https://kite.trade/connect/login?v=3&api_key={api_key}"
                            totp_msg = ""
                            if totp_secret:
                                totp_pin = pyotp.TOTP(totp_secret).now()
                                totp_msg = f"\n• *Live TOTP*: `{totp_pin}` (Tap to copy)"
                            
                            self.send_message(
                                "⚠️ *ZERODHA LIVE AUTONOMOUS LOGIN REQUIRED* ⚠️\n"
                                f"1. Click here to login: [Kite Login]({login_url}){totp_msg}\n"
                                "2. After you log in, copy the entire broken URL and reply with: `/token URL`"
                            )
                        except Exception as e:
                            logger.error(f"Failed to generate morning login brief: {e}")

                # 1.5 Handle daily 09:00 AM IST Connection Confirmation
                if ist_now.hour >= 9:
                    if self._last_confirmation_date != current_date_str:
                        self._last_confirmation_date = current_date_str
                        mgr = SecretManager()
                        acc_token = mgr.get_secret("access_token", broker="zerodha")
                        if acc_token:
                            self.send_message("✅ *Login Successful* - Broker Connected. Execution engines standing by.")
                        else:
                            self.send_message("🚨 *Login Missing* - Autonomous execution halted. Please login via Dashboard or /token command.")
                
                # 2. Check for updates from Telegram
                if self.enabled:
                    self._check_telegram_updates()
                    
            except Exception as e:
                logger.error(f"Error in Telegram Uplink run loop: {e}")
                
            time.sleep(5.0)

    def _check_telegram_updates(self) -> None:
        url = f"https://api.telegram.org/bot{self.bot_token}/getUpdates"
        params = {"offset": self._last_update_id + 1, "timeout": 2}
        try:
            res = requests.get(url, params=params, timeout=5)
            if res.status_code != 200:
                return
            data = res.json()
            for update in data.get("result", []):
                self._last_update_id = update.get("update_id", self._last_update_id)
                msg = update.get("message", {})
                chat = msg.get("chat", {})
                
                # Make sure message is from the configured chat ID
                if str(chat.get("id")) == str(self.chat_id):
                    text = msg.get("text", "").strip()
                    if text.startswith("/token "):
                        # Extract token
                        request_token = text.split("/token ", 1)[1].strip()
                        if "request_token=" in request_token:
                            try:
                                parsed = urlparse(request_token)
                                qs = parse_qs(parsed.query)
                                if 'request_token' in qs:
                                    request_token = qs['request_token'][0]
                                else:
                                    # Fallback simple split
                                    request_token = request_token.split("request_token=")[1].split("&")[0]
                            except Exception:
                                request_token = request_token.split("request_token=")[1].split("&")[0]
                        
                        logger.info("Intercepted request_token via Telegram")
                        self.send_message("🔄 Processing request_token...")
                        try:
                            from integrations.brokers.secrets import update_env_file
                            mgr = SecretManager()
                            api_key = mgr.get_secret("api_key", broker="zerodha")
                            api_secret = mgr.get_secret("api_secret", broker="zerodha")
                            kite = KiteConnect(api_key=api_key)
                            session_data = kite.generate_session(request_token, api_secret=api_secret)
                            final_access_token = session_data["access_token"]
                            
                            # Sync state completely
                            mgr.set_secret("access_token", final_access_token, broker="zerodha")
                            os.environ["ZERODHA_ACCESS_TOKEN"] = final_access_token
                            update_env_file(".env", "ZERODHA_ACCESS_TOKEN", final_access_token)
                            
                            self.send_message("✅ *Access Granted*. Vault updated. Resuming autonomous trading operations.")
                        except Exception as e:
                            self.send_message(f"❌ *Login Failed*: {e}")
                            
                    elif text.lower().split()[0] in ("/kill", "/pause", "/resume", "/close_all", "/status"):
                        cmd = text.lower().split()[0]
                        logger.warning(f"Received control command via Telegram: {cmd}")
                        if self.command_handler is None:
                            self.send_message("❌ Control command received but no trading bot is attached to the uplink.")
                        else:
                            try:
                                ack = self.command_handler.handle_remote_command(cmd)
                                self.send_message(ack)
                            except Exception as e:
                                logger.error(f"Control command {cmd} failed: {e}")
                                self.send_message(f"❌ Command {cmd} failed: {e}")
                    elif text.isdigit() and len(text) == 6:
                        self.latest_totp = text
                        logger.info(f"Received valid 6-digit TOTP token: {text}")
                        # Echo confirmation back to the user
                        self.send_message(f"✅ Received TOTP token: {text}. Authenticating Zerodha Connect...")
                    elif text:
                        # Process conversational query
                        logger.info(f"Received conversational query via Telegram: {text}")
                        try:
                            # Run LLM processor
                            response = self.llm_processor.generate_response(text)
                            self.send_message(response)
                        except Exception as e:
                            logger.error(f"Failed to generate LLM response for Telegram: {e}")
                            self.send_message("❌ Commander, my logic circuits encountered an error while processing that query.")
        except Exception as e:
            logger.debug(f"Failed to check Telegram updates: {e}")
