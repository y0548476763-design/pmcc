import asyncio
import logging
import uuid
import threading
from fastapi import FastAPI, BackgroundTasks
from pydantic import BaseModel
from typing import List, Optional, Dict
from ib_insync import *

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

import math # Add math import

# --- Global State Placeholder ---
ib = None 
_ib_loop: Optional[asyncio.AbstractEventLoop] = None
escalation_monitor: Dict[str, dict] = {}

def sanitize(data):
    """Recursively replace NaN with None for JSON compliance."""
    if isinstance(data, dict):
        return {k: sanitize(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [sanitize(v) for v in data]
    elif isinstance(data, float) and math.isnan(data):
        return None
    return data

def _run_ib_loop():
    global _ib_loop, ib
    # Create the loop specifically for this thread
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _ib_loop = loop
    
    # Initialize IB instance INSIDE the thread loop
    ib = IB()
    
    async def connect_and_maintain():
        while True:
            if not ib.isConnected():
                try:
                    logger.info("Attempting to connect to IB Gateway (Port 4002)...")
                    await ib.connectAsync('127.0.0.1', 4002, clientId=99)
                    ib.reqMarketDataType(3) # Enable delayed data as fallback
                    logger.info("✅ Successfully connected to IB Gateway (Delayed Data Enabled)!")
                except Exception as e:
                    logger.error(f"Connection failed: {e}. Retrying in 10s...")
                    await asyncio.sleep(10)
            else:
                await asyncio.sleep(5)
    
    loop.create_task(connect_and_maintain())
    loop.run_forever()

# Start the IB thread
ib_thread = threading.Thread(target=_run_ib_loop, daemon=True)
ib_thread.start()

def run_in_ib(coro, timeout=30):
    if _ib_loop is None or ib is None:
        raise RuntimeError("IB loop is not running yet")
    future = asyncio.run_coroutine_threadsafe(coro, _ib_loop)
    return future.result(timeout=timeout)

app = FastAPI(title="IBKR Standalone Execution Worker")

class Leg(BaseModel):
    symbol: str
    secType: str  
    action: str   
    ratio: int
    con_id: Optional[int] = 0       
    strike: Optional[float] = None
    expiry: Optional[str] = None
    right: Optional[str] = None

class OrderRequest(BaseModel):
    action: str 
    order_type: str = "LMT"
    total_qty: int
    lmt_price: float = 0.0
    legs: List[Leg]
    esc_pct: float = 0.01
    esc_interval: int = 30
    max_steps: int = 5

@app.get("/status")
async def get_status():
    if ib is None: return {"connected": False, "error": "Initializing..."}
    return {"connected": ib.isConnected(), "port": ib.client.port if ib.isConnected() else None, "clientId": ib.client.clientId if ib.isConnected() else None}

@app.post("/qualify")
async def qualify_contract(leg: Leg):
    if ib is None or not ib.isConnected(): return {"ok": False, "error": "Not connected"}
    async def _qualify():
        c = Option(leg.symbol, leg.expiry, leg.strike, leg.right, 'SMART') if leg.secType == 'OPT' else Stock(leg.symbol, 'SMART', 'USD')
        q = await ib.qualifyContractsAsync(c)
        if q: return {"ok": True, "con_id": q[0].conId, "localSymbol": q[0].localSymbol}
        return {"ok": False, "error": "Contract not found"}
    try: return run_in_ib(_qualify())
    except Exception as e: return {"ok": False, "error": str(e)}

@app.get("/portfolio")
async def get_portfolio():
    if ib is None or not ib.isConnected(): return []
    return sanitize([{"symbol": p.contract.symbol, "qty": p.position, "avg_cost": getattr(p, "averageCost", 0.0), "marketPrice": p.marketPrice, "unrealizedPNL": p.unrealizedPNL} for p in ib.portfolio()])

@app.get("/account")
async def get_account():
    """משיכת נתוני מזומן קריטיים לרצפת ההישרדות"""
    if ib is None or not ib.isConnected(): return {"error": "Not connected"}
    async def _get_acc():
        # accountValues is much more reliable for single accounts
        vals = ib.accountValues()
        acc_data = {}
        for v in vals:
            if v.currency == 'USD' or v.currency == '':
                if v.tag in ['NetLiquidation', 'NetLiquidationByCurrency']:
                    acc_data['NetLiquidation'] = float(v.value.replace(',', ''))
                if v.tag in ['AvailableFunds', 'AvailableFunds-C']:
                    acc_data['AvailableFunds'] = float(v.value.replace(',', ''))
                if v.tag in ['TotalCashValue', 'TotalCashBalance']:
                    acc_data['TotalCashValue'] = float(v.value.replace(',', ''))
                if v.tag == 'BuyingPower':
                    acc_data['BuyingPower'] = float(v.value.replace(',', ''))
        
        # If still empty, try summary as fallback
        if not acc_data:
            summary = await ib.reqAccountSummaryAsync()
            for item in summary:
                if item.tag in ['NetLiquidation', 'AvailableFunds', 'TotalCashValue', 'BuyingPower']:
                    acc_data[item.tag] = float(item.value)
        
        return acc_data
    try: return sanitize(run_in_ib(_get_acc()))
    except Exception as e: return {"error": str(e)}

@app.get("/ticker/{symbol}")
async def get_ticker_data(symbol: str, expiry: Optional[str] = None, strike: Optional[float] = None, right: Optional[str] = None):
    if ib is None or not ib.isConnected(): return {"error": "Not connected"}
    async def _get_ticker():
        if expiry and strike and right and right != "None":
            contract = Option(symbol, expiry, strike, right, 'SMART', currency='USD', multiplier='100')
        else:
            contract = Stock(symbol, 'SMART', 'USD')
            
        contracts = await ib.qualifyContractsAsync(contract)
        if not contracts: return {"error": f"Contract not found for {symbol} {expiry or ''}"}
        
        tickers = await ib.reqTickersAsync(contracts[0])
        if not tickers: return {"error": "No ticker data"}
        
        # Wait a bit for data to stream in
        await asyncio.sleep(2)
        t = tickers[0]
        
        # Advanced Data Extraction
        g = t.modelGreeks or t.lastGreeks
        
        # Priority for Price: ModelPrice (for options) -> Last -> Close -> MarketPrice
        price = t.marketPrice()
        if isinstance(contract, Option) and g and g.optPrice:
            price = g.optPrice
        
        data = {
            "symbol": symbol,
            "price": price,
            "bid": t.bid if t.bid > 0 else None,
            "ask": t.ask if t.ask > 0 else None,
            "iv": getattr(t, 'impliedVolatility', None) or (g.undPrice if g else None) # fallback or logic
        }
        
        # IV specific logic
        if isinstance(contract, Option):
            data["iv"] = getattr(t, 'impliedVolatility', None) or (g.impliedVol if g else None)

        if g or isinstance(contract, Option):
            data.update({
                "delta": getattr(g, 'delta', None) if g else None,
                "gamma": getattr(g, 'gamma', None) if g else None,
                "theta": getattr(g, 'theta', None) if g else None,
                "vega": getattr(g, 'vega', None) if g else None,
                "modelPrice": getattr(g, 'optPrice', None) if g else None,
                "pvDividend": getattr(g, 'pvDividend', None) if g else None
            })
            
        return data
    try: return sanitize(run_in_ib(_get_ticker()))
    except Exception as e: return {"error": str(e)}

@app.post("/cancel_all")
async def cancel_all():
    if ib is None or not ib.isConnected(): return {"status": "Not connected"}
    _ib_loop.call_soon_threadsafe(ib.reqGlobalCancel)
    for oid, info in escalation_monitor.items():
        if "פעיל" in info["internal_status"] or "מתחיל" in info["internal_status"]:
            info["internal_status"] = "בוטל חירום 🛑"
    return {"status": "כל הפקודות הפתוחות בוטלו"}

async def run_managed_order_logic(order_id: str, req: OrderRequest):
    current_price = req.lmt_price
    escalation_monitor[order_id] = {"internal_status": "מתחיל...", "ib_status": "N/A", "steps": [], "errors": [], "final_fill": None}
    
    try:
        if len(req.legs) == 1:
            l = req.legs[0]
            contract = Contract(conId=l.con_id, exchange='SMART') if l.con_id else (Option(l.symbol, l.expiry, l.strike, l.right, 'SMART') if l.secType == 'OPT' else Stock(l.symbol, 'SMART', 'USD'))
        else:
            contract = Contract(secType='BAG', symbol=req.legs[0].symbol, currency='USD', exchange='SMART')
            legs_list = []
            for l in req.legs:
                con_id = l.con_id if l.con_id else (await ib.qualifyContractsAsync(Option(l.symbol, l.expiry, l.strike, l.right, 'SMART') if l.secType == 'OPT' else Stock(l.symbol, 'SMART')))[0].conId
                legs_list.append(ComboLeg(conId=con_id, ratio=l.ratio, action=l.action, exchange='SMART'))
            contract.comboLegs = legs_list

        if req.order_type == "MKT":
            escalation_monitor[order_id]["internal_status"] = "שוגר כמרקט (MKT)"
            order = MarketOrder(req.action, req.total_qty)
            trade = ib.placeOrder(contract, order)
            for _ in range(15):
                await asyncio.sleep(1)
                escalation_monitor[order_id]["ib_status"] = trade.orderStatus.status
                if trade.isDone():
                    escalation_monitor[order_id]["internal_status"] = "בוצע בהצלחה ✅"
                    escalation_monitor[order_id]["final_fill"] = trade.orderStatus.avgFillPrice
                    return
            return

        escalation_monitor[order_id]["internal_status"] = "לולאת הסלמה פעילה"
        for step in range(req.max_steps):
            if "בוטל" in escalation_monitor[order_id]["internal_status"]: return
            
            escalation_monitor[order_id]["steps"].append(f"שלב {step+1}: שיגור ב-{current_price:.2f}")
            order = LimitOrder(req.action, req.total_qty, round(current_price, 2))
            trade = ib.placeOrder(contract, order)
            
            for _ in range(req.esc_interval):
                await asyncio.sleep(1)
                escalation_monitor[order_id]["ib_status"] = trade.orderStatus.status
                for log in trade.log:
                    if log.status in ['Cancelled', 'Inactive'] or log.errorCode:
                        err = f"IB Error {log.errorCode}: {log.message}"
                        if err not in escalation_monitor[order_id]["errors"]: escalation_monitor[order_id]["errors"].append(err)
                if trade.isDone():
                    escalation_monitor[order_id]["internal_status"] = "בוצע בהצלחה ✅"
                    escalation_monitor[order_id]["final_fill"] = trade.orderStatus.avgFillPrice
                    return

            ib.cancelOrder(order)
            await asyncio.sleep(1)
            adj = abs(current_price) * req.esc_pct
            current_price = (current_price + adj) if req.action == 'BUY' else (current_price - adj)

        escalation_monitor[order_id]["internal_status"] = "ההסלמה הסתיימה ללא ביצוע ❌"
    except Exception as e:
        escalation_monitor[order_id]["internal_status"] = f"שגיאה: {e}"
        escalation_monitor[order_id]["errors"].append(str(e))

@app.post("/submit")
async def submit_order(req: OrderRequest, tasks: BackgroundTasks):
    order_id = str(uuid.uuid4())[:8]
    asyncio.run_coroutine_threadsafe(run_managed_order_logic(order_id, req), _ib_loop)
    return {"order_id": order_id, "message": "הבקשה נשלחה ללולאת הביצוע"}

@app.get("/monitor")
def get_monitor(): return escalation_monitor

if __name__ == "__main__":
    import uvicorn
    # No nest_asyncio here to avoid uvicorn loop_factory conflict
    uvicorn.run(app, host="0.0.0.0", port=8001)
