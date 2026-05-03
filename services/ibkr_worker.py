import asyncio
import logging
import uuid
import threading
import time
from fastapi import FastAPI, BackgroundTasks, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Dict
from ib_insync import *

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Global State ---
ib = IB()
_ib_loop: Optional[asyncio.AbstractEventLoop] = None
escalation_monitor: Dict[str, dict] = {}

def _run_ib_loop():
    """Background thread to run the IBKR event loop."""
    global _ib_loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _ib_loop = loop
    
    async def connect_and_maintain():
        while True:
            if not ib.isConnected():
                try:
                    logger.info("Attempting to connect to IB Gateway (Port 4002)...")
                    await ib.connectAsync('127.0.0.1', 4002, clientId=99)
                    logger.info("✅ Successfully connected to IB Gateway!")
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

# Helper to run coros in the IB thread
def run_in_ib(coro, timeout=30):
    if _ib_loop is None:
        raise RuntimeError("IB loop is not running")
    future = asyncio.run_coroutine_threadsafe(coro, _ib_loop)
    return future.result(timeout=timeout)

app = FastAPI(title="IBKR Standalone Execution Worker")

# --- מודלים ---
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
    total_qty: int
    lmt_price: float
    legs: List[Leg]
    esc_pct: float = 0.01
    esc_interval: int = 30
    max_steps: int = 5

# --- Endpoints ---

@app.get("/status")
async def get_status():
    return {
        "connected": ib.isConnected(),
        "port": ib.client.port if ib.isConnected() else None,
        "clientId": ib.client.clientId if ib.isConnected() else None
    }

@app.post("/qualify")
async def qualify_contract(leg: Leg):
    if not ib.isConnected():
        return {"ok": False, "error": "Not connected to IBKR"}
        
    async def _qualify():
        c = Option(leg.symbol, leg.expiry, leg.strike, leg.right, 'SMART') if leg.secType == 'OPT' else Stock(leg.symbol, 'SMART', 'USD')
        q = await ib.qualifyContractsAsync(c)
        if q:
            return {"ok": True, "con_id": q[0].conId, "localSymbol": q[0].localSymbol}
        return {"ok": False, "error": "Contract not found"}

    try:
        return run_in_ib(_qualify())
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.get("/portfolio")
async def get_portfolio():
    if not ib.isConnected(): return []
    return [{"symbol": p.contract.symbol, "qty": p.position, "marketPrice": p.marketPrice, "unrealizedPNL": p.unrealizedPNL} for p in ib.portfolio()]

@app.get("/ticker/{symbol}")
async def get_ticker_data(symbol: str):
    if not ib.isConnected(): return {"error": "Not connected"}
    
    async def _get_ticker():
        contracts = await ib.qualifyContractsAsync(Stock(symbol, 'SMART', 'USD'))
        if not contracts: return {"error": "Symbol not found"}
        tickers = ib.reqTickers(contracts[0])
        if not tickers: return {"error": "No ticker data"}
        t = tickers[0]
        return {"price": t.marketPrice(), "bid": t.bid, "ask": t.ask, "iv": t.impliedVol}
        
    try:
        return run_in_ib(_get_ticker())
    except Exception as e:
        return {"error": str(e)}

# --- מנוע הסלמה ---
async def run_managed_order_logic(order_id: str, req: OrderRequest):
    # This logic runs in the IB thread to avoid async context issues
    current_price = req.lmt_price
    escalation_monitor[order_id] = {"internal_status": "מתחיל...", "ib_status": "N/A", "steps": [], "errors": []}
    
    try:
        if len(req.legs) == 1:
            l = req.legs[0]
            if l.con_id:
                contract = Contract(conId=l.con_id, exchange='SMART')
            else:
                contract = Option(l.symbol, l.expiry, l.strike, l.right, 'SMART') if l.secType == 'OPT' else Stock(l.symbol, 'SMART', 'USD')
        else:
            contract = Contract(secType='BAG', symbol=req.legs[0].symbol, currency='USD', exchange='SMART')
            legs_list = []
            for l in req.legs:
                if l.con_id:
                    con_id = l.con_id
                else:
                    inner = Option(l.symbol, l.expiry, l.strike, l.right, 'SMART') if l.secType == 'OPT' else Stock(l.symbol, 'SMART')
                    q = await ib.qualifyContractsAsync(inner)
                    con_id = q[0].conId
                legs_list.append(ComboLeg(conId=con_id, ratio=l.ratio, action=l.action, exchange='SMART'))
            contract.comboLegs = legs_list

        for step in range(req.max_steps):
            msg = f"שלב {step+1}: שיגור במחיר {current_price:.2f}"
            escalation_monitor[order_id]["steps"].append(msg)
            
            order = LimitOrder(req.action, req.total_qty, round(current_price, 2))
            trade = ib.placeOrder(contract, order)
            
            for _ in range(req.esc_interval):
                await asyncio.sleep(1)
                escalation_monitor[order_id]["ib_status"] = trade.orderStatus.status
                
                for log in trade.log:
                    if log.status in ['Cancelled', 'Inactive'] or log.errorCode:
                        err_msg = f"IB Error {log.errorCode}: {log.message}"
                        if err_msg not in escalation_monitor[order_id]["errors"]:
                            escalation_monitor[order_id]["errors"].append(err_msg)

                if trade.isDone():
                    escalation_monitor[order_id]["internal_status"] = "בוצע בהצלחה ✅"
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
    # We schedule the task in the IB thread loop
    asyncio.run_coroutine_threadsafe(run_managed_order_logic(order_id, req), _ib_loop)
    return {"order_id": order_id, "message": "הסלמה החלה"}

@app.get("/monitor")
def get_monitor():
    return escalation_monitor

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
