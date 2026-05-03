import asyncio
import logging
import uuid
from fastapi import FastAPI, BackgroundTasks, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Dict
from ib_insync import *

app = FastAPI(title="IBKR Standalone Execution Worker")
ib = IB()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

escalation_monitor: Dict[str, dict] = {}

class Leg(BaseModel):
    symbol: str
    secType: str  # 'OPT' or 'STK'
    action: str   # 'BUY' or 'SELL'
    ratio: int
    con_id: Optional[int] = 0       # הוספנו אפשרות להזנת ConID ידנית
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

async def ensure_connection():
    if ib.isConnected():
        return
    
    # Priority for Gateway (4002/4001) then TWS (7497/7496)
    target_ports = [4002, 7497, 4001, 7496]
    
    msg = "Starting connection sequence..."
    logger.info(msg)
    connection_logs.append(msg)
    
    for port in target_ports:
        # Try a few random client IDs to avoid "clientId already in use"
        for _ in range(2):
            cid = random.randint(10, 999)
            try:
                msg = f"Trying 127.0.0.1:{port} with clientId={cid}"
                logger.info(msg)
                connection_logs.append(msg)
                
                # Force clean slate
                if ib.client.isConnected():
                    ib.disconnect()
                
                await ib.connectAsync('127.0.0.1', port, clientId=cid, timeout=4)
                
                if ib.isConnected():
                    msg = f"✅ Connected successfully to port {port} (clientId={cid})"
                    logger.info(msg)
                    connection_logs.append(msg)
                    return
            except Exception as e:
                msg = f"❌ Port {port}/CID {cid} failed: {e}"
                logger.warning(msg)
                connection_logs.append(msg)
                await asyncio.sleep(0.5)
                continue
    
    msg = "FAILED: All connection attempts exhausted."
    logger.error(msg)
    connection_logs.append(msg)

# --- מנוע חילוץ ConID ---
@app.post("/qualify")
async def qualify_contract(leg: Leg):
    await ensure_connection()
    c = Option(leg.symbol, leg.expiry, leg.strike, leg.right, 'SMART') if leg.secType == 'OPT' else Stock(leg.symbol, 'SMART', 'USD')
    try:
        q = await ib.qualifyContractsAsync(c)
        if q:
            return {"ok": True, "con_id": q[0].conId, "localSymbol": q[0].localSymbol}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return {"ok": False, "error": "Contract not found"}

# --- מנוע הסלמה מתקדם עם ניטור IBKR אמיתי ---
async def run_managed_order(order_id: str, req: OrderRequest):
    await ensure_connection()
    current_price = req.lmt_price
    
    # בניית חוזה (תמיכה מלאה ב-ConID)
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

        escalation_monitor[order_id] = {"internal_status": "מתחיל", "ib_status": "N/A", "steps": [], "errors": []}

        for step in range(req.max_steps):
            msg = f"שלב {step+1}: שיגור במחיר {current_price:.2f}"
            escalation_monitor[order_id]["steps"].append(msg)
            
            order = LimitOrder(req.action, req.total_qty, round(current_price, 2))
            trade = ib.placeOrder(contract, order)
            
            # לולאת המתנה שדוגמת את הסטטוס מ-IBKR בכל שנייה
            for _ in range(req.esc_interval):
                await asyncio.sleep(1)
                escalation_monitor[order_id]["ib_status"] = trade.orderStatus.status
                
                # בדיקת שגיאות מהלוג של אינטראקטיב (חשוב לבדיקות סופ"ש)
                for log in trade.log:
                    if log.status in ['Cancelled', 'Inactive'] or log.errorCode:
                        err_msg = f"IB Error {log.errorCode}: {log.message}"
                        if err_msg not in escalation_monitor[order_id]["errors"]:
                            escalation_monitor[order_id]["errors"].append(err_msg)

                if trade.isDone():
                    escalation_monitor[order_id]["internal_status"] = "בוצע בהצלחה ✅"
                    return

            # אם לא נתפס, מבטלים ומשפרים מחיר
            ib.cancelOrder(order)
            await asyncio.sleep(1)
            
            adj = abs(current_price) * req.esc_pct
            current_price = (current_price + adj) if req.action == 'BUY' else (current_price - adj)

        escalation_monitor[order_id]["internal_status"] = "ההסלמה הסתיימה ללא ביצוע ❌"
    except Exception as e:
        logger.error(f"Order error {order_id}: {e}")
        escalation_monitor[order_id] = {"internal_status": f"שגיאה: {str(e)} ❌", "steps": [], "errors": [str(e)]}

# --- Endpoints רגילים ---
@app.get("/status")
async def get_status():
    await ensure_connection()
    return {
        "connected": ib.isConnected(),
        "port": ib.client.port if ib.isConnected() else None,
        "clientId": ib.client.clientId if ib.isConnected() else None
    }

@app.get("/portfolio")
async def get_portfolio():
    await ensure_connection()
    return [{"symbol": p.contract.symbol, "qty": p.position, "marketPrice": p.marketPrice, "unrealizedPNL": p.unrealizedPNL} for p in ib.portfolio()]

@app.get("/ticker/{symbol}")
async def get_ticker_data(symbol: str):
    await ensure_connection()
    try:
        contracts = await ib.qualifyContractsAsync(Stock(symbol, 'SMART', 'USD'))
        if not contracts:
            return {"error": "Symbol not found or could not be qualified"}
        tickers = ib.reqTickers(contracts[0])
        if not tickers:
            return {"error": "No ticker data available"}
        t = tickers[0]
        return {"price": t.marketPrice(), "bid": t.bid, "ask": t.ask, "iv": t.impliedVol}
    except Exception as e:
        logger.error(f"Ticker data error for {symbol}: {e}")
        return {"error": str(e)}

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
