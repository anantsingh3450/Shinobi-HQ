"""Comprehensive verification tests for the SQLite persistence and migration layer."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from hokage.memory.resolver import PathResolver
from shared.persistence.sqlite_engine import SqliteStorageEngine
from shared.persistence.sqlite_stores import (
    SqliteTradeStore,
)
from bots.execution.models import TradeRecord, TradeDirection


@pytest.fixture
def tmp_resolver(tmp_path: Path) -> PathResolver:
    """Fixture that returns a PathResolver pointing to a temporary folder."""
    return PathResolver(tmp_path)


def test_empty_migration(tmp_resolver: PathResolver) -> None:
    """Verify migration behavior on a fresh start with no JSON files."""
    engine = SqliteStorageEngine(tmp_resolver)
    
    # Run migration
    migrated = engine.run_migrations()
    assert migrated is True
    
    # Verify version in database — engine always initialises to version 2 (Phase 6.5)
    assert engine.check_schema_version() == 2
    
    # Verify integrity check passes
    assert engine.execute_integrity_check() is True


def test_large_migration(tmp_resolver: PathResolver) -> None:
    """Verify migration behavior with a large volume of mock JSON records."""
    brain_root = tmp_resolver.resolve_brain_root()
    
    # Create trades directory and large trades.jsonl
    trades_dir = tmp_resolver.resolve_trades_dir()
    trades_dir.mkdir(parents=True, exist_ok=True)
    trades_file = trades_dir / "trades.jsonl"
    
    record_count = 1000
    with trades_file.open("w", encoding="utf-8") as fh:
        for i in range(record_count):
            trade = {
                "trade_id": f"t-{i}",
                "proposal_id": f"p-{i}",
                "market": "BTC/USD",
                "direction": "LONG",
                "quantity": 1.5,
                "entry_price": 60000.0 + i,
                "simulated_value": 90000.0,
                "mode": "PAPER",
                "status": "OPEN",
                "strategy_name": "Grid Strategy",
                "sources_cited": ["src-1", "src-2"],
                "executed_at": datetime.now(timezone.utc).isoformat()
            }
            fh.write(json.dumps(trade) + "\n")
            
    # Run migration
    engine = SqliteStorageEngine(tmp_resolver)
    migrated = engine.run_migrations()
    assert migrated is True
    
    # Verify database counts
    conn = engine.get_connection()
    cursor = conn.execute("SELECT COUNT(*) FROM trades;")
    count = cursor.fetchone()[0]
    assert count == record_count
    
    # Verify original file renamed to .migrated
    assert not trades_file.exists()
    assert (trades_dir / "trades.jsonl.migrated").exists()


def test_corrupted_json_migration_rollback(tmp_resolver: PathResolver) -> None:
    """Verify that a corrupted JSON file triggers an ACID rollback and leaves no database."""
    trades_dir = tmp_resolver.resolve_trades_dir()
    trades_dir.mkdir(parents=True, exist_ok=True)
    trades_file = trades_dir / "trades.jsonl"
    
    # Write a mix of valid and corrupted JSON lines
    with trades_file.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "trade_id": "t-1", "proposal_id": "p-1", "market": "BTC/USD", "direction": "LONG",
            "quantity": 1.0, "entry_price": 60000.0, "simulated_value": 60000.0, "mode": "PAPER",
            "status": "OPEN", "strategy_name": "S1", "sources_cited": [], "executed_at": datetime.now(timezone.utc).isoformat()
        }) + "\n")
        fh.write("{corrupt_json_line\n")  # Corrupted line!
        
    engine = SqliteStorageEngine(tmp_resolver)
    
    # Migration must raise an exception
    with pytest.raises(Exception):
        engine.run_migrations()
        
    # Verify database file was deleted (or rolled back/not created)
    db_path = tmp_resolver.resolve_brain_root() / "hokage.db"
    assert not db_path.exists()
    
    # Original corrupted file must still exist and be intact
    assert trades_file.exists()


def test_partial_migration_failure_rollback(tmp_resolver: PathResolver) -> None:
    """Verify that an exception mid-migration rolls back the entire database transaction."""
    # Write a valid trades file
    trades_dir = tmp_resolver.resolve_trades_dir()
    trades_dir.mkdir(parents=True, exist_ok=True)
    trades_file = trades_dir / "trades.jsonl"
    with trades_file.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "trade_id": "t-1", "proposal_id": "p-1", "market": "BTC/USD", "direction": "LONG",
            "quantity": 1.0, "entry_price": 60000.0, "simulated_value": 60000.0, "mode": "PAPER",
            "status": "OPEN", "strategy_name": "S1", "sources_cited": [], "executed_at": datetime.now(timezone.utc).isoformat()
        }) + "\n")
        
    # Write an invalid portfolio account (missing key)
    port_dir = tmp_resolver.resolve_portfolio_dir()
    port_dir.mkdir(parents=True, exist_ok=True)
    port_file = port_dir / "account_paper.json"
    with port_file.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "account_id": "paper",
            # missing initial_balance, cash etc. to trigger migration crash!
        }))
        
    engine = SqliteStorageEngine(tmp_resolver)
    
    # Migration must crash due to KeyError
    with pytest.raises(Exception):
        engine.run_migrations()
        
    # Verify no partial database is left
    db_path = tmp_resolver.resolve_brain_root() / "hokage.db"
    assert not db_path.exists()
    
    # Original files must be intact
    assert trades_file.exists()
    assert port_file.exists()


def test_never_migrate_twice(tmp_resolver: PathResolver) -> None:
    """Verify that starting migration twice is a no-op the second time."""
    engine = SqliteStorageEngine(tmp_resolver)
    
    # First migration
    first_run = engine.run_migrations()
    assert first_run is True
    assert engine.check_schema_version() == 2  # Phase 6.5: engine initialises at version 2
    
    # Second migration
    second_run = engine.run_migrations()
    assert second_run is False  # Already up to date


def test_integrity_verification(tmp_resolver: PathResolver) -> None:
    """Verify database health using SQLite integrity checks."""
    engine = SqliteStorageEngine(tmp_resolver)
    engine.run_migrations()
    
    # Health check should be True
    assert engine.execute_integrity_check() is True
    
    # Intentionally corrupt the file to test detection
    engine.close()
    db_path = tmp_resolver.resolve_brain_root() / "hokage.db"
    with db_path.open("r+b") as fh:
        fh.seek(100)
        fh.write(b"CORRUPTED_DATA_STAMP")
        
    # Health check should now fail (either raises OperationalError or returns False)
    # Re-init engine to clear connection cached state
    corrupted_engine = SqliteStorageEngine(tmp_resolver)
    assert corrupted_engine.execute_integrity_check() is False


def test_concurrency_reads_and_writes(tmp_resolver: PathResolver) -> None:
    """Verify WAL mode thread safety with concurrent reads and writes."""
    engine = SqliteStorageEngine(tmp_resolver)
    engine.run_migrations()
    
    store = SqliteTradeStore(engine)
    
    # Number of concurrent writer and reader threads
    threads = []
    errors = []
    
    def writer_task(thread_id: int) -> None:
        try:
            for i in range(50):
                trade = TradeRecord(
                    proposal_id=f"p-{thread_id}-{i}",
                    market="EUR/USD",
                    direction=TradeDirection.LONG,
                    quantity=100.0,
                    entry_price=1.08,
                    simulated_value=108.0,
                    strategy_name="Concurrent Long",
                    sources_cited=(),
                    trade_id=f"t-{thread_id}-{i}"
                )
                store.save(trade)
                time.sleep(0.001)
        except Exception as exc:
            errors.append(f"Writer error: {exc}")

    def reader_task() -> None:
        try:
            for _ in range(100):
                trades = store.load_all()
                # Just reading
                _ = len(trades)
                time.sleep(0.001)
        except Exception as exc:
            errors.append(f"Reader error: {exc}")

    # Launch 4 writers and 4 readers
    for i in range(4):
        t_w = threading.Thread(target=writer_task, args=(i,))
        t_r = threading.Thread(target=reader_task)
        threads.extend([t_w, t_r])
        t_w.start()
        t_r.start()
        
    # Join all threads
    for t in threads:
        t.join()
        
    # Verify no errors occurred
    assert not errors, f"Concurrency errors detected: {errors}"
    
    # Verify final count in database
    total_written = 4 * 50
    assert len(store.load_all()) == total_written


def test_recovery_after_interruption(tmp_resolver: PathResolver) -> None:
    """Verify that if migration is interrupted, the original JSON files are intact for a successful retry."""
    # Write a valid trades file
    trades_dir = tmp_resolver.resolve_trades_dir()
    trades_dir.mkdir(parents=True, exist_ok=True)
    trades_file = trades_dir / "trades.jsonl"
    with trades_file.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "trade_id": "t-1", "proposal_id": "p-1", "market": "BTC/USD", "direction": "LONG",
            "quantity": 1.0, "entry_price": 60000.0, "simulated_value": 60000.0, "mode": "PAPER",
            "status": "OPEN", "strategy_name": "S1", "sources_cited": [], "executed_at": datetime.now(timezone.utc).isoformat()
        }) + "\n")

    # Simulate an interruption by monkeypatching SQLite connect to raise an OperationalError
    engine = SqliteStorageEngine(tmp_resolver)
    
    def mock_get_connection():
        raise sqlite3.OperationalError("Simulated write interruption/disk full")
        
    original_get_conn = engine.get_connection
    engine.get_connection = mock_get_connection
    
    # Migration fails due to simulated interruption
    with pytest.raises(sqlite3.OperationalError):
        engine.run_migrations()
        
    # Restore connection method
    engine.get_connection = original_get_conn
    
    # Original files must be completely intact
    assert trades_file.exists()
    
    # Re-running migration works perfectly now
    success = engine.run_migrations()
    assert success is True
    
    # Counts match
    assert len(SqliteTradeStore(engine).load_all()) == 1
