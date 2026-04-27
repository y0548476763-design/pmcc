"""
tws_combo.py - Module for executing complex BAG (Combo) orders with escalation.
"""
import time
import logging
from typing import Optional, Dict, Callable, List
from ib_insync import IB, Bag, ComboLeg, LimitOrder, Trade

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def _log(msg: str):
    logger.info(msg)

def execute_combo_roll(ib: IB, 
                       ticker: str, legs: List[Dict], qty: int, limit_price: float,
                       use_market: bool = False,
                       escalation_step_pct: float = 1.0,
                       escalation_wait_secs: int = 60,
                       max_escalations: int = 10,
                       log_cb: Optional[Callable[[str, str], None]] = None,
                       mo = None) -> Dict:
    """
    Executes a BAG order with dynamic legs.
    legs: List of {"conId": int, "action": str, "ratio": int}
    """
    if mo and getattr(mo, "is_processing", False):
        _log(f"Order is already escalating. Aborting duplicate thread.")
        return {"ok": False, "error": "Already processing"}
    
    if mo: mo.is_processing = True

    _log(f"[COMBO] Starting multi-leg execution for {ticker} qty={qty} legs={len(legs)}")
    
    # 1. Create Bag
    combo_legs = []
    for l in legs:
        combo_legs.append(ComboLeg(conId=l["conId"], ratio=l.get("ratio", 1), action=l["action"], exchange='SMART'))
    
    bag = Bag(symbol=ticker, currency='USD', exchange='SMART', comboLegs=combo_legs)

    # 2. Initial Order
    order_type = 'MKT' if use_market else 'LMT'
    initial_limit = round(limit_price, 2)
    current_price = initial_limit
    
    if use_market:
        from ib_insync import MarketOrder
        order = MarketOrder('BUY', qty)
    else:
        order = LimitOrder('BUY', qty, initial_limit)

    # 3. Place Order
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
            log_cb("DEBUG", f"STATUS_UPDATE:{status}:{avg_fill}")

        if status == 'Filled':
            elapsed = int(time.time() - start_time)
            _log(f"[COMBO] FILLED! qty={filled} avg=${avg_fill:.2f} in {elapsed}s ({escalations} escals)")
            return {'status': 'FILLED', 'fill_price': avg_fill, 'qty': filled,
                    'elapsed_sec': elapsed, 'escalations': escalations, 'order_id': trade.order.orderId}

        if status in ('Cancelled', 'Inactive', 'ApiCancelled'):
            _log(f"[COMBO] Order {status}")
            return {'status': status, 'fill_price': 0, 'escalations': escalations}

        # Market Closure Awareness
        from datetime import datetime
        try: from zoneinfo import ZoneInfo
        except: from backports.zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("America/New_York"))
        is_open = now.weekday() < 5 and (9*60+30 <= now.hour*60+now.minute < 16*60)
        
        if not is_open:
            continue

        # Escalation logic (LMT only)
        if not use_market and max_escalations > 0 and (time.time() - start_time) > escalation_wait_secs * (escalations + 1):
            if escalations >= max_escalations:
                _log(f"[COMBO] Max escalations reached. Cancelling.")
                ib.cancelOrder(trade.order)
                break
            escalations += 1
            # Adjust price based on net debit (BUY order)
            current_price = round(current_price * (1.0 + escalation_step_pct / 100.0), 2)
            trade.order.lmtPrice = current_price
            ib.placeOrder(bag, trade.order)
            _log(f"[COMBO] Escalation #{escalations}: new price=${current_price:.2f}")
            if log_cb: log_cb("INFO", f"Escalation #{escalations}: ${current_price:.2f}")

        # Safety: stop after 30 minutes for earnings orders
        if time.time() - start_time > 1800:
            _log("[COMBO] Safety timeout (30m) reached. Cancelling.")
            ib.cancelOrder(trade.order)
            break

    return {'status': 'TIMEOUT', 'fill_price': 0, 'escalations': escalations}
