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

import math

def sanitize(data):
    """Recursively replace NaN with None for JSON compliance."""
    if isinstance(data, dict):
        return {k: sanitize(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [sanitize(v) for v in data]
    elif isinstance(data, float) and math.isnan(data):
        return None
    return data

ib = IB()
_ib_loop: Optional[asyncio.AbstractEventLoop] = None
escalation_monitor: Dict[str, dict] = {}

# יצירת לולאה יציבה שרצה ברקע ולא תוקעת את השרת
def _run_ib_loop():
    global _ib_loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _ib_loop = loop
    loop.run_forever()

ib_thread = threading.Thread(target=_run_ib_loop, daemon=True)
ib_thread.start()

def run_in_ib(coro, timeout=30):
    if _ib_loop is None:
        raise RuntimeError("IB loop is not running")
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

# --- נתיבי שליטה (חיבור וניתוק יזום) ---
@app.post("/connect")
async def connect_ibkr():
    async def _connect():
        if not ib.isConnected():
            await ib.connectAsync('127.0.0.1', 4002, clientId=99)
        return True
    try:
        run_in_ib(_connect(), timeout=15)
        return {"status": "Connected successfully"}
    except Exception as e:
        return {"status": f"Error: {e}"}

@app.post("/disconnect")
async def disconnect_ibkr():
    if ib.isConnected():
        ib.disconnect()
    return {"status": "Disconnected"}

@app.get("/status")
async def get_status():
    return {"connected": ib.isConnected(), "port": ib.client.port if ib.isConnected() else None, "clientId": ib.client.clientId if ib.isConnected() else None}

# --- נתיבי מידע ופעולות ---
@app.post("/qualify")
async def qualify_contract(leg: Leg):
    if not ib.isConnected(): return {"ok": False, "error": "Not connected"}
    async def _qualify():
        c = Option(leg.symbol, leg.expiry, leg.strike, leg.right, 'SMART') if leg.secType == 'OPT' else Stock(leg.symbol, 'SMART', 'USD')
        q = await ib.qualifyContractsAsync(c)
        if q: return {"ok": True, "con_id": q[0].conId, "localSymbol": q[0].localSymbol}
        return {"ok": False, "error": "Contract not found"}
    try: return run_in_ib(_qualify())
    except Exception as e: return {"ok": False, "error": str(e)}

@app.get("/portfolio")
async def get_portfolio():
    if not ib.isConnected(): return []
    return sanitize([{"symbol": p.contract.symbol, "qty": p.position, "avg_cost": getattr(p, "averageCost", 0.0), "marketPrice": p.marketPrice, "unrealizedPNL": p.unrealizedPNL} for p in ib.portfolio()])

@app.get("/account")
async def get_account():
    if not ib.isConnected(): return {"error": "Not connected"}
    async def _get_acc():
        summary = await ib.reqAccountSummaryAsync()
        acc_data = {}
        for item in summary:
            if item.tag in ['NetLiquidation', 'AvailableFunds', 'TotalCashValue', 'BuyingPower']:
                acc_data[item.tag] = float(item.value)
        return acc_data
    try: return sanitize(run_in_ib(_get_acc()))
    except Exception as e: return {"error": str(e)}

@app.post("/ticker")
async def get_ticker_data(leg: Leg):
    if not ib.isConnected(): return {"error": "Not connected"}
    async def _get_ticker():
        if leg.con_id: contract = Contract(conId=leg.con_id, exchange='SMART')
        elif leg.secType == 'OPT': contract = Option(leg.symbol, leg.expiry, leg.strike, leg.right, 'SMART')
        else: contract = Stock(leg.symbol, 'SMART', 'USD')
            
        contracts = await ib.qualifyContractsAsync(contract)
        if not contracts: return {"error": "Contract not found"}
        
        ib.reqMarketDataType(3) # 3 = Delayed data
        tickers = await ib.reqTickersAsync(contracts[0])
        if not tickers: return {"error": "No ticker data"}
        
        # Wait a bit for data to stream in
        await asyncio.sleep(1)
        t = tickers[0]
        greeks = t.modelGreeks
        # Try multiple sources for IV
        opt_iv = getattr(t, 'impliedVolatility', None)
        if opt_iv is None and greeks: opt_iv = greeks.impliedVol
        
        # Underlying metrics (for options)
        extra = {}
        if contracts[0].secType == 'OPT':
            underlying = Stock(contracts[0].symbol, 'SMART', 'USD')
            u_contracts = await ib.qualifyContractsAsync(underlying)
            if u_contracts:
                # Request index IV (106) and Hist Vol (104)
                u_ticker = ib.reqMktData(u_contracts[0], "104,106", False, False)
                await asyncio.sleep(1)
                extra["avg_iv"] = getattr(u_ticker, 'impliedVolatility', None)
                extra["hist_vol"] = getattr(u_ticker, 'historicalVolatility', None)
                ib.cancelMktData(u_ticker)
                
                # Fetch 1-year historical IV for IV Rank
                bars = await ib.reqHistoricalDataAsync(
                    u_contracts[0], endDateTime='', durationStr='1 Y',
                    barSizeSetting='1 day', whatToShow='OPTION_IMPLIED_VOLATILITY', useRTH=True
                )
                if bars:
                    ivs = [b.close for b in bars if b.close > 0]
                    if ivs:
                        low, high = min(ivs), max(ivs)
                        curr = extra["avg_iv"] or ivs[-1]
                        extra["iv_rank"] = (curr - low) / (high - low) if high > low else 0
                        extra["iv_low"] = low
                        extra["iv_high"] = high

        return {
            "symbol": contracts[0].localSymbol, "con_id": contracts[0].conId,
            "price": t.marketPrice(), "bid": t.bid, "ask": t.ask, "iv": opt_iv,
            "delta": greeks.delta if greeks else None, "gamma": greeks.gamma if greeks else None,
            "theta": greeks.theta if greeks else None, "vega": greeks.vega if greeks else None,
            **extra
        }
    try: return sanitize(run_in_ib(_get_ticker()))
    except Exception as e: return {"error": str(e)}

@app.post("/cancel_all")
async def cancel_all():
    if not ib.isConnected(): return {"status": "Not connected"}
    _ib_loop.call_soon_threadsafe(ib.reqGlobalCancel)
    for oid, info in escalation_monitor.items():
        if "פעיל" in info["internal_status"] or "מתחיל" in info["internal_status"]:
            info["internal_status"] = "בוטל חירום 🛑"
    return {"status": "כל הפקודות הפתוחות בוטלו"}

async def run_managed_order_logic(order_id: str, req: OrderRequest):
    if not ib.isConnected():
        escalation_monitor[order_id] = {"internal_status": "שגיאה: אין חיבור", "ib_status": "N/A", "steps": ["נכשל"], "errors": []}
        return
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
    uvicorn.run(app, host="0.0.0.0", port=8001)
