# C1 — SQLite `is_active` De-Mock Migration Plan

## The sniff
`src/shared/persistence/sqlite_engine.py:28` — `SqliteStorageEngine.is_active()`
returns `False` whenever `"pytest" in sys.modules` (unless argv names
`test_sqlite_persistence`). This forces ~383 tests down the legacy JSON
persistence path and means the SQLite schema/migrations/stores are never
exercised by the normal suite.

## Blast radius
`is_active()` gates the storage backend at 20+ call sites:
`tax/store.py`, `watchdog/store.py`, `strategy/evolution.py` (x3),
`command_queue.py`, `improvement_bot.py` (x3), `portfolio/store.py`,
`reconciliation/store.py`, `json_trade_store.py`, `prediction_ledger.py`,
`decision_journal.py`, `performance_analytics.py`, `dashboard/api.py` (many).
Pattern everywhere: `if is_active(resolver): <SQLite> else: <JSON>`.

## Why a naive delete is *probably* safe (but must be verified)
After removing the pytest short-circuit, `is_active()` degrades to its real
predicate: `hokage.db exists under brain_root AND schema_version >= 1`.
Unit tests use `tmp_path`-isolated brain roots with no `hokage.db`, so
`is_active()` returns `False` **for the same reason** — the JSON path is still
taken. Expected result: **0 breaks**.

The one hazard: any test that *materializes* a migrated `hokage.db` in its brain
root (directly or via a code path that calls `run_migrations()`), then asserts
JSON-store behavior, would now flip to the SQLite store mid-test and could fail.

## Execution — two stages

### Stage C1a (this change): remove the sniff, keep behavior
1. Delete lines 25-32 (the `if "pytest" in sys.modules` block). No replacement.
2. `is_active()` now relies solely on real DB existence + schema check.
3. Run full suite.
   - **0 breaks** -> sniff gone, behavior preserved. Log the SQLite-path coverage
     hole (below) and proceed.
   - **Breaks** -> classify: a test that builds a real DB is a BAD MOCK (isolate its
     brain root) or a genuine JSON/SQLite divergence (REAL BUG — flag, do not fix).

### Stage C1b (follow-up, larger — NOT in C1a): actually test the SQLite path
The coverage hole is the real prize. Proposal:
1. Add a `sqlite_brain` pytest fixture: builds a `SqliteStorageEngine` on a
   `tmp_path` brain root and runs `run_migrations()` to a real, migrated DB
   (file-based tmp, or `:memory:` shared-cache if the engine supports it).
2. Parametrize (or duplicate) the persistence-store tests to run against BOTH
   backends: legacy JSON and the migrated SQLite — asserting identical behavior.
   This is what proves JSON and SQLite stores agree, and closes the hole.
3. Scope: one store at a time (portfolio, trades, ledger, journal, reconciliation,
   tax, watchdog, evolution). Each is an independent, reviewable PR-sized unit.

## Coverage debt created/So-far untested
Until C1b lands, the SQLite branch of every store above is executed only by
`test_sqlite_persistence`, not by the store-level behavior tests. 🔴 High:
this is the durability layer for live trading — trades, positions, ledger.
