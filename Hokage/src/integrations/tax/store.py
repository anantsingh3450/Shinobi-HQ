"""JSON Lines tax ledger for simulated tax events."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from integrations.tax.models import (
    TaxComponent,
    TaxComponentType,
    TaxEvent,
    TaxJurisdiction,
)


class JsonTaxLedger:
    """Persist TaxEvent records separately from the trading ledger."""

    _FILENAME = "tax_events.jsonl"

    def __init__(self, output_directory: Path) -> None:
        self._output_directory = output_directory
        
        # Determine if SQLite is active
        from hokage.memory.resolver import PathResolver
        from shared.persistence.sqlite_engine import SqliteStorageEngine
        from shared.persistence.sqlite_stores import SqliteTaxLedger
        
        resolver = PathResolver(output_directory.parent)
        if SqliteStorageEngine.is_active(resolver):
            engine = SqliteStorageEngine(resolver)
            self._delegate = SqliteTaxLedger(engine)
        else:
            self._delegate = None

    @property
    def events_file(self) -> Path:
        """Path to the tax ledger file."""
        return self._output_directory / self._FILENAME

    def record_event(self, event: TaxEvent) -> None:
        """Append a tax event to the ledger."""
        if self._delegate is not None:
            self._delegate.record_event(event)
            return

        self._output_directory.mkdir(parents=True, exist_ok=True)
        with self.events_file.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(self._to_dict(event), sort_keys=True) + "\n")

    def load_events(self) -> tuple[TaxEvent, ...]:
        """Load all tax events from the ledger."""
        if self._delegate is not None:
            return self._delegate.load_events()

        if not self.events_file.exists():
            return ()

        events: list[TaxEvent] = []
        with self.events_file.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    events.append(self._from_dict(json.loads(line)))
        return tuple(events)

    @staticmethod
    def _to_dict(event: TaxEvent) -> dict:
        return {
            "trade_id": event.trade_id,
            "market": event.market,
            "direction": event.direction,
            "quantity": event.quantity,
            "entry_price": event.entry_price,
            "simulated_value": event.simulated_value,
            "executed_at": event.executed_at.isoformat(),
            "jurisdiction": event.jurisdiction.value,
            "currency": event.currency,
            "components": [
                {
                    "component_type": component.component_type.value,
                    "amount": component.amount,
                    "currency": component.currency,
                    "description": component.description,
                }
                for component in event.components
            ],
        }

    @staticmethod
    def _from_dict(data: dict) -> TaxEvent:
        return TaxEvent(
            trade_id=data["trade_id"],
            market=data["market"],
            direction=data["direction"],
            quantity=data["quantity"],
            entry_price=data["entry_price"],
            simulated_value=data["simulated_value"],
            executed_at=datetime.fromisoformat(data["executed_at"]),
            jurisdiction=TaxJurisdiction(data["jurisdiction"]),
            currency=data["currency"],
            components=tuple(
                TaxComponent(
                    component_type=TaxComponentType(component["component_type"]),
                    amount=component["amount"],
                    currency=component["currency"],
                    description=component.get("description", ""),
                )
                for component in data.get("components", [])
            ),
        )
