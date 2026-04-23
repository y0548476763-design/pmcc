"""
tws_combo.py — Dedicated Combo/BAG order execution engine.
Uses real conIds from the live portfolio + IBKR contract qualification.
Saves all execution data to SQLite for future RL/analysis.
"""
import sqlite3, time, threading, io
from datetime import datetime, timezone
from typing import Optional
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "combo_trades.db")

def _init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS combo_executions (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            ts            TEXT,
            ticker        TEXT,
            sell_strike   REAL,
            sell_expiry   TEXT,
            sell_conid    INTEGER,
            buy_strike    REAL,
            buy_expiry    TEXT,
            buy_conid     INTEGER,
            qty           INTEGER,
            initial_limit REAL,
            fill_price    REAL,
            dte_before    INTEGER,
            dte_after     INTEGER,
            spread_width  REAL,
            escalations   INTEGER,
            fill_seconds  INTEGER,
            order_type    TEXT,
            status        TEXT,
            notes         TEXT
        )
    """)
    conn.commit()
    conn.close()

_init_db()


def _log_execution(ticker, sell_strike, sell_expiry, sell_conid,
                   buy_strike, buy_expiry, buy_conid, qty,
                   initial_limit, fill_price, dte_before, dte_after,
                   spread_width, escalations, fill_seconds, order_type, status, notes=""):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""INSERT INTO combo_executions
        (ts, ticker, sell_strike, sell_expiry, sell_conid,
         buy_strike, buy_expiry, buy_conid, qty, initial_limit,
         fill_price, dte_before, dte_after, spread_width,
         escalations, fill_seconds, order_type, status, notes)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        datetime.now(timezone.utc).isoformat(),
        ticker, sell_strike, sell_expiry, sell_conid,
        buy_strike, buy_expiry, buy_conid, qty, initial_limit,
        fill_price, dte_before, dte_after, spread_width,
        escalations, fill_seconds, order_type, status, notes
    ))
    conn.commit()
    conn.close()


def get_combo_mid_price(ib, ticker: str, sell_conid: int, buy_conid: int) -> float:
    """Request a snapshot quote for the combo to get Bid/Ask/Mid.
    Uses delayed data if live is unavailable.
    """
    try:
        from ib_insync import ComboLeg, Bag
        # Enable delayed data if live not available
        ib.reqMarketDataType(3) 
        
        sell_leg = ComboLeg(conId=sell_conid, ratio=1, action='SELL', exchange='SMART')
        buy_leg  = ComboLeg(conId=buy_conid,  ratio=1, action='BUY',  exchange='SMART')
        bag = Bag(symbol=ticker, currency='USD', exchange='SMART', comboLegs=[sell_leg, buy_leg])
        
        # Non-blocking ticker request
        tickers = ib.reqTickers(bag)
        # Wait up to 5s for data to arrive
        for _ in range(5):
            ib.sleep(1)
            if tickers:
                t = tickers[0]
                bid = t.bid if t.bid and t.bid > 0 else 0
                ask = t.ask if t.ask and t.ask > 0 else 0
                if bid > 0 and ask > 0:
                    return round((bid + ask) / 2, 2)
                if t.last and t.last > 0:
                    return round(t.last, 2)
    except Exception:
        pass
    return 0.0


def execute_combo_roll(ib, sell_conid: int, sell_strike: float, sell_expiry: str,
                       buy_conid: int, buy_strike: float, buy_expiry: str,
                       ticker: str, qty: int,
                       limit_price: float = 0.0,
                       use_market: bool = False,
                       escalation_step_pct: float = 1.0,
                       escalation_wait_secs: int = 60,
                       max_escalations: int = 10,
                       log_cb=None) -> dict:
    """
    Execute a BAG/Combo roll order.
    - If use_market=True: fires MKT order immediately.
    - If limit_price=0: fetches live mid-price from IBKR.
    - Escalates limit price by escalation_step_pct every escalation_wait_secs seconds.
    Returns dict with fill info and data for ML logging.
    """
    from ib_insync import ComboLeg, Bag, LimitOrder, MarketOrder
    from datetime import datetime as dt

    def _log(msg):
        if log_cb: log_cb("INFO", msg)

    _log(f"[COMBO] {ticker}: SELL {sell_strike}/{sell_expiry} -> BUY {buy_strike}/{buy_expiry}")

    # Compute DTEs for logging
    today = datetime.now(timezone.utc).date()
    def _dte(exp_str):
        try:
            s = exp_str.replace('-', '').replace('/', '')
            return (datetime.strptime(s, '%Y%m%d').date() - today).days
        except:
            return 0
    dte_before = _dte(sell_expiry)
    dte_after  = _dte(buy_expiry)

    # Build BAG contract
    sell_leg = ComboLeg(conId=sell_conid, ratio=1, action='SELL', exchange='SMART')
    buy_leg  = ComboLeg(conId=buy_conid,  ratio=1, action='BUY',  exchange='SMART')
    bag = Bag(symbol=ticker, currency='USD', exchange='SMART', comboLegs=[sell_leg, buy_leg])

    # Determine initial price
    if use_market:
        order = MarketOrder('BUY', qty)
        order.tif = 'DAY'
        order_type = 'MKT'
        initial_limit = 0.0
    else:
        if limit_price <= 0:
            limit_price = get_combo_mid_price(ib, ticker, sell_conid, buy_conid)
        if limit_price <= 0:
            limit_price = 1.0  # Fallback
        order = LimitOrder('BUY', qty, round(limit_price, 2))
        order.tif = 'DAY'
        order_type = 'LMT'
        initial_limit = limit_price

    start_time = time.time()
    trade = ib.placeOrder(bag, order)
    _log(f"[COMBO] Submitted orderId={trade.order.orderId} @ {'MKT' if use_market else '$'+str(round(limit_price,2))}")

    # Track escalation
    escalations = 0
    current_price = initial_limit

    while True:
        ib.sleep(1)
        status = trade.orderStatus.status
        filled = trade.orderStatus.filled
        avg_fill = trade.orderStatus.avgFillPrice

        if status == 'Filled':
            elapsed = int(time.time() - start_time)
            spread_width = round(abs(buy_strike - sell_strike), 2)
            _log(f"[COMBO] FILLED! qty={filled} avg=${avg_fill:.2f} in {elapsed}s ({escalations} escals)")
            _log_execution(ticker, sell_strike, sell_expiry, sell_conid,
                           buy_strike, buy_expiry, buy_conid, qty,
                           initial_limit, avg_fill, dte_before, dte_after,
                           spread_width, escalations, elapsed, order_type, 'FILLED')
            return {'status': 'FILLED', 'fill_price': avg_fill, 'qty': filled,
                    'elapsed_sec': elapsed, 'escalations': escalations, 'order_id': trade.order.orderId}

        if status in ('Cancelled', 'Inactive', 'ApiCancelled'):
            _log(f"[COMBO] Order {status}")
            _log_execution(ticker, sell_strike, sell_expiry, sell_conid,
                           buy_strike, buy_expiry, buy_conid, qty,
                           initial_limit, 0, dte_before, dte_after, 0, escalations,
                           int(time.time()-start_time), order_type, status)
            return {'status': status, 'fill_price': 0, 'escalations': escalations}

        # Escalation logic (LMT only)
        if not use_market and max_escalations > 0 and (time.time() - start_time) > escalation_wait_secs * (escalations + 1):
            if escalations >= max_escalations:
                _log(f"[COMBO] Max escalations reached. Cancelling.")
                ib.cancelOrder(trade.order)
                break
            escalations += 1
            current_price = round(current_price * (1.0 + escalation_step_pct / 100.0), 2)
            trade.order.lmtPrice = current_price
            ib.placeOrder(bag, trade.order)  # Modify in place (same orderId)
            _log(f"[COMBO] Escalation #{escalations}: new price=${current_price:.2f}")

        # Safety: stop after 10 minutes
        if time.time() - start_time > 600:
            ib.cancelOrder(trade.order)
            break

    return {'status': 'TIMEOUT', 'fill_price': 0, 'escalations': escalations}
