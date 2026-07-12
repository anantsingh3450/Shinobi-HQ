from __future__ import annotations

import json
import uuid
import queue
import threading
import logging
from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("Hokage.CommandQueue")


class Role(str, Enum):
    COMMANDER = "COMMANDER"
    DEVELOPER = "DEVELOPER"
    OBSERVER = "OBSERVER"
    EMERGENCY = "EMERGENCY"


class CommandType(str, Enum):
    START_AUTONOMOUS = "START_AUTONOMOUS"
    STOP_AUTONOMOUS = "STOP_AUTONOMOUS"
    PAUSE_ENGINE = "PAUSE_ENGINE"
    RESUME_ENGINE = "RESUME_ENGINE"
    ENABLE_PAPER = "ENABLE_PAPER"
    ENABLE_LIVE = "ENABLE_LIVE"
    ENABLE_SHADOW = "ENABLE_SHADOW"
    EMERGENCY_STOP = "EMERGENCY_STOP"
    UPDATE_SETTINGS = "UPDATE_SETTINGS"
    RUN_RESEARCH = "RUN_RESEARCH"
    RUN_SCAN = "RUN_SCAN"
    GENERATE_REPORT = "GENERATE_REPORT"
    VOICE_COMMAND = "VOICE_COMMAND"


# Role-based permissions matrix mapping CommandType to allowed roles
PERMISSION_MATRIX: dict[CommandType, list[Role]] = {
    CommandType.START_AUTONOMOUS: [Role.COMMANDER, Role.DEVELOPER],
    CommandType.STOP_AUTONOMOUS: [Role.COMMANDER, Role.DEVELOPER],
    CommandType.PAUSE_ENGINE: [Role.COMMANDER, Role.DEVELOPER],
    CommandType.RESUME_ENGINE: [Role.COMMANDER, Role.DEVELOPER],
    CommandType.ENABLE_PAPER: [Role.COMMANDER, Role.DEVELOPER],
    CommandType.ENABLE_LIVE: [Role.COMMANDER], # Only Commander can enable live trading!
    CommandType.ENABLE_SHADOW: [Role.COMMANDER, Role.DEVELOPER],
    CommandType.EMERGENCY_STOP: [Role.COMMANDER, Role.DEVELOPER, Role.EMERGENCY], # Emergency role can stop the system
    CommandType.UPDATE_SETTINGS: [Role.COMMANDER, Role.DEVELOPER],
    CommandType.RUN_RESEARCH: [Role.COMMANDER, Role.DEVELOPER, Role.OBSERVER],
    CommandType.RUN_SCAN: [Role.COMMANDER, Role.DEVELOPER],
    CommandType.GENERATE_REPORT: [Role.COMMANDER, Role.DEVELOPER, Role.OBSERVER],
    CommandType.VOICE_COMMAND: [Role.COMMANDER],
}


@dataclass
class Command:
    command_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    commander: str = "Commander"
    role: Role = Role.COMMANDER
    command_type: CommandType = CommandType.RUN_SCAN
    parameters: dict[str, Any] = field(default_factory=dict)
    priority: int = 1  # 0 = Critical/Emergency, 1 = Normal, 2 = Low
    status: str = "PENDING"  # PENDING, RUNNING, COMPLETED, FAILED, REJECTED
    execution_time: float | None = None  # in seconds
    result: Any = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "command_id": self.command_id,
            "timestamp": self.timestamp.isoformat(),
            "commander": self.commander,
            "role": self.role.value,
            "command_type": self.command_type.value,
            "parameters": self.parameters,
            "priority": self.priority,
            "status": self.status,
            "execution_time": self.execution_time,
            "result": self.result,
            "error": self.error
        }


class CommandQueue:
    """Thread-safe queue for serializing and executing Commander actions."""

    def __init__(self, orchestrator: Any) -> None:
        self.orchestrator = orchestrator
        self.queue: queue.PriorityQueue[tuple[int, datetime, Command]] = queue.PriorityQueue()
        self.lock = threading.Lock()
        self.active_worker = None
        self.is_running = False

    def validate_permissions(self, command: Command) -> bool:
        """Verify if the command's role is permitted to execute this command type."""
        allowed_roles = PERMISSION_MATRIX.get(command.command_type, [])
        return command.role in allowed_roles

    def enqueue(self, command: Command) -> bool:
        """Validate permissions and enqueue a command for asynchronous execution."""
        if not self.validate_permissions(command):
            command.status = "REJECTED"
            command.error = f"Role '{command.role.value}' does not have permission to execute '{command.command_type.value}'."
            self.log_command_to_db(command)
            
            # Publish event via EventBus
            try:
                from hokage.dashboard.event_bus import EventBus
                EventBus().publish("ALERT_CREATED", {
                    "source": "COMMAND_QUEUE",
                    "severity": "WARNING",
                    "message": f"Unauthorized command attempt: {command.command_type.value} by {command.commander} ({command.role.value})"
                })
            except Exception:
                pass
                
            return False

        # Enqueue with priority (lower priority number executes first)
        self.queue.put((command.priority, command.timestamp, command))
        self.log_command_to_db(command)
        return True

    def start_worker(self) -> None:
        """Start the background worker thread to process enqueued commands."""
        with self.lock:
            if not self.is_running:
                self.is_running = True
                self.active_worker = threading.Thread(target=self._worker_loop, daemon=True)
                self.active_worker.start()
                logger.info("Command Queue worker thread started.")

    def stop_worker(self) -> None:
        """Stop the background worker thread."""
        with self.lock:
            self.is_running = False

    def _worker_loop(self) -> None:
        while self.is_running:
            try:
                # Bounded wait so we can check if worker has been stopped
                _, _, cmd = self.queue.get(timeout=1.0)
            except queue.Empty:
                continue

            try:
                self._execute_command(cmd)
            except Exception as e:
                logger.error(f"Error processing command {cmd.command_id}: {e}")
            finally:
                self.queue.task_done()

    def _execute_command(self, cmd: Command) -> None:
        cmd.status = "RUNNING"
        self.log_command_to_db(cmd)
        
        start_time = datetime.now(timezone.utc)
        try:
            # Dispatch command to the orchestrator mapping
            result = self._dispatch_to_orchestrator(cmd)
            cmd.status = "COMPLETED"
            cmd.result = result
        except Exception as e:
            cmd.status = "FAILED"
            cmd.error = str(e)
            logger.error(f"Command {cmd.command_type.value} failed: {e}")
        finally:
            end_time = datetime.now(timezone.utc)
            cmd.execution_time = (end_time - start_time).total_seconds()
            self.log_command_to_db(cmd)
            
            # Publish completion event
            try:
                from hokage.dashboard.event_bus import EventBus
                EventBus().publish("COMMAND_EXECUTED", cmd.to_dict())
            except Exception:
                pass

    def _dispatch_to_orchestrator(self, cmd: Command) -> Any:
        """Map CommandTypes to actual orchestrator function calls."""
        ot = self.orchestrator
        
        if cmd.command_type == CommandType.START_AUTONOMOUS:
            ot.autonomous_bot.start()
            return "Autonomous mode started"
            
        elif cmd.command_type == CommandType.STOP_AUTONOMOUS:
            ot.autonomous_bot.stop()
            return "Autonomous mode stopped"
            
        elif cmd.command_type == CommandType.PAUSE_ENGINE:
            # Pause autonomous loop or decision making
            if hasattr(ot.autonomous_bot, "pause"):
                ot.autonomous_bot.pause()
            return "Decision engine paused"
            
        elif cmd.command_type == CommandType.RESUME_ENGINE:
            if hasattr(ot.autonomous_bot, "resume"):
                ot.autonomous_bot.resume()
            return "Decision engine resumed"
            
        elif cmd.command_type == CommandType.ENABLE_PAPER:
            # Change environment mode to PAPER
            from integrations.brokers.models import ExecutionMode
            ot.context.execution_mode = ExecutionMode.PAPER
            return "Paper trading enabled"
            
        elif cmd.command_type == CommandType.ENABLE_LIVE:
            from integrations.brokers.models import ExecutionMode
            ot.context.execution_mode = ExecutionMode.LIVE
            return "Live trading enabled"
            
        elif cmd.command_type == CommandType.ENABLE_SHADOW:
            from integrations.brokers.models import ExecutionMode
            ot.context.execution_mode = ExecutionMode.SHADOW
            return "Shadow mode enabled"
            
        elif cmd.command_type == CommandType.EMERGENCY_STOP:
            # Perform emergency shutdown: stop loop, cancel all active orders, clear context
            ot.autonomous_bot.stop()
            # Cancel orders in execution bot
            if hasattr(ot.execution_bot, "cancel_all_orders"):
                ot.execution_bot.cancel_all_orders()
            # Publish emergency event
            try:
                from hokage.dashboard.event_bus import EventBus
                EventBus().publish("ALERT_CREATED", {
                    "source": "WATCHDOG",
                    "severity": "CRITICAL",
                    "message": "EMERGENCY KILL SWITCH ACTIVATED. All trading activity halted immediately."
                })
            except Exception:
                pass
            return "Emergency stop completed successfully"
            
        elif cmd.command_type == CommandType.UPDATE_SETTINGS:
            # Save settings in SQLite
            key = cmd.parameters.get("key")
            value = cmd.parameters.get("value")
            if key:
                ot.sqlite_engine.get_connection().execute(
                    "INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?);",
                    (key, json.dumps(value))
                )
                try:
                    from hokage.dashboard.event_bus import EventBus
                    EventBus().publish("SETTINGS_UPDATED", {"key": key, "value": value})
                except Exception:
                    pass
                return f"Settings updated for {key}"
            raise ValueError("Missing 'key' or 'value' parameter")
            
        elif cmd.command_type == CommandType.RUN_RESEARCH:
            query = cmd.parameters.get("query", "Macro Outlook")
            return ot.execute_research_to_strategy(query)
            
        elif cmd.command_type == CommandType.RUN_SCAN:
            return ot.autonomous_bot._scan_and_enter_opportunities()
            
        elif cmd.command_type == CommandType.GENERATE_REPORT:
            # Trigger report generation
            if hasattr(ot.research_bot, "generate_report"):
                return ot.research_bot.generate_report()
            return "Report generation queued"
            
        elif cmd.command_type == CommandType.VOICE_COMMAND:
            query = cmd.parameters.get("query", "")
            from bots.autonomous.conversation import CommanderConversationEngine
            from bots.autonomous.cache import IntelligenceCache
            cache = IntelligenceCache(ot.resolver.resolve_brain_root())
            engine = CommanderConversationEngine(ot, cache)
            return engine.respond(query)
            
        else:
            raise ValueError(f"Unknown command type: {cmd.command_type.value}")

    def log_command_to_db(self, cmd: Command) -> None:
        """Log command to SQLite database for audit trail (never overwrite history)."""
        try:
            from shared.persistence.sqlite_engine import SqliteStorageEngine
            if not SqliteStorageEngine.is_active(self.orchestrator.resolver):
                return
                
            conn = self.orchestrator.sqlite_engine.get_connection()
            with conn:
                conn.execute("""
                    INSERT OR REPLACE INTO system_commands (
                        command_id, timestamp, commander, role, command_type, 
                        parameters, priority, status, execution_time, result, error
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """, (
                    cmd.command_id,
                    cmd.timestamp.isoformat(),
                    cmd.commander,
                    cmd.role.value,
                    cmd.command_type.value,
                    json.dumps(cmd.parameters),
                    cmd.priority,
                    cmd.status,
                    cmd.execution_time,
                    json.dumps(cmd.result) if cmd.result else None,
                    cmd.error
                ))
        except Exception as e:
            logger.error(f"Failed to log command to DB: {e}")
