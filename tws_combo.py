"""
tws_combo.py - Module for executing complex BAG (Combo) orders with escalation.
"""
import time
import logging
from typing import Optional, Dict, Callable
from ib_insync import IB, Option, Bag, ComboLeg, LimitOrder, Trade

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def _log(msg: str):
    logger.info(msg)

def _log_execution(ticker, sell_strike, sell_expiry, sell_conid,
                   buy_strike, buy_expiry, buy_conid, qty,
                   limit_price, fill_price, dte_before, dte_after,
                   spread_width, escalations, elapsed, order_type, status):
    import sqlite3
    try:
        conn = sqlite3.connect('combo_trades.db')
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS combo_rolls
                     (timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                      ticker TEXT, sell_strike REAL, sell_expiry TEXT, sell_conid INTEGER,
                      buy_strike REAL, buy_expiry TEXT, buy_conid INTEGER, qty INTEGER,
                      limit_price REAL, fill_price REAL, dte_before INTEGER, dte_after INTEGER,
                      spread_width REAL, escalations INTEGER, elapsed_sec INTEGER,
                      order_type TEXT, status TEXT)''')
        c.execute('''INSERT INTO combo_rolls 
                     (ticker, sell_strike, sell_expiry, sell_conid,
                      buy_strike, buy_expiry, buy_conid, qty,
                      limit_price, fill_price, dte_before, dte_after,
                      spread_width, escalations, elapsed_sec, order_type, status)
                     VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                  (ticker, sell_strike, sell_expiry, sell_conid,
                   buy_strike, buy_expiry, buy_conid, qty,
                   limit_price, fill_price, dte_before, dte_after,
                   spread_width, escalations, elapsed, order_type, status))
        conn.commit()
        conn.close()
    except Exception as e:
        _log(f"Error logging to DB: {e}")

def execute_combo_roll(ib: IB, 
                       sell_conid: int, sell_strike: float, sell_expiry: str,
                       buy_conid: int, buy_strike: float, buy_expiry: str,
                       ticker: str, qty: int, limit_price: float,
                       use_market: bool = False,
                       escalation_step_pct: float = 1.0,
                       escalation_wait_secs: int = 60,
                       max_escalations: int = 10,
                       log_cb: Optional[Callable[[str, str], None]] = None) -> Dict:
    """
    Executes a BAG order: SELL old LEAPS, BUY new LEAPS.
    Updates the price every escalation_wait_secs by escalation_step_pct.
    """
    _log(f"[COMBO] Starting roll for {ticker} qty={qty}")
    
    # 1. Setup contracts
    # (Note: we assume conIds are qualified and correct)
    
    # 2. Create Bag
    bag = Bag(symbol=ticker, currency='USD', exchange='SMART', 
              comboLegs=[
                  ComboLeg(conId=sell_conid, ratio=1, action='SELL', exchange='SMART'),
                  ComboLeg(conId=buy_conid,  ratio=1, action='BUY',  exchange='SMART')
              ])

    # 3. Initial Order
    order_type = 'MKT' if use_market else 'LMT'
    initial_limit = round(limit_price, 2)
    current_price = initial_limit
    
    if use_market:
        from ib_insync import MarketOrder
        order = MarketOrder('BUY', qty)
    else:
        order = LimitOrder('BUY', qty, initial_limit)

    # DTE calculations for logging
    from datetime import datetime
    def _get_dte(exp_str):
        try:
            exp = datetime.strptime(str(exp_str).replace("-",""), "%Y%m%d").date()
            return (exp - datetime.now().date()).days
        except: return 0
    
    dte_before = _get_dte(sell_expiry)
    dte_after  = _get_dte(buy_expiry)

    # 4. Place Order
    # Force sync next valid order ID to prevent Error 103 (Duplicate ID)
    ib.client.reqIds(-1)
    
    trade = ib.placeOrder(bag, order)
    _log(f"[COMBO] Order placed: {order_type} qty={qty} price=${current_price:.2f}")
    
    # Check for immediate rejection
    ib.sleep(0.5)
    status = trade.orderStatus.status
    if status in ('Cancelled', 'Inactive', 'ApiCancelled'):
        _log(f"[COMBO] Rejected/Cancelled immediately: {status}")
        if log_cb: log_cb("ERROR", f"Rejected: {status}")
        _log_execution(ticker, sell_strike, sell_expiry, sell_conid,
                       buy_strike, buy_expiry, buy_conid, qty,
                       initial_limit, 0, dte_before, dte_after, 0, 0,
                       int(time.time()-start_time), order_type, status)
        return {'status': status, 'fill_price': 0, 'escalations': 0}

    if log_cb: log_cb("INFO", f"Order placed: {order_type} @ ${current_price:.2f}")

    start_time = time.time()
    escalations = 0

    while True:
        ib.sleep(1)
        status = trade.orderStatus.status
        filled = trade.orderStatus.filled
        avg_fill = trade.orderStatus.avgFillPrice
        
        if log_cb:
            # Report status back to caller (API/OrderManager)
            log_cb("DEBUG", f"STATUS_UPDATE:{status}:{avg_fill}")

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

        # Market Closure Awareness
        from datetime import datetime
        try: from zoneinfo import ZoneInfo
        except: from backports.zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("America/New_York"))
        is_open = now.weekday() < 5 and (9*60+30 <= now.hour*60+now.minute < 16*60)
        
        if not is_open:
            if escalations == 0: # Only log once
                _log("[COMBO] Market Closed - Pausing Escalation")
            continue

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
            if log_cb: log_cb("INFO", f"Escalation #{escalations}: ${current_price:.2f}")

        # Safety: stop after 10 minutes
        if time.time() - start_time > 600:
            _log("[COMBO] Safety timeout (10m) reached. Cancelling.")
            ib.cancelOrder(trade.order)
            break

    return {'status': 'TIMEOUT', 'fill_price': 0, 'escalations': escalations}
