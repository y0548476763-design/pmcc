import sqlite3
import config
from datetime import datetime
from typing import Optional
import pandas as pd

DB_PATH = config.DB_PATH

DDL = """
CREATE TABLE IF NOT EXISTS trades (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp     TEXT NOT NULL,
    ticker        TEXT NOT NULL,
    action        TEXT NOT NULL,
    option_type   TEXT NOT NULL,
    strike        REAL NOT NULL,
    expiry        TEXT NOT NULL,
    qty           INTEGER NOT NULL,
    fill_price    REAL NOT NULL,
    commission    REAL DEFAULT 0.0,
    order_id      TEXT,
    account       TEXT,
    notes         TEXT
);
CREATE TABLE IF NOT EXISTS pnl_snapshots (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp     TEXT NOT NULL,
    ticker        TEXT NOT NULL,
    leaps_value   REAL,
    short_value   REAL,
    net_pnl       REAL,
    cost_basis    REAL
);
"""


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_db() -> None:
    with _conn() as c:
        c.executescript(DDL)


def log_trade(
    ticker: str, action: str, option_type: str,
    strike: float, expiry: str, qty: int, fill_price: float,
    commission: float = 0.0, order_id: str = "",
    account: str = "DEMO", notes: str = "",
) -> int:
    with _conn() as c:
        cur = c.execute(
            """INSERT INTO trades
               (timestamp, ticker, action, option_type, strike, expiry,
                qty, fill_price, commission, order_id, account, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (datetime.utcnow().isoformat(), ticker, action, option_type,
             strike, expiry, qty, fill_price, commission, order_id, account, notes),
        )
        return cur.lastrowid


def snapshot_pnl(ticker: str, leaps_val: float, short_val: float,
                 net_pnl: float, cost_basis: float) -> None:
    with _conn() as c:
        c.execute(
            """INSERT INTO pnl_snapshots
               (timestamp, ticker, leaps_value, short_value, net_pnl, cost_basis)
               VALUES (?,?,?,?,?,?)""",
            (datetime.utcnow().isoformat(), ticker, leaps_val, short_val,
             net_pnl, cost_basis),
        )


def get_trades_df() -> pd.DataFrame:
    with _conn() as c:
        return pd.read_sql_query("SELECT * FROM trades ORDER BY timestamp DESC", c)


def get_pnl_history(ticker: Optional[str] = None) -> pd.DataFrame:
    with _conn() as c:
        if ticker:
            return pd.read_sql_query(
                "SELECT * FROM pnl_snapshots WHERE ticker=? ORDER BY timestamp",
                c, params=(ticker,)
            )
        return pd.read_sql_query(
            "SELECT * FROM pnl_snapshots ORDER BY timestamp", c
        )


# Auto-init on import
init_db()
