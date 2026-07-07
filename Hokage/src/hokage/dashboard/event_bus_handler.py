import logging
from hokage.dashboard.event_bus import EventBus

class EventBusLogHandler(logging.Handler):
    """Custom logging handler that publishes operational log messages to the EventBus."""

    def __init__(self, level=logging.INFO):
        super().__init__(level)
        self._event_bus = None

    @property
    def event_bus(self):
        if self._event_bus is None:
            self._event_bus = EventBus()
        return self._event_bus

    def emit(self, record):
        try:
            log_entry = self.format(record)
            level_name = record.levelname
            
            # Map Python log levels to Dashboard log levels
            if level_name == "CRITICAL":
                level_name = "ERROR"
            elif level_name == "WARNING":
                level_name = "WARNING"
            elif level_name in ("ERROR", "EXCEPTION"):
                level_name = "ERROR"
            else:
                level_name = "INFO"
                
            # Filter: only stream Hokage-prefixed logs to avoid third-party logs cluttering
            if not record.name.startswith("Hokage"):
                return
                
            self.event_bus.publish("SHINOBI_LOG", {
                "level": level_name,
                "message": log_entry
            })
        except Exception:
            self.handleError(record)
