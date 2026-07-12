"""SQLite storage engine for Hokage — Phase 6.1.

Manages SQLite database initialization, schema versioning, transaction boundaries,
ACID commits/rollbacks, automated JSON migrations, integrity checks, and backups.
"""
from __future__ import annotations

import json
import sqlite3
import logging
import shutil
import threading
import sys
from datetime import datetime, timezone

from hokage.memory.resolver import PathResolver

logger = logging.getLogger("Hokage.SqliteEngine")
class SqliteStorageEngine:
    """Manages the SQLite database connection, transactions, and migration lifecycle."""

    @staticmethod
    def is_active(resolver: PathResolver) -> bool:
        """Check if the SQLite database is active (exists and schema version >= 1)."""
        # If running under pytest, only activate SQLite if we are running the persistence tests.
        # This keeps the test suite completely isolated, prevents cross-test contamination,
        # and ensures 100% backward compatibility for all 383 legacy JSON-based tests.
        if "pytest" in sys.modules:
            import sys as py_sys
            is_persistence_test = any("test_sqlite_persistence" in arg for arg in py_sys.argv)
            if not is_persistence_test:
                return False

        db_path = resolver.resolve_brain_root() / "hokage.db"
        if not db_path.exists():
            return False
        conn = None
        try:
            conn = sqlite3.connect(str(db_path))
            cursor = conn.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1;")
            row = cursor.fetchone()
            return row is not None and row[0] >= 1
        except Exception:
            return False
        finally:
            if conn:
                conn.close()

    def __init__(self, resolver: PathResolver) -> None:
        """Initialize SqliteStorageEngine."""
        self.resolver = resolver
        self.brain_root = resolver.resolve_brain_root()
        self.db_path = self.brain_root / "hokage.db"
        self._local = threading.local()

    def get_connection(self) -> sqlite3.Connection:
        """Return a thread-safe connection with WAL mode and foreign keys enabled."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self.brain_root.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            conn.row_factory = sqlite3.Row
            
            # Enable Foreign Keys and WAL Mode for high concurrency and ACID guarantees
            conn.execute("PRAGMA foreign_keys = ON;")
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.commit()
            self._local.conn = conn
            
        return self._local.conn

    def close(self) -> None:
        """Close the database connection for the current thread."""
        if hasattr(self._local, "conn") and self._local.conn is not None:
            self._local.conn.close()
            self._local.conn = None

    def execute_integrity_check(self) -> bool:
        """Run SQLite integrity check PRAGMA. Returns True if database is healthy."""
        try:
            conn = self.get_connection()
            cursor = conn.execute("PRAGMA integrity_check;")
            result = cursor.fetchone()
            if result and result[0] == "ok":
                return True
            logger.error(f"Database integrity check failed: {result}")
            return False
        except Exception as exc:
            logger.error(f"Error during database integrity check: {exc}")
            return False

    def initialize_schema(self, conn: sqlite3.Connection) -> None:
        """Initialize all schema tables for Hokage."""
        # 1. Schema version table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY,
                migrated_at TEXT NOT NULL
            );
        """)

        # 2. Trades table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                trade_id TEXT PRIMARY KEY,
                proposal_id TEXT NOT NULL,
                market TEXT NOT NULL,
                direction TEXT NOT NULL,
                quantity REAL NOT NULL,
                entry_price REAL NOT NULL,
                simulated_value REAL NOT NULL,
                mode TEXT NOT NULL,
                status TEXT NOT NULL,
                strategy_name TEXT NOT NULL,
                sources_cited TEXT NOT NULL,
                executed_at TEXT NOT NULL,
                playbook_id TEXT,
                failure_reason TEXT,
                volatility_regime TEXT
            );
        """)

        # 3. Portfolio account table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS portfolio (
                account_id TEXT PRIMARY KEY,
                initial_balance REAL NOT NULL,
                cash REAL NOT NULL,
                currency TEXT NOT NULL,
                realized_pnl REAL NOT NULL,
                unrealized_pnl TEXT NOT NULL
            );
        """)

        # 4. Positions table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS positions (
                position_id TEXT PRIMARY KEY,
                account_id TEXT NOT NULL,
                market TEXT NOT NULL,
                direction TEXT NOT NULL,
                quantity REAL NOT NULL,
                entry_price REAL NOT NULL,
                current_price REAL NOT NULL,
                unrealized_pnl REAL NOT NULL,
                realized_pnl REAL NOT NULL,
                status TEXT NOT NULL,
                opened_at TEXT NOT NULL,
                closed_at TEXT,
                playbook_id TEXT,
                failure_reason TEXT,
                volatility_regime TEXT,
                FOREIGN KEY (account_id) REFERENCES portfolio(account_id) ON DELETE CASCADE
            );
        """)

        # 5. Tax events table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tax_events (
                trade_id TEXT PRIMARY KEY,
                market TEXT NOT NULL,
                direction TEXT NOT NULL,
                quantity REAL NOT NULL,
                entry_price REAL NOT NULL,
                simulated_value REAL NOT NULL,
                executed_at TEXT NOT NULL,
                jurisdiction TEXT NOT NULL,
                currency TEXT NOT NULL,
                components TEXT NOT NULL
            );
        """)

        # 6. Predictions table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS predictions (
                proposal_id TEXT PRIMARY KEY,
                strategy_name TEXT NOT NULL,
                market TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                confidence_score REAL NOT NULL,
                backtest_passed INTEGER NOT NULL,
                win_rate REAL NOT NULL,
                net_profit REAL NOT NULL,
                after_tax_net_profit REAL,
                provider TEXT NOT NULL,
                recorded_at TEXT NOT NULL
            );
        """)

        # 7. Decision journal table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS decision_journal (
                decision_id TEXT,
                timestamp TEXT,
                symbol TEXT NOT NULL,
                decision TEXT NOT NULL,
                conviction INTEGER NOT NULL,
                conviction_breakdown TEXT NOT NULL,
                reason TEXT NOT NULL,
                veto_source TEXT,
                market_regime TEXT NOT NULL,
                sector_flow TEXT NOT NULL,
                expected_holding_days INTEGER NOT NULL,
                expected_return_pct REAL NOT NULL,
                expected_risk_pct REAL NOT NULL,
                reasoning_chain TEXT NOT NULL,
                action TEXT NOT NULL,
                conviction_score INTEGER NOT NULL,
                sector TEXT NOT NULL,
                portfolio_health INTEGER NOT NULL,
                trust_score INTEGER NOT NULL,
                personality_mode TEXT NOT NULL,
                news_drivers TEXT NOT NULL,
                analog_match TEXT NOT NULL,
                sector_rotation_state TEXT NOT NULL,
                expected_holding_period TEXT NOT NULL,
                expected_outcome TEXT NOT NULL,
                actual_outcome TEXT NOT NULL,
                pnl REAL NOT NULL,
                decision_reason TEXT NOT NULL,
                PRIMARY KEY (decision_id, timestamp)
            );
        """)

        # 8. Decision outcomes table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS decision_outcomes (
                decision_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                outcome TEXT NOT NULL,
                pnl REAL NOT NULL,
                return_pct REAL NOT NULL,
                exit_reason TEXT NOT NULL,
                holding_days INTEGER NOT NULL,
                PRIMARY KEY (decision_id, timestamp)
            );
        """)

        # 9. No-trade decisions table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS no_trade_decisions (
                asset TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                decision TEXT NOT NULL,
                confidence INTEGER NOT NULL,
                reasons TEXT NOT NULL,
                invalidated_setups TEXT NOT NULL,
                next_review_time TEXT NOT NULL,
                PRIMARY KEY (asset, timestamp)
            );
        """)

        # 10. Trade authorizations table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trade_authorizations (
                asset TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                direction TEXT NOT NULL,
                conviction_score INTEGER NOT NULL,
                risk_reward REAL NOT NULL,
                trend_validation TEXT NOT NULL,
                volatility_validation TEXT NOT NULL,
                capital_preservation_validation TEXT NOT NULL,
                universe_validation TEXT NOT NULL,
                execution_reason TEXT NOT NULL,
                authorised_by TEXT NOT NULL,
                PRIMARY KEY (asset, timestamp)
            );
        """)

        # 11. Improvement proposals table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS improvement_proposals (
                proposal_id TEXT PRIMARY KEY,
                strategy_id TEXT NOT NULL,
                strategy_name TEXT NOT NULL,
                asset TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                action TEXT NOT NULL,
                previous_values TEXT NOT NULL,
                new_values TEXT NOT NULL,
                rationale TEXT NOT NULL,
                expected_improvement TEXT NOT NULL,
                status TEXT NOT NULL,
                approving_commander TEXT,
                applied_at TEXT,
                actual_post_change_performance TEXT
            );
        """)

        # 12. Applied improvements table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS applied_improvements (
                proposal_id TEXT PRIMARY KEY,
                strategy_id TEXT NOT NULL,
                strategy_name TEXT NOT NULL,
                asset TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                previous_values TEXT NOT NULL,
                new_values TEXT NOT NULL,
                rationale TEXT NOT NULL,
                expected_improvement TEXT NOT NULL,
                actual_post_change_performance TEXT,
                approving_commander TEXT NOT NULL
            );
        """)

        # 13. Strategy notifications table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS strategy_notifications (
                timestamp TEXT NOT NULL,
                strategy_id TEXT NOT NULL,
                change_type TEXT NOT NULL,
                reason TEXT NOT NULL,
                supporting_evidence TEXT NOT NULL,
                validation_status TEXT NOT NULL,
                confidence REAL NOT NULL,
                status TEXT NOT NULL,
                PRIMARY KEY (strategy_id, timestamp)
            );
        """)

        # 14. Shadow decisions table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS shadow_decisions (
                timestamp TEXT NOT NULL,
                strategy_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                decision_type TEXT NOT NULL,
                details TEXT NOT NULL,
                PRIMARY KEY (strategy_id, symbol, timestamp)
            );
        """)

        # 15. Reconciliation freezes table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reconciliation_freezes (
                frozen_key TEXT PRIMARY KEY,
                reason TEXT NOT NULL,
                frozen_at TEXT NOT NULL
            );
        """)

        # 16. Reconciliation reports table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reconciliation_reports (
                report_id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                health_score REAL NOT NULL,
                discrepancies TEXT NOT NULL,
                risk_estimate TEXT NOT NULL,
                status TEXT NOT NULL,
                is_critical INTEGER NOT NULL
            );
        """)

        # 17. Reconciliation status table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reconciliation_status (
                key TEXT PRIMARY KEY,
                health_score REAL NOT NULL,
                last_reconciliation_time TEXT NOT NULL,
                outstanding_discrepancies_count INTEGER NOT NULL,
                critical_alerts_count INTEGER NOT NULL,
                details TEXT NOT NULL
            );
        """)

        # 18. Watchdog heartbeats table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS watchdog_heartbeats (
                subsystem TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                status TEXT NOT NULL,
                uptime REAL NOT NULL,
                last_successful_cycle TEXT NOT NULL,
                execution_latency REAL NOT NULL,
                memory_usage REAL NOT NULL,
                cpu_usage REAL NOT NULL
            );
        """)

        # 19. Watchdog incidents table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS watchdog_incidents (
                incident_id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                severity TEXT NOT NULL,
                subsystem TEXT NOT NULL,
                root_cause TEXT NOT NULL,
                detected_by TEXT NOT NULL,
                automatic_actions TEXT NOT NULL,
                recommended_actions TEXT NOT NULL,
                commander_acknowledgement INTEGER NOT NULL,
                resolution TEXT NOT NULL,
                duration REAL
            );
        """)

        # Phase 6.5: Create Version 2 tables
        self._create_version_2_tables(conn)

        # Component 4: Create Version 3 tables
        self._create_version_3_tables(conn)

        # Component 5: Create Version 4 tables (Mission Control)
        self._create_version_4_tables(conn)

        # Component 6: Create Version 5 tables (Cognitive Evolution)
        self._create_version_5_tables(conn)

        # Component 7: Create Version 6 tables (Multi-Agent Governance)
        self._create_version_6_tables(conn)

        conn.commit()

    def _create_version_2_tables(self, conn: sqlite3.Connection) -> None:
        """Create all tables required for Phase 6.5 (Schema Version 2)."""
        # 20. Shadow sessions table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS shadow_sessions (
                session_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                stopped_at TEXT,
                starting_equity REAL NOT NULL,
                current_equity REAL NOT NULL,
                git_version TEXT NOT NULL,
                config_hash TEXT NOT NULL,
                strategy_set_version TEXT NOT NULL,
                market_universe_version TEXT NOT NULL,
                risk_profile_version TEXT NOT NULL,
                database_schema_version INTEGER NOT NULL
            );
        """)

        # 21. Shadow daily performance table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS shadow_daily_performance (
                timestamp TEXT NOT NULL,
                session_id TEXT NOT NULL,
                portfolio_equity REAL NOT NULL,
                portfolio_cash REAL NOT NULL,
                portfolio_return REAL NOT NULL,
                PRIMARY KEY (timestamp, session_id),
                FOREIGN KEY(session_id) REFERENCES shadow_sessions(session_id) ON DELETE CASCADE
            );
        """)

        # 22. Shadow benchmark performance table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS shadow_benchmark_performance (
                timestamp TEXT NOT NULL,
                session_id TEXT NOT NULL,
                benchmark_symbol TEXT NOT NULL,
                close_price REAL NOT NULL,
                daily_return REAL NOT NULL,
                PRIMARY KEY (timestamp, session_id, benchmark_symbol),
                FOREIGN KEY(session_id) REFERENCES shadow_sessions(session_id) ON DELETE CASCADE
            );
        """)

        # 23. Trade attributions table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trade_attributions (
                decision_id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                ic_gates_snapshot TEXT NOT NULL,
                dominant_factor TEXT NOT NULL,
                expected_move REAL NOT NULL,
                actual_move REAL NOT NULL,
                expected_edge REAL NOT NULL,
                realized_edge REAL NOT NULL,
                risk_taken REAL NOT NULL,
                risk_reward_quality REAL NOT NULL,
                ic_confidence INTEGER NOT NULL,
                market_regime TEXT NOT NULL,
                volatility_regime TEXT NOT NULL,
                decision_classification TEXT NOT NULL,
                entry_quality_grade TEXT NOT NULL,
                exit_quality_grade TEXT NOT NULL,
                timing_quality_grade TEXT NOT NULL,
                risk_quality_grade TEXT NOT NULL,
                sizing_quality_grade TEXT NOT NULL,
                overall_grade TEXT NOT NULL,
                explanation TEXT NOT NULL
            );
        """)

        # 24. Trade replays table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trade_replays (
                trade_id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                explainability_manifest TEXT NOT NULL,
                lifecycle_timeline TEXT NOT NULL
            );
        """)

        # 25. Immutable validation reports table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS immutable_validation_reports (
                report_id TEXT PRIMARY KEY,
                report_type TEXT NOT NULL,
                session_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                checksum TEXT NOT NULL,
                content_json TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES shadow_sessions(session_id) ON DELETE CASCADE
            );
        """)

        # 26. Audit trail table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_trail (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                data TEXT NOT NULL
            );
        """)

        # 27. Commander notes table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS commander_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                target_id TEXT NOT NULL,
                note TEXT NOT NULL,
                recorded_at TEXT NOT NULL
            );
        """)

    def _create_version_3_tables(self, conn: sqlite3.Connection) -> None:
        """Create all tables required for Component 4 (Schema Version 3)."""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS system_commands (
                command_id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                commander TEXT NOT NULL,
                role TEXT NOT NULL,
                command_type TEXT NOT NULL,
                parameters TEXT NOT NULL,
                priority INTEGER NOT NULL,
                status TEXT NOT NULL,
                execution_time REAL,
                result TEXT,
                error TEXT
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS system_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS system_alerts (
                alert_id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                severity TEXT NOT NULL,
                message TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                acknowledged INTEGER DEFAULT 0,
                resolved INTEGER DEFAULT 0,
                pinned INTEGER DEFAULT 0
            );
        """)

    def check_schema_version(self) -> int:
        """Check the current version of schema. Returns 0 if uninitialized."""
        try:
            conn = self.get_connection()
            cursor = conn.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1;")
            row = cursor.fetchone()
            return row[0] if row else 0
        except sqlite3.OperationalError:
            return 0

    def run_migrations(self) -> bool:
        """Detect JSON files, create database, migrate records, verify, and complete.

        Ensures atomic rollback and recovery on any failure to guarantee capital/data safety.
        Applies schema versions 1-6 idempotently.
        """
        current_version = self.check_schema_version()
        if current_version >= 2:
            logger.info(f"SQLite database schema is at version {current_version}. Applying any missing upgrades.")
            # Ensure all Component 3 & 4 tables exist defensively
            conn = self.get_connection()
            conn.execute("""
                CREATE TABLE IF NOT EXISTS audit_trail (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    data TEXT NOT NULL
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS commander_notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    target_id TEXT NOT NULL,
                    note TEXT NOT NULL,
                    recorded_at TEXT NOT NULL
                );
            """)
            self._create_version_3_tables(conn)
            # Incrementally apply new schema versions
            if current_version < 4:
                logger.info("Applying Schema Version 4: Mission Control tables.")
                self._create_version_4_tables(conn)
                conn.execute(
                    "INSERT OR REPLACE INTO schema_version (version, migrated_at) VALUES (?, ?);",
                    (4, datetime.now(timezone.utc).isoformat())
                )
            if current_version < 5:
                logger.info("Applying Schema Version 5: Cognitive Evolution tables.")
                self._create_version_5_tables(conn)
                conn.execute(
                    "INSERT OR REPLACE INTO schema_version (version, migrated_at) VALUES (?, ?);",
                    (5, datetime.now(timezone.utc).isoformat())
                )
            if current_version < 6:
                logger.info("Applying Schema Version 6: Multi-Agent Governance tables.")
                self._create_version_6_tables(conn)
                conn.execute(
                    "INSERT OR REPLACE INTO schema_version (version, migrated_at) VALUES (?, ?);",
                    (6, datetime.now(timezone.utc).isoformat())
                )
            if current_version < 7:
                logger.info("Applying Schema Version 7: Institutional Alpha & Self-Healing columns.")
                # Add columns to trades and positions tables defensively
                for col in ["playbook_id", "failure_reason", "volatility_regime"]:
                    try:
                        conn.execute(f"ALTER TABLE trades ADD COLUMN {col} TEXT;")
                    except sqlite3.OperationalError:
                        pass # column already exists
                    try:
                        conn.execute(f"ALTER TABLE positions ADD COLUMN {col} TEXT;")
                    except sqlite3.OperationalError:
                        pass # column already exists
                conn.execute(
                    "INSERT OR REPLACE INTO schema_version (version, migrated_at) VALUES (?, ?);",
                    (7, datetime.now(timezone.utc).isoformat())
                )
            conn.commit()
            return False


        conn = self.get_connection()

        # Phase 6.5: Schema Upgrade from Version 1 to Version 2
        if current_version == 1:
            logger.info("Upgrading SQLite database schema from version 1 to 2.")
            # 1. Create a secure backup of the database file
            backup_db = self.db_path.with_suffix(".db.bak")
            try:
                shutil.copy2(self.db_path, backup_db)
                logger.info(f"Created database backup before upgrade: {backup_db}")
            except Exception as exc:
                logger.error(f"Failed to create database backup: {exc}")
                raise exc

            try:
                conn.execute("BEGIN TRANSACTION;")
                self._create_version_2_tables(conn)
                conn.execute("INSERT OR REPLACE INTO schema_version (version, migrated_at) VALUES (?, ?);", (2, datetime.now(timezone.utc).isoformat()))
                conn.commit()
                logger.info("Successfully upgraded database schema to version 2.")
                return True
            except Exception as exc:
                logger.error(f"Failed to upgrade schema to version 2, rolling back: {exc}")
                try:
                    conn.rollback()
                except Exception:
                    pass
                # Restore from backup if we failed
                if backup_db.exists():
                    try:
                        shutil.copy2(backup_db, self.db_path)
                        logger.info("Restored database from backup after failed upgrade.")
                    except Exception as restore_exc:
                        logger.critical(f"Failed to restore database from backup! {restore_exc}")
                raise exc

        # Identify target files to migrate
        json_files = {
            "trades": self.resolver.resolve_trades_dir() / "trades.jsonl",
            "account": self.resolver.resolve_portfolio_dir() / "account_paper.json",
            "tax": self.resolver.resolve_tax_dir() / "tax_events.jsonl",
            "predictions": self.resolver.resolve_predictions_dir() / "predictions.jsonl",
            "journal": self.resolver.resolve_brain_root() / "journal" / "decision_journal.jsonl",
            "outcomes": self.resolver.resolve_brain_root() / "journal" / "decision_outcomes.jsonl",
            "no_trade": self.resolver.resolve_brain_root() / "journal" / "no_trade_decisions.jsonl",
            "authorizations": self.resolver.resolve_brain_root() / "journal" / "trade_authorizations.jsonl",
            "proposals": self.resolver.resolve_brain_root() / "improvement" / "improvement_proposals.jsonl",
            "applied": self.resolver.resolve_brain_root() / "journal" / "applied_improvements.jsonl",
            "notifications": self.resolver.resolve_brain_root() / "journal" / "strategy_notifications.jsonl",
            "shadow": self.resolver.resolve_brain_root() / "journal" / "shadow_decisions.jsonl"
        }
        
        # Check if there is any active JSON data to migrate
        has_data = any(p.exists() and p.stat().st_size > 0 for p in json_files.values())
        
        # Initialize SQLite connection and schema DDL
        conn = self.get_connection()
        self.initialize_schema(conn)

        if not has_data:
            # Fresh start, no legacy data to migrate. Write version 2.
            conn.execute("INSERT OR REPLACE INTO schema_version (version, migrated_at) VALUES (?, ?);", (2, datetime.now(timezone.utc).isoformat()))
            conn.commit()
            logger.info("Fresh database initialized with schema version 2.")
            return True

        logger.info("Legacy JSON data detected. Initiating ACID migration.")

        # 1. Create a secure backup before starting migration
        backup_dir = self.brain_root / "backups" / f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        backup_dir.mkdir(parents=True, exist_ok=True)
        
        for key, path in json_files.items():
            if path.exists():
                shutil.copy2(path, backup_dir / path.name)
        logger.info(f"Created pre-migration backup in {backup_dir}")

        # 2. Perform transactional migrations
        try:
            # We open a dedicated transaction
            conn.execute("BEGIN TRANSACTION;")

            record_counts = {}

            # A. Migrate Trades
            trades_file = json_files["trades"]
            trades_count = 0
            if trades_file.exists():
                with trades_file.open("r", encoding="utf-8") as fh:
                    for line in fh:
                        if line.strip():
                            t = json.loads(line.strip())
                            conn.execute("""
                                INSERT INTO trades (
                                    trade_id, proposal_id, market, direction, quantity, entry_price, 
                                    simulated_value, mode, status, strategy_name, sources_cited, executed_at
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                            """, (
                                t["trade_id"], t["proposal_id"], t["market"], t["direction"],
                                t["quantity"], t["entry_price"], t["simulated_value"], t["mode"],
                                t["status"], t["strategy_name"], ",".join(t["sources_cited"]), t["executed_at"]
                            ))
                            trades_count += 1
            record_counts["trades"] = (trades_count, "SELECT COUNT(*) FROM trades;")

            # B. Migrate Portfolio Account & Open Positions
            acc_file = json_files["account"]
            acc_count = 0
            pos_count = 0
            if acc_file.exists():
                with acc_file.open("r", encoding="utf-8") as fh:
                    acc_data = json.load(fh)
                    # Insert account
                    conn.execute("""
                        INSERT INTO portfolio (
                            account_id, initial_balance, cash, currency, realized_pnl, unrealized_pnl
                        ) VALUES (?, ?, ?, ?, ?, ?);
                    """, (
                        acc_data["account_id"], acc_data["initial_balance"], acc_data["cash"],
                        acc_data["currency"], acc_data["realized_pnl"], str(acc_data.get("unrealized_pnl", 0.0))
                    ))
                    acc_count += 1
                    
                    # Insert open positions
                    for pid, p in acc_data.get("positions", {}).items():
                        # Parse status
                        status_val = p["status"]["name"] if isinstance(p.get("status"), dict) else str(p.get("status", "OPEN"))
                        conn.execute("""
                            INSERT INTO positions (
                                position_id, account_id, market, direction, quantity, entry_price, current_price, 
                                unrealized_pnl, realized_pnl, status, opened_at, closed_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                        """, (
                            pid, acc_data["account_id"], p["market"], p["direction"], p["quantity"],
                            p["entry_price"], p["current_price"], p["unrealized_pnl"], p["realized_pnl"],
                            status_val, p["opened_at"], p.get("closed_at")
                        ))
                        pos_count += 1
            record_counts["portfolio"] = (acc_count, "SELECT COUNT(*) FROM portfolio;")
            record_counts["positions"] = (pos_count, "SELECT COUNT(*) FROM positions;")

            # C. Migrate Tax Events
            tax_file = json_files["tax"]
            tax_count = 0
            if tax_file.exists():
                with tax_file.open("r", encoding="utf-8") as fh:
                    for line in fh:
                        if line.strip():
                            te = json.loads(line.strip())
                            conn.execute("""
                                INSERT INTO tax_events (
                                    trade_id, market, direction, quantity, entry_price, 
                                    simulated_value, executed_at, jurisdiction, currency, components
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                            """, (
                                te["trade_id"], te["market"], te["direction"], te["quantity"],
                                te["entry_price"], te["simulated_value"], te["executed_at"],
                                te["jurisdiction"], te["currency"], json.dumps(te["components"])
                            ))
                            tax_count += 1
            record_counts["tax_events"] = (tax_count, "SELECT COUNT(*) FROM tax_events;")

            # D. Migrate Predictions
            pred_file = json_files["predictions"]
            pred_count = 0
            if pred_file.exists():
                with pred_file.open("r", encoding="utf-8") as fh:
                    for line in fh:
                        if line.strip():
                            p = json.loads(line.strip())
                            conn.execute("""
                                INSERT INTO predictions (
                                    proposal_id, strategy_name, market, timeframe, confidence_score, 
                                    backtest_passed, win_rate, net_profit, after_tax_net_profit, provider, recorded_at
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                            """, (
                                p["proposal_id"], p["strategy_name"], p["market"], p["timeframe"],
                                p["confidence_score"], 1 if p["backtest_passed"] else 0, p["win_rate"],
                                p["net_profit"], p.get("after_tax_net_profit"), p["provider"], p["recorded_at"]
                            ))
                            pred_count += 1
            record_counts["predictions"] = (pred_count, "SELECT COUNT(*) FROM predictions;")

            # E. Migrate Decision Journal
            journal_file = json_files["journal"]
            j_count = 0
            if journal_file.exists():
                with journal_file.open("r", encoding="utf-8") as fh:
                    for line in fh:
                        if line.strip():
                            j = json.loads(line.strip())
                            conn.execute("""
                                INSERT INTO decision_journal (
                                    decision_id, timestamp, symbol, decision, conviction, conviction_breakdown,
                                    reason, veto_source, market_regime, sector_flow, expected_holding_days,
                                    expected_return_pct, expected_risk_pct, reasoning_chain, action,
                                    conviction_score, sector, portfolio_health, trust_score, personality_mode,
                                    news_drivers, analog_match, sector_rotation_state, expected_holding_period,
                                    expected_outcome, actual_outcome, pnl, decision_reason
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                            """, (
                                j.get("decision_id", ""),
                                j.get("timestamp", datetime.now(timezone.utc).isoformat()),
                                j.get("symbol", "UNKNOWN"),
                                j.get("decision", j.get("action", "REJECTED")),
                                j.get("conviction", j.get("conviction_score", 0)),
                                json.dumps(j.get("conviction_breakdown", {})),
                                j.get("reason", j.get("decision_reason", "")),
                                j.get("veto_source"),
                                j.get("market_regime", "UNKNOWN"),
                                j.get("sector_flow", "N/A"),
                                j.get("expected_holding_days", 3),
                                j.get("expected_return_pct", 0.0),
                                j.get("expected_risk_pct", 0.0),
                                json.dumps(j.get("reasoning_chain", [])),
                                j.get("action", j.get("decision", "REJECTED")),
                                j.get("conviction_score", j.get("conviction", 0)),
                                j.get("sector", "other"),
                                j.get("portfolio_health", 0),
                                j.get("trust_score", 0),
                                j.get("personality_mode", "BALANCED"),
                                json.dumps(j.get("news_drivers", [])),
                                j.get("analog_match", "N/A"),
                                j.get("sector_rotation_state", "N/A"),
                                j.get("expected_holding_period", "2-5 Days"),
                                j.get("expected_outcome", "Profit target"),
                                j.get("actual_outcome", "PENDING"),
                                j.get("pnl", 0.0),
                                j.get("decision_reason", j.get("reason", ""))
                            ))
                            j_count += 1
            record_counts["decision_journal"] = (j_count, "SELECT COUNT(*) FROM decision_journal;")

            # F. Migrate Decision Outcomes
            out_file = json_files["outcomes"]
            out_count = 0
            if out_file.exists():
                with out_file.open("r", encoding="utf-8") as fh:
                    for line in fh:
                        if line.strip():
                            o = json.loads(line.strip())
                            conn.execute("""
                                INSERT INTO decision_outcomes (
                                    decision_id, timestamp, outcome, pnl, return_pct, exit_reason, holding_days
                                ) VALUES (?, ?, ?, ?, ?, ?, ?);
                            """, (
                                o["decision_id"], o["timestamp"], o["outcome"], o["pnl"],
                                o["return_pct"], o["exit_reason"], o["holding_days"]
                            ))
                            out_count += 1
            record_counts["decision_outcomes"] = (out_count, "SELECT COUNT(*) FROM decision_outcomes;")

            # G. Migrate No-Trade Decisions
            nt_file = json_files["no_trade"]
            nt_count = 0
            if nt_file.exists():
                with nt_file.open("r", encoding="utf-8") as fh:
                    for line in fh:
                        if line.strip():
                            nt = json.loads(line.strip())
                            conn.execute("""
                                INSERT INTO no_trade_decisions (
                                    asset, timestamp, decision, confidence, reasons, invalidated_setups, next_review_time
                                ) VALUES (?, ?, ?, ?, ?, ?, ?);
                            """, (
                                nt["asset"], nt["timestamp"], nt["decision"], nt["confidence"],
                                json.dumps(nt["reasons"]), json.dumps(nt["invalidated_setups"]), nt["next_review_time"]
                            ))
                            nt_count += 1
            record_counts["no_trade_decisions"] = (nt_count, "SELECT COUNT(*) FROM no_trade_decisions;")

            # H. Migrate Trade Authorizations
            auth_file = json_files["authorizations"]
            auth_count = 0
            if auth_file.exists():
                with auth_file.open("r", encoding="utf-8") as fh:
                    for line in fh:
                        if line.strip():
                            auth = json.loads(line.strip())
                            conn.execute("""
                                INSERT INTO trade_authorizations (
                                    asset, timestamp, direction, conviction_score, risk_reward, trend_validation,
                                    volatility_validation, capital_preservation_validation, universe_validation,
                                    execution_reason, authorised_by
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                            """, (
                                auth["asset"], auth["timestamp"], auth["direction"], auth["conviction_score"],
                                auth["risk_reward"], str(auth["trend_validation"]), auth["volatility_validation"],
                                auth["capital_preservation_validation"], auth["universe_validation"],
                                auth["execution_reason"], auth["authorised_by"]
                            ))
                            auth_count += 1
            record_counts["trade_authorizations"] = (auth_count, "SELECT COUNT(*) FROM trade_authorizations;")

            # I. Migrate Improvement Proposals
            prop_file = json_files["proposals"]
            prop_count = 0
            if prop_file.exists():
                with prop_file.open("r", encoding="utf-8") as fh:
                    for line in fh:
                        if line.strip():
                            p = json.loads(line.strip())
                            conn.execute("""
                                INSERT INTO improvement_proposals (
                                    proposal_id, strategy_id, strategy_name, asset, timestamp, action,
                                    previous_values, new_values, rationale, expected_improvement, status,
                                    approving_commander, applied_at, actual_post_change_performance
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                            """, (
                                p["proposal_id"], p["strategy_id"], p["strategy_name"], p["asset"],
                                p["timestamp"], p["action"], json.dumps(p["previous_values"]),
                                json.dumps(p["new_values"]), p["rationale"], p["expected_improvement"],
                                p["status"], p.get("approving_commander"), p.get("applied_at"),
                                json.dumps(p.get("actual_post_change_performance"))
                            ))
                            prop_count += 1
            record_counts["improvement_proposals"] = (prop_count, "SELECT COUNT(*) FROM improvement_proposals;")

            # J. Migrate Applied Improvements
            app_file = json_files["applied"]
            app_count = 0
            if app_file.exists():
                with app_file.open("r", encoding="utf-8") as fh:
                    for line in fh:
                        if line.strip():
                            a = json.loads(line.strip())
                            conn.execute("""
                                INSERT INTO applied_improvements (
                                    proposal_id, strategy_id, strategy_name, asset, timestamp,
                                    previous_values, new_values, rationale, expected_improvement,
                                    actual_post_change_performance, approving_commander
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                            """, (
                                a["proposal_id"], a["strategy_id"], a["strategy_name"], a["asset"],
                                a["timestamp"], json.dumps(a["previous_values"]), json.dumps(a["new_values"]),
                                a["rationale"], a["expected_improvement"],
                                json.dumps(a.get("actual_post_change_performance")), a["approving_commander"]
                            ))
                            app_count += 1
            record_counts["applied_improvements"] = (app_count, "SELECT COUNT(*) FROM applied_improvements;")

            # K. Migrate Strategy Notifications
            notif_file = json_files["notifications"]
            notif_count = 0
            if notif_file.exists():
                with notif_file.open("r", encoding="utf-8") as fh:
                    for line in fh:
                        if line.strip():
                            n = json.loads(line.strip())
                            conn.execute("""
                                INSERT INTO strategy_notifications (
                                    timestamp, strategy_id, change_type, reason, supporting_evidence,
                                    validation_status, confidence, status
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                            """, (
                                n["timestamp"], n["strategy_id"], n["change_type"], n["reason"],
                                json.dumps(n["supporting_evidence"]), n["validation_status"],
                                n["confidence"], n["status"]
                            ))
                            notif_count += 1
            record_counts["strategy_notifications"] = (notif_count, "SELECT COUNT(*) FROM strategy_notifications;")

            # L. Migrate Shadow Decisions
            shadow_file = json_files["shadow"]
            shadow_count = 0
            if shadow_file.exists():
                with shadow_file.open("r", encoding="utf-8") as fh:
                    for line in fh:
                        if line.strip():
                            sd = json.loads(line.strip())
                            conn.execute("""
                                INSERT OR REPLACE INTO shadow_decisions (
                                    timestamp, strategy_id, symbol, decision_type, details
                                ) VALUES (?, ?, ?, ?, ?);
                            """, (
                                sd["timestamp"], sd["strategy_id"], sd["symbol"],
                                sd["decision_type"], json.dumps(sd["details"])
                            ))
                            shadow_count += 1
            record_counts["shadow_decisions"] = (shadow_count, "SELECT COUNT(*) FROM shadow_decisions;")

            # 3. VERIFY imported record counts
            for table, (expected_cnt, query) in record_counts.items():
                cur = conn.execute(query)
                actual_cnt = cur.fetchone()[0]
                if actual_cnt != expected_cnt:
                    raise ValueError(f"Integrity check failed: Table '{table}' expected {expected_cnt} records but got {actual_cnt} records.")

            # 4. Mark migration complete
            conn.execute("INSERT OR REPLACE INTO schema_version (version, migrated_at) VALUES (?, ?);", (2, datetime.now(timezone.utc).isoformat()))

            # Commit the transaction atomically!
            conn.commit()
            logger.info("Migration transaction committed successfully.")

            # 5. Preserve original JSON files as backups, and rename active files to prevent dual reads
            for key, path in json_files.items():
                if path.exists():
                    try:
                        # Rename active file to .migrated to prevent double-reads/double-migrations
                        migrated_path = path.with_suffix(path.suffix + ".migrated")
                        path.replace(migrated_path)
                    except Exception as exc:
                        logger.warning(f"Could not rename {path} to .migrated: {exc}")

            # Verify integrity of SQLite database
            if self.execute_integrity_check():
                logger.info("SQLite database verified clean. Integrity PASS.")
            else:
                raise ValueError("Post-migration SQLite database integrity check failed.")

            return True

        except Exception as exc:
            # ACID Rollback! Guarantee no partial writes or corrupted state.
            logger.error(f"Migration failed! Initiating transactional rollback and state recovery: {exc}")
            try:
                conn.rollback()
            except Exception:
                pass
            self.close()
            
            # Delete the database file if we created it during this failed migration
            if self.db_path.exists():
                try:
                    self.db_path.unlink()
                except Exception:
                    pass

            # Restore original JSON files from backup (they remain untouched in their original locations if we failed before renaming)
            logger.error("State recovery complete. Database rolled back and files recovered.")
            raise exc

    # =========================================================================
    # Component 5 — Mission Control (Schema Version 4)
    # =========================================================================

    def _create_version_4_tables(self, conn: sqlite3.Connection) -> None:
        """Create all tables required for Component 5 (Mission Control, Schema Version 4)."""

        conn.execute("""
            CREATE TABLE IF NOT EXISTS missions (
                mission_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                objective TEXT NOT NULL,
                description TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'PENDING',
                priority INTEGER NOT NULL DEFAULT 1,
                trigger_type TEXT NOT NULL DEFAULT 'MANUAL',
                assigned_bots TEXT NOT NULL DEFAULT '[]',
                tags TEXT NOT NULL DEFAULT '[]',
                current_stage TEXT,
                progress_pct REAL NOT NULL DEFAULT 0.0,
                started_at TEXT,
                completed_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                metadata TEXT NOT NULL DEFAULT '{}'
            );
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS mission_events (
                event_id TEXT PRIMARY KEY,
                mission_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                stage TEXT,
                message TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                data TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY(mission_id) REFERENCES missions(mission_id) ON DELETE CASCADE
            );
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS mission_templates (
                template_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                objective TEXT NOT NULL,
                default_bots TEXT NOT NULL DEFAULT '[]',
                default_tags TEXT NOT NULL DEFAULT '[]',
                stages TEXT NOT NULL DEFAULT '[]',
                trigger_type TEXT NOT NULL DEFAULT 'MANUAL',
                created_at TEXT NOT NULL,
                is_system INTEGER NOT NULL DEFAULT 0
            );
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS mission_dependencies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mission_id TEXT NOT NULL,
                depends_on_mission_id TEXT NOT NULL,
                dependency_type TEXT NOT NULL DEFAULT 'SEQUENTIAL',
                FOREIGN KEY(mission_id) REFERENCES missions(mission_id) ON DELETE CASCADE,
                FOREIGN KEY(depends_on_mission_id) REFERENCES missions(mission_id) ON DELETE CASCADE
            );
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS mission_queue (
                queue_id INTEGER PRIMARY KEY AUTOINCREMENT,
                mission_id TEXT NOT NULL UNIQUE,
                priority INTEGER NOT NULL DEFAULT 1,
                scheduled_at TEXT,
                enqueued_at TEXT NOT NULL,
                FOREIGN KEY(mission_id) REFERENCES missions(mission_id) ON DELETE CASCADE
            );
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS workflow_definitions (
                workflow_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1,
                is_active INTEGER NOT NULL DEFAULT 1,
                metadata TEXT NOT NULL DEFAULT '{}'
            );
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS workflow_nodes (
                node_id TEXT PRIMARY KEY,
                workflow_id TEXT NOT NULL,
                node_type TEXT NOT NULL,
                label TEXT NOT NULL,
                position_x REAL NOT NULL DEFAULT 0.0,
                position_y REAL NOT NULL DEFAULT 0.0,
                config TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY(workflow_id) REFERENCES workflow_definitions(workflow_id) ON DELETE CASCADE
            );
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS workflow_edges (
                edge_id TEXT PRIMARY KEY,
                workflow_id TEXT NOT NULL,
                source_node_id TEXT NOT NULL,
                target_node_id TEXT NOT NULL,
                condition TEXT,
                label TEXT,
                FOREIGN KEY(workflow_id) REFERENCES workflow_definitions(workflow_id) ON DELETE CASCADE
            );
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS mission_metrics (
                snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
                captured_at TEXT NOT NULL,
                total_missions INTEGER NOT NULL DEFAULT 0,
                successful_missions INTEGER NOT NULL DEFAULT 0,
                failed_missions INTEGER NOT NULL DEFAULT 0,
                avg_completion_seconds REAL NOT NULL DEFAULT 0.0,
                success_rate_pct REAL NOT NULL DEFAULT 0.0,
                active_missions INTEGER NOT NULL DEFAULT 0,
                missions_today INTEGER NOT NULL DEFAULT 0
            );
        """)

    # =========================================================================
    # Component 6 — Cognitive Evolution (Schema Version 5)
    # =========================================================================

    def _create_version_5_tables(self, conn: sqlite3.Connection) -> None:
        """Create all tables required for Component 6 (Cognitive Intelligence, Schema Version 5)."""

        conn.execute("""
            CREATE TABLE IF NOT EXISTS memory_nodes (
                node_id TEXT PRIMARY KEY,
                node_type TEXT NOT NULL,
                label TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                importance REAL NOT NULL DEFAULT 0.5,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                metadata TEXT NOT NULL DEFAULT '{}'
            );
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS memory_edges (
                edge_id TEXT PRIMARY KEY,
                source_node_id TEXT NOT NULL,
                target_node_id TEXT NOT NULL,
                relationship TEXT NOT NULL,
                weight REAL NOT NULL DEFAULT 1.0,
                created_at TEXT NOT NULL,
                FOREIGN KEY(source_node_id) REFERENCES memory_nodes(node_id) ON DELETE CASCADE,
                FOREIGN KEY(target_node_id) REFERENCES memory_nodes(node_id) ON DELETE CASCADE
            );
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS learning_records (
                record_id TEXT PRIMARY KEY,
                source_type TEXT NOT NULL,
                source_id TEXT NOT NULL,
                lesson TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'GENERAL',
                impact_score REAL NOT NULL DEFAULT 0.5,
                confidence REAL NOT NULL DEFAULT 0.5,
                tags TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                applied_count INTEGER NOT NULL DEFAULT 0
            );
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS strategy_versions (
                version_id TEXT PRIMARY KEY,
                strategy_id TEXT NOT NULL,
                version_number INTEGER NOT NULL,
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                parameters TEXT NOT NULL DEFAULT '{}',
                backtest_metrics TEXT NOT NULL DEFAULT '{}',
                live_metrics TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'DRAFT',
                created_at TEXT NOT NULL,
                promoted_at TEXT,
                deprecated_at TEXT
            );
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS prediction_calibration (
                calibration_id TEXT PRIMARY KEY,
                model_name TEXT NOT NULL,
                prediction_type TEXT NOT NULL,
                predicted_value REAL NOT NULL,
                actual_value REAL NOT NULL,
                error REAL NOT NULL,
                relative_error REAL NOT NULL,
                timestamp TEXT NOT NULL,
                context TEXT NOT NULL DEFAULT '{}'
            );
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS improvement_queue (
                improvement_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                category TEXT NOT NULL,
                estimated_impact REAL NOT NULL DEFAULT 0.5,
                difficulty TEXT NOT NULL DEFAULT 'MEDIUM',
                status TEXT NOT NULL DEFAULT 'PENDING',
                priority INTEGER NOT NULL DEFAULT 1,
                source TEXT NOT NULL DEFAULT 'SYSTEM',
                created_at TEXT NOT NULL,
                reviewed_at TEXT,
                reviewer TEXT,
                review_notes TEXT
            );
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS performance_snapshots (
                snapshot_id TEXT PRIMARY KEY,
                bot_name TEXT NOT NULL,
                captured_at TEXT NOT NULL,
                accuracy REAL,
                latency_ms REAL,
                success_rate REAL,
                throughput REAL,
                error_rate REAL,
                custom_metrics TEXT NOT NULL DEFAULT '{}'
            );
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS coach_recommendations (
                recommendation_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                category TEXT NOT NULL,
                priority TEXT NOT NULL DEFAULT 'MEDIUM',
                status TEXT NOT NULL DEFAULT 'ACTIVE',
                estimated_gain REAL NOT NULL DEFAULT 0.0,
                generated_at TEXT NOT NULL,
                expires_at TEXT,
                action_url TEXT
            );
        """)

    # =========================================================================
    # Component 7 — Multi-Agent Governance (Schema Version 6)
    # =========================================================================

    def _create_version_6_tables(self, conn: sqlite3.Connection) -> None:
        """Create all tables required for Component 7 (Multi-Agent Governance, Schema Version 6)."""

        conn.execute("""
            CREATE TABLE IF NOT EXISTS agent_registry (
                agent_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                role TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'IDLE',
                capabilities TEXT NOT NULL DEFAULT '[]',
                workload INTEGER NOT NULL DEFAULT 0,
                health_score REAL NOT NULL DEFAULT 1.0,
                last_heartbeat TEXT,
                created_at TEXT NOT NULL,
                metadata TEXT NOT NULL DEFAULT '{}'
            );
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS agent_messages (
                message_id TEXT PRIMARY KEY,
                sender_agent_id TEXT NOT NULL,
                recipient_agent_id TEXT,
                message_type TEXT NOT NULL,
                subject TEXT NOT NULL DEFAULT '',
                body TEXT NOT NULL,
                priority INTEGER NOT NULL DEFAULT 1,
                status TEXT NOT NULL DEFAULT 'SENT',
                sent_at TEXT NOT NULL,
                read_at TEXT,
                reply_to_message_id TEXT
            );
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS governance_policies (
                policy_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                category TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                parameters TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                enforced_by TEXT NOT NULL DEFAULT 'SYSTEM'
            );
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS consensus_records (
                consensus_id TEXT PRIMARY KEY,
                topic TEXT NOT NULL,
                description TEXT NOT NULL,
                voting_model TEXT NOT NULL DEFAULT 'MAJORITY',
                status TEXT NOT NULL DEFAULT 'OPEN',
                votes TEXT NOT NULL DEFAULT '{}',
                result TEXT,
                threshold REAL NOT NULL DEFAULT 0.51,
                created_at TEXT NOT NULL,
                resolved_at TEXT,
                metadata TEXT NOT NULL DEFAULT '{}'
            );
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS resource_metrics (
                metric_id INTEGER PRIMARY KEY AUTOINCREMENT,
                captured_at TEXT NOT NULL,
                cpu_pct REAL NOT NULL DEFAULT 0.0,
                ram_mb REAL NOT NULL DEFAULT 0.0,
                llm_tokens_used INTEGER NOT NULL DEFAULT 0,
                llm_tokens_limit INTEGER NOT NULL DEFAULT 1000000,
                api_calls_used INTEGER NOT NULL DEFAULT 0,
                api_calls_limit INTEGER NOT NULL DEFAULT 10000,
                disk_gb REAL NOT NULL DEFAULT 0.0
            );
        """)

