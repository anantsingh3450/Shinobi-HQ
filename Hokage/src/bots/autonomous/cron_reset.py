import threading
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

class CronScheduler(threading.Thread):
    def __init__(self, bot, lock: threading.Lock) -> None:
        super().__init__(name="CronScheduler-0600", daemon=True)
        self.bot = bot
        self.lock = lock
        self._stop_event = threading.Event()

    def run(self) -> None:
        logger.info("CronScheduler: 06:00 AM reset daemon initialized.")
        try:
            from integrations.brokers.session_manager import KolkataTime
            from datetime import time as dt_time
            tz = KolkataTime()
        except ImportError:
            logger.error("CronScheduler: Could not import KolkataTime. Scheduler aborting.")
            return

        last_reset_date = None
        last_checklist_date = None

        while not self._stop_event.is_set():
            try:
                now_ist = datetime.now(timezone.utc).astimezone(tz)
                curr_date = now_ist.date()
                
                # Check if it is strictly past 06:00 AM today and we haven't reset today
                if now_ist.time() >= dt_time(6, 0) and last_reset_date != curr_date:
                    logger.info(f"CronScheduler: Triggering 06:00 AM Free Mind state flush for {curr_date}.")
                    with self.lock:
                        # Clear manual overrides
                        if hasattr(self.bot, "intraday_override"):
                            self.bot.intraday_override.clear()
                        
                        # Reset session tracking
                        if hasattr(self.bot, "_trades_taken_today"):
                            self.bot._trades_taken_today.clear()
                        if hasattr(self.bot, "_exits_executed_today"):
                            self.bot._exits_executed_today.clear()
                            
                        self.bot.elder_manual_input_received = False
                        self.bot.gatekeeper_state = None
                        
                        # Enforce fully autonomous mode
                        self.bot.free_mind_free_hand = True
                        
                    last_reset_date = curr_date
                    logger.info("CronScheduler: Free Mind reset complete. All locks lifted.")
                
                # 08:45 AM Morning Health Checklist
                #
                # NOT ON A DAY WITH NO OPEN. This check exists to say whether
                # Hokage is ready for 09:00, and its own wording is "Awaiting
                # 09:00 Open" / "ACTION REQUIRED BEFORE OPEN". On 2026-11-07 it
                # sent a red API: FAIL about a Saturday - the overnight token is
                # always dead, so on every weekend and holiday this reports a
                # failure that is simply the market being shut. Silence needs a
                # POSITIVE closure: see trading_calendar.nothing_trades, which
                # keeps the alarm on an unknown date.
                shut_today, why_shut = False, ""
                try:
                    from hokage.memory import trading_calendar
                    shut_today = trading_calendar.nothing_trades(now_ist.date())
                    why_shut = trading_calendar.describe(now_ist.date())
                except Exception:
                    shut_today = False      # no calendar, no silence
                if shut_today and last_checklist_date != curr_date:
                    logger.info(
                        "CronScheduler: skipping the morning checklist - %s", why_shut)
                    last_checklist_date = curr_date
                if (now_ist.time() >= dt_time(8, 45) and not shut_today
                        and last_checklist_date != curr_date):
                    logger.info("CronScheduler: Triggering 08:45 AM Health Checklist.")
                    checklist_passed = True
                    try:
                        # 1. Check DB
                        from shared.persistence.sqlite_engine import SqliteStorageEngine
                        sqlite_engine = SqliteStorageEngine(self.bot.orchestrator.resolver)
                        conn = sqlite_engine.get_connection()
                        conn.execute("SELECT 1")
                        db_status = "OK"
                    except Exception as e:
                        db_status = f"FAIL ({e})"
                        checklist_passed = False

                    try:
                        # 2. Check API
                        client = self.bot.orchestrator.registry.get_venue("kite_main")
                        if client:
                            client.get_account_balance()
                        api_status = "OK"
                    except Exception as e:
                        api_status = f"FAIL ({e})"
                        checklist_passed = False

                    # "Awaiting 09:00 Open" is a lie on a day that opens at
                    # 14:20. The checklist still runs at 08:45 - it is a
                    # readiness check, and being early is its job - but it
                    # names the hour the market actually opens.
                    open_at = "09:00"
                    try:
                        from hokage.memory import trading_calendar
                        window = trading_calendar.session_window(
                            now_ist.date(), "NSE")
                        if window:
                            open_at = window[0].strftime("%H:%M")
                    except Exception:
                        pass

                    engine_status = "Active" if self.bot.is_active() else "FAIL (Not Active)"
                    if engine_status != "Active":
                        checklist_passed = False

                    # WHICH CODE IS RUNNING. Deliberately NOT part of
                    # checklist_passed: HEAD moves on every commit, which is
                    # routine, and a check that goes red every day is a check
                    # nobody reads. This is here to make an invisible state
                    # visible - on 2026-11-08 Hokage held 44-hour-old code
                    # through a live session while three restarts reported
                    # success, and no panel could say so, because every panel
                    # asks the running process how it is and a stale process
                    # is perfectly healthy.
                    code_line = "unknown"
                    try:
                        from shared.ops import code_version
                        behind, _, _ = code_version.staleness()
                        code_line = ("⚠️ " if behind else "") + code_version.describe()
                    except Exception:
                        pass

                    msg = (
                        f"{'✅' if checklist_passed else '🚨'} Morning Systems Check: \n"
                        f"DB: {db_status}\n"
                        f"API: {api_status}\n"
                        f"Engine: {engine_status}\n"
                        f"Code: {code_line}\n\n"
                        f"{f'Awaiting {open_at} Open.' if checklist_passed else 'ACTION REQUIRED BEFORE OPEN.'}"
                    )
                    
                    if self.bot.telegram_bot and self.bot.telegram_bot.enabled:
                        self.bot.telegram_bot.send_message(msg)
                        
                    last_checklist_date = curr_date

            except Exception as e:
                logger.error(f"CronScheduler: Exception in check loop: {e}")
                
            # Sleep for 30 seconds before next check
            self._stop_event.wait(30.0)
            
    def stop(self) -> None:
        self._stop_event.set()
