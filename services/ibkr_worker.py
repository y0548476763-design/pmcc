import asyncio
import logging
import uuid
from fastapi import FastAPI, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel
from typing import List, Optional, Dict
from ib_insync import *

# הגדרות שרת ולוגים
app = FastAPI(title="IBKR Standalone Execution Worker")
ib = IB()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# מאגר פנימי לניטור הסלמות בזמן אמת
escalation_monitor: Dict[str, dict] = {}

class Leg(BaseModel):
    symbol: str
    secType: str  # 'OPT' or 'STK'
    action: str   # 'BUY' or 'SELL'
    ratio: int
    strike: Optional[float] = None
    expiry: Optional[str] = None
    right: Optional[str] = None

class OrderRequest(BaseModel):
    action: str # 'BUY' or 'SELL'
    total_qty: int
    lmt_price: float
    legs: List[Leg]
    esc_pct: float = 0.01
    esc_interval: int = 30
    max_steps: int = 5

async def ensure_connection():
    if not ib.isConnected():
        try:
            # We try ports for both Paper (7497) and Live (7496/4001/4002)
            ports = [7497, 4002, 7496, 4001]
            for port in ports:
                try:
                    await ib.connectAsync('127.0.0.1', port, clientId=10)
                    logger.info(f"Connected to IBKR on port {port}")
                    return
                except:
                    continue
        except Exception as e:
            logger.error(f"Connection failed: {e}")

# --- מנוע הסלמה אסינכרוני ---
async def run_managed_order(order_id: str, req: OrderRequest):
    await ensure_connection()
    current_price = req.lmt_price
    
    # 1. בניית החוזה
    try:
        if len(req.legs) == 1:
            l = req.legs[0]
            if l.secType == 'OPT':
                contract = Option(l.symbol, l.expiry, l.strike, l.right, 'SMART')
            else:
                contract = Stock(l.symbol, 'SMART', 'USD')
        else:
            # פקודת קומבו (BAG)
            contract = Contract(secType='BAG', symbol=req.legs[0].symbol, currency='USD', exchange='SMART')
            legs_list = []
            for l in req.legs:
                inner = Option(l.symbol, l.expiry, l.strike, l.right, 'SMART') if l.secType == 'OPT' else Stock(l.symbol, 'SMART')
                qualified = await ib.qualifyContractsAsync(inner)
                legs_list.append(ComboLeg(conId=qualified[0].conId, ratio=l.ratio, action=l.action, exchange='SMART'))
            contract.comboLegs = legs_list

        escalation_monitor[order_id] = {"status": "בביצוע", "steps": [], "final_fill": None}

        # 2. לולאת הסלמה
        for step in range(req.max_steps):
            msg = f"שלב {step+1}: מנסה מחיר {current_price:.2f}"
            escalation_monitor[order_id]["steps"].append(msg)
            
            order = LimitOrder(req.action, req.total_qty, round(current_price, 2))
            trade = ib.placeOrder(contract, order)
            
            await asyncio.sleep(req.esc_interval)
            
            if trade.isDone():
                escalation_monitor[order_id]["status"] = "בוצע בהצלחה ✅"
                escalation_monitor[order_id]["final_fill"] = trade.orderStatus.avgFillPrice
                return

            # ביטול לצורך שיפור מחיר
            ib.cancelOrder(order)
            await asyncio.sleep(1)
            
            # חישוב הסלמה: ב-BUY מעלים מחיר, ב-SELL (קרדיט) מורידים מחיר
            adj = current_price * req.esc_pct
            current_price = (current_price + adj) if req.action == 'BUY' else (current_price - adj)

        escalation_monitor[order_id]["status"] = "נכשל - לא נתפס ❌"
    except Exception as e:
        logger.error(f"Order error {order_id}: {e}")
        escalation_monitor[order_id] = {"status": f"שגיאה: {str(e)} ❌", "steps": []}

# --- Endpoints ---

@app.get("/portfolio")
async def get_portfolio():
    await ensure_connection()
    return [{"symbol": p.contract.symbol, "qty": p.position, "marketPrice": p.marketPrice, "unrealizedPNL": p.unrealizedPNL} for p in ib.portfolio()]

@app.get("/ticker/{symbol}")
async def get_ticker_data(symbol: str):
    await ensure_connection()
    contract = Stock(symbol, 'SMART', 'USD')
    qualified = await ib.qualifyContractsAsync(contract)
    tickers = ib.reqTickers(qualified[0])
    t = tickers[0]
    return {"price": t.marketPrice(), "bid": t.bid, "ask": t.ask, "iv": t.impliedVol}

@app.post("/submit")
async def submit_order(req: OrderRequest, tasks: BackgroundTasks):
    order_id = str(uuid.uuid4())[:8]
    tasks.add_task(run_managed_order, order_id, req)
    return {"order_id": order_id, "message": "הסלמה החלה"}

@app.get("/monitor")
def get_monitor():
    return escalation_monitor

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
