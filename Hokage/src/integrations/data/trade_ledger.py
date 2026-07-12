import sqlite3
import os
from datetime import datetime, timezone

DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "shared", "persistence", "hokage.db"
)

class TradeLedger:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()
        
    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    asset TEXT NOT NULL,
                    market TEXT,
                    direction TEXT NOT NULL,
                    entry_price REAL,
                    exit_price REAL,
                    slippage REAL,
                    risk_reward REAL,
                    confidence_score REAL,
                    strategy_name TEXT,
                    playbook_id TEXT,
                    executed_at TEXT
                )
            ''')
            conn.commit()

    def log_trade(self, asset: str, direction: str, entry_price: float, exit_price: float, slippage: float, risk_reward: float, confidence_score: float, strategy_name: str = "Unknown", playbook_id: str = ""):
        timestamp = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO trades (
                    timestamp, asset, market, direction, entry_price, exit_price, slippage, risk_reward, confidence_score, strategy_name, playbook_id, executed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (timestamp, asset, asset, direction, entry_price, exit_price, slippage, risk_reward, confidence_score, strategy_name, playbook_id, timestamp))
            conn.commit()

    def get_all_trades(self, limit: int = 100):
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM trades ORDER BY timestamp DESC LIMIT ?", (limit,))
            return [dict(row) for row in cursor.fetchall()]

ledger = TradeLedger()
