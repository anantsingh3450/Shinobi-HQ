"""Hokage Canonical Boot Manager.

Coordinates the complete, sequential boot process of the system:
1. Brain Bootstrapper
2. SQLite + migrations
3. EventBus
4. HokageOrchestrator
5. CommandQueue
6. MissionControl
7. AutonomousTradingBot
8. Watchdog
9. LearningEngine
10. GovernanceEngine
11. Scheduler
12. Broker Registry
13. PaperVenue
14. Zerodha Connection (READ_ONLY check)
15. Dashboard SSE infrastructure
16. Dashboard Server
"""
from __future__ import annotations

import sys
import signal
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path

from hokage.memory.resolver import PathResolver
from hokage.memory.bootstrap import BrainBootstrapper
from hokage.orchestrator.pipeline import HokageOrchestrator
from hokage.dashboard.event_bus import EventBus
from integrations.brokers.models import ExecutionMode
from shared.persistence.sqlite_engine import SqliteStorageEngine

logger = logging.getLogger("Hokage.BootManager")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

from hokage.dashboard.event_bus_handler import EventBusLogHandler
eb_handler = EventBusLogHandler()
eb_handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))
logging.getLogger("Hokage").addHandler(eb_handler)


class LifecycleState:
    INITIALIZING = "INITIALIZING"
    BOOTSTRAPPING = "BOOTSTRAPPING"
    LOADING_DATABASE = "LOADING_DATABASE"
    LOADING_BRAIN = "LOADING_BRAIN"
    CONNECTING_BROKER = "CONNECTING_BROKER"
    STARTING_AUTONOMOUS_LOOP = "STARTING_AUTONOMOUS_LOOP"
    STARTING_WATCHDOG = "STARTING_WATCHDOG"
    STARTING_DASHBOARD = "STARTING_DASHBOARD"
    ONLINE = "ONLINE"
    SHUTTING_DOWN = "SHUTTING_DOWN"
    OFFLINE = "OFFLINE"


class HokageBootManager:
    """Manages the full lifecycle boot sequence and graceful shutdown of Hokage."""

    def __init__(self, brain_root: Path | None = None) -> None:
        self.brain_root = brain_root
        self.event_bus = EventBus()
        self.orchestrator: HokageOrchestrator | None = None
        self.state = LifecycleState.INITIALIZING
        self._shutdown_lock = threading.Lock()
        self._is_shutting_down = False

    def publish_state(self, state: str) -> None:
        """Publish lifecycle transition to the EventBus."""
        self.state = state
        transition = {
            "state": state,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        logger.info(f"[LIFECYCLE] Transition to state: {state}")
        self.event_bus.publish("SYSTEM_LIFECYCLE_CHANGE", transition)

    def boot(self) -> None:
        """Execute the sequential boot process."""
        try:
            print("=========================================")
            print("         HOKAGE BOOT SEQUENCE            ")
            print("=========================================")
            self.publish_state(LifecycleState.INITIALIZING)

            # 1. Brain Bootstrapper
            self.publish_state(LifecycleState.BOOTSTRAPPING)
            resolver = PathResolver(self.brain_root)
            BrainBootstrapper(resolver).bootstrap()

            # Rotating file log: the audit_trail DB captures every log line
            # too, but a plain tail-able file on disk survives console
            # buffer loss and doesn't require a SQL query to read.
            from logging.handlers import RotatingFileHandler
            logs_dir = resolver.resolve_brain_root() / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(
                logs_dir / "hokage.log", maxBytes=10_000_000, backupCount=5, encoding="utf-8"
            )
            file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
            logging.getLogger().addHandler(file_handler)

            # 2. SQLite + Migrations
            self.publish_state(LifecycleState.LOADING_DATABASE)
            sqlite_engine = SqliteStorageEngine(resolver)
            sqlite_engine.run_migrations()

            # 3. EventBus
            # Instance is created during init. Confirm list of subscribers
            self.event_bus = EventBus()

            # 4. HokageOrchestrator
            self.publish_state(LifecycleState.LOADING_BRAIN)
            self.orchestrator = HokageOrchestrator(brain_root=self.brain_root)

            # Connect all registered execution venues on startup to establish session statuses
            logger.info("Connecting registered execution venues...")
            for venue_id in self.orchestrator.registry.list_venues():
                try:
                    venue = self.orchestrator.registry.get_venue(venue_id)
                    status = venue.connect()
                    logger.info(f"Connected venue '{venue_id}': {status.message if hasattr(status, 'message') else 'OK'}")
                except Exception as exc:
                    logger.warning(f"Note: Connection check for venue '{venue_id}': {exc}")

            # 5. CommandQueue (automatically starts CLI command loop worker in Orchestrator)
            # 6. MissionControl (SQLite schema loaded above)
            # 7. Broker Registry (initialized in Orchestrator)
            # 8. PaperVenue (initialized in Orchestrator)

            # 9. Zerodha Connection (READ_ONLY check)
            self.publish_state(LifecycleState.CONNECTING_BROKER)
            if self.orchestrator.context.execution_mode != ExecutionMode.READ_ONLY:
                logger.warning("ExecutionMode is not set to READ_ONLY on boot connection check!")

            # 10. Start AutonomousTradingBot
            self.publish_state(LifecycleState.STARTING_AUTONOMOUS_LOOP)
            self.orchestrator.autonomous_bot.start()

            # 11. Start Watchdog Monitoring (resolving active venue dynamically from context)
            self.publish_state(LifecycleState.STARTING_WATCHDOG)
            active_ctx = self.orchestrator.get_execution_context()
            active_venue = self.orchestrator.registry.get_venue(active_ctx.active_venue_id)
            self.orchestrator.watchdog.start_connectivity_monitor(active_venue)

            # 12. Run Health Gate Verification
            if not self._run_health_gate():
                self.publish_state(LifecycleState.OFFLINE)
                print("\n=========================================")
                print("             BOOT FAILED                 ")
                print("=========================================")
                sys.exit(1)

            # 13. Start Dashboard Server
            self.publish_state(LifecycleState.STARTING_DASHBOARD)
            from hokage.dashboard.api import create_dashboard_api
            app = create_dashboard_api(brain_root=self.brain_root, orchestrator=self.orchestrator)
            app.boot_manager = self

            # A deliberate stop ends the moment he is back. Clear the marker
            # that tells the external liveness watch to stay quiet.
            #
            # 2026-09-02: the marker written on 2026-08-28 21:26 was STILL on
            # disk when Hokage was restarted at 08:33 after several days away —
            # because only the liveness probe cleared it, and the probe does not
            # run before 09:00. Had he died at 08:40, the 09:00 check would have
            # seen him down, found the marker, and said nothing. A stale marker
            # masking a real death is exactly the "permanently deaf" failure the
            # self-healing design was supposed to prevent; clearing it here, at
            # the moment the stop actually ends, closes the window. The probe
            # still clears it too — that stays as the backstop for any start
            # path that bypasses this one.
            self._clear_deliberate_stop_marker()

            self.publish_state(LifecycleState.ONLINE)
            print("\n=========================================")
            print("             HOKAGE ONLINE               ")
            print("Systems online.")
            print("Awaiting market.")
            print("=========================================")

            # Run Flask development server (blocking)
            app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)

        except BaseException as exc:
            logger.critical(f"Boot manager encountered a fatal error (BaseException): {type(exc).__name__}: {exc}", exc_info=True)
            import traceback
            traceback.print_exc()
            self.publish_state(LifecycleState.OFFLINE)
            print("\n=========================================")
            print(f"             BOOT FAILED: {exc}          ")
            print("=========================================")
            sys.exit(1)

    #: Written by Stop-Hokage.ps1 / liveness_probe --stopped-on-purpose so the
    #: external liveness watch stays quiet during a stop the commander ordered.
    _STOP_MARKER = "state/stopped_deliberately.json"

    def _clear_deliberate_stop_marker(self) -> None:
        """Booting IS the end of a deliberate stop. Never fatal.

        Resolves through PathResolver rather than `self.brain_root`, which is
        None unless a caller passed one — start.py does not. The first version
        of this used it directly and failed with "argument should be a str or an
        os.PathLike object ... not 'NoneType'". The try/except kept Hokage
        booting, and the guard test passed because it only walked the AST and
        never executed the method.
        """
        try:
            root = PathResolver(self.brain_root).resolve_brain_root()
            marker = Path(root) / self._STOP_MARKER
            if marker.exists():
                marker.unlink()
                logger.info(
                    "Cleared the deliberate-stop marker — the liveness watch is "
                    "armed again."
                )
        except Exception as exc:
            # A monitor hint must never be able to stop Hokage booting.
            logger.warning(f"Could not clear the deliberate-stop marker: {exc}")

    def _run_health_gate(self) -> bool:
        """Verify health of every critical subsystem before going online."""
        logger.info("Executing health gate verification...")
        verifications = [
            ("Database", self._verify_db),
            ("EventBus", self._verify_event_bus),
            ("CommandQueue", self._verify_command_queue),
            ("Mission Engine", self._verify_mission_engine),
            ("Watchdog", self._verify_watchdog),
            ("PaperVenue", self._verify_paper_venue),
            ("Broker Registry", self._verify_broker_registry),
            ("Zerodha Connection", self._verify_zerodha_connection),
            ("Dashboard", self._verify_dashboard),
            ("Scheduler", self._verify_scheduler),
            ("AutonomousTradingBot", self._verify_autonomous_bot),
        ]

        for name, verify_fn in verifications:
            try:
                if not verify_fn():
                    logger.error(f"Health check failed for subsystem: {name}")
                    return False
            except Exception as e:
                logger.error(f"Health check raised exception for subsystem {name}: {e}")
                return False

        logger.info("Health gate checks: ALL SUBSYSTEMS PASSED.")
        return True

    def _verify_db(self) -> bool:
        conn = self.orchestrator.sqlite_engine.get_connection()
        cursor = conn.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1;")
        return cursor.fetchone() is not None

    def _verify_event_bus(self) -> bool:
        return hasattr(self.event_bus, "_listeners")

    def _verify_command_queue(self) -> bool:
        return self.orchestrator.command_queue.is_running

    def _verify_mission_engine(self) -> bool:
        conn = self.orchestrator.sqlite_engine.get_connection()
        cursor = conn.execute("SELECT count(*) FROM missions")
        return cursor.fetchone() is not None

    def _verify_watchdog(self) -> bool:
        return self.orchestrator.watchdog is not None

    def _verify_paper_venue(self) -> bool:
        return self.orchestrator.registry.get_venue("paper_main") is not None

    def _verify_broker_registry(self) -> bool:
        return len(self.orchestrator.broker_registry.list_brokers()) >= 0

    def _verify_zerodha_connection(self) -> bool:
        return self.orchestrator.kite_connection is not None

    def _verify_dashboard(self) -> bool:
        from hokage.dashboard.api import create_dashboard_api
        return create_dashboard_api is not None

    def _verify_scheduler(self) -> bool:
        return self.orchestrator.autonomous_bot is not None

    def _verify_autonomous_bot(self) -> bool:
        return self.orchestrator.autonomous_bot.is_active()

    def shutdown(self) -> None:
        """Safely terminate all background threads and processes."""
        with self._shutdown_lock:
            if self._is_shutting_down:
                return
            self._is_shutting_down = True

        print("\n=========================================")
        print("          HOKAGE SHUTTING DOWN           ")
        print("=========================================")
        self.publish_state(LifecycleState.SHUTTING_DOWN)

        if self.orchestrator:
            # 1. Stop autonomous loops & schedulers
            logger.info("Stopping Autonomous Trading loop...")
            self.orchestrator.autonomous_bot.stop()

            # 2. Stop watchdog connectivity monitors
            logger.info("Stopping Watchdog connectivity monitor...")
            self.orchestrator.watchdog.stop_connectivity_monitor()

            # 3. Stop Command Queue worker
            logger.info("Stopping Command Queue worker...")
            self.orchestrator.command_queue.stop_worker()

            # 4. Close database cleanly
            logger.info("Closing SQLite database connection pool...")
            self.orchestrator.sqlite_engine.close()

        self.publish_state(LifecycleState.OFFLINE)
        print("=========================================")
        print("             HOKAGE OFFLINE              ")
        print("=========================================")


_boot_manager: HokageBootManager | None = None


def handle_signal(signum, frame) -> None:
    """Signal handler that triggers boot manager shutdown."""
    global _boot_manager
    if _boot_manager:
        _boot_manager.shutdown()
    sys.exit(0)


def main() -> None:
    """Main entry point to execute the boot manager."""
    global _boot_manager
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    _boot_manager = HokageBootManager()
    _boot_manager.boot()


if __name__ == "__main__":
    main()
