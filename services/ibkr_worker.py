import asyncio
import logging
import threading
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import ib_insync as ibi

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Global IB Setup ────────────────────────────────────────────────────────
ib = ibi.IB()
_ib_loop = None

def _run_ib_thread():
    """Background thread running its own dedicated asyncio event loop for IB."""
    global _ib_loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _ib_loop = loop
    
    # Auto-connect synchronously in this thread
    logger.info("IB Worker Thread started. Connecting to IBKR...")
    try:
        # Try DEMO first, then LIVE
        for port in [4002, 7497, 4001, 7496]:
            try:
                loop.run_until_complete(ib.connectAsync('127.0.0.1', port, clientId=10, timeout=4))
                logger.info(f"Connected to IBKR on port {port}")
                break
            except Exception:
                pass
    except Exception as e:
        logger.error(f"IB Worker failed to connect: {e}")
        
    # Keep the loop alive forever to process websocket messages and incoming coroutines
    loop.run_forever()

# Start the dedicated IB thread
_th = threading.Thread(target=_run_ib_thread, daemon=True, name="ibkr_loop_thread")
_th.start()


def run_ib(coro, timeout=25):
    """Safely dispatches an ib_insync coroutine to the background IB event loop."""
    if _ib_loop is None:
        raise RuntimeError("IB event loop is not running")
    future = asyncio.run_coroutine_threadsafe(coro, _ib_loop)
    return future.result(timeout=timeout)


app = FastAPI(title="IBKR Worker Service")


# ── Pydantic Models ─────────────────────────────────────────────────────────

class ComboLeg(BaseModel):
    strike: float
    expiry: str
    right: str
    action: str  # BUY or SELL
    qty: int = 1
    conId: Optional[int] = None

class PlaceComboRequest(BaseModel):
    ticker: str
    legs: List[ComboLeg]
    limit_price: float
    use_market: bool = False
    escalation_step_pct: float = 1.0
    escalation_wait_secs: int = 180
    scheduled_time: Optional[str] = None

class QualifyComboRequest(BaseModel):
    ticker: str
    legs: List[ComboLeg]

class PlaceOrderRequest(BaseModel):
    ticker: str
    strike: float
    expiry: str
    right: str = "C"
    action: str = "BUY"
    qty: int = 1
    limit_price: Optional[float] = None


# ── Endpoints ───────────────────────────────────────────────────────────────

@app.get("/health")
async def health_check():
    return {"status": "ok", "ibkr_connected": ib.isConnected()}


@app.post("/api/ibkr/connect")
async def connect_ibkr(mode: str = "DEMO"):
    """Force connection to IBKR Gateway. Dispatches to the IB thread."""
    if ib.isConnected():
        run_ib(ib.disconnectAsync() if hasattr(ib, 'disconnectAsync') else asyncio.sleep(0))
        if hasattr(ib, 'disconnect'): ib.disconnect()
        await asyncio.sleep(1)
        
    ports = [4002, 7497] if mode.upper() == "DEMO" else [4001, 7496]
    
    for port in ports:
        try:
            logger.info(f"Trying to connect to port {port}...")
            # Run the connection directly in the IB loop
            run_ib(ib.connectAsync('127.0.0.1', port, clientId=10, timeout=4))
            return {"ok": True, "mode": mode, "port": port}
        except Exception as e:
            logger.warning(f"Failed on port {port}: {e}")
            
    raise HTTPException(status_code=503, detail="Could not connect to IBKR Gateway")


@app.get("/api/ibkr/positions")
async def get_positions():
    if not ib.isConnected():
        raise HTTPException(status_code=503, detail="IBKR not connected")
    
    # We can read positions directly if cached, but safer to run in IB loop
    async def _get_pos():
        pos = await ib.reqPositionsAsync()
        acc = await ib.accountSummaryAsync()
        return pos, acc
        
    positions, acc_summary = await asyncio.get_running_loop().run_in_executor(None, lambda: run_ib(_get_pos()))
    
    cash = 0.0
    net_liq = 0.0
    for item in acc_summary:
        if item.tag == "AvailableFunds": cash = float(item.value)
        elif item.tag == "NetLiquidation": net_liq = float(item.value)
            
    pos_list = [{"ticker": p.contract.symbol, "secType": p.contract.secType, "position": p.position, "avgCost": p.avgCost} for p in positions]
        
    return {"ok": True, "cash": cash, "net_liq": net_liq, "positions": pos_list}


@app.post("/api/ibkr/qualify_combo")
async def qualify_combo(req: QualifyComboRequest):
    if not ib.isConnected():
        raise HTTPException(status_code=503, detail="IBKR not connected")
        
    try:
        import math
        ib_options = []
        for l in req.legs:
            expiry = str(l.expiry).replace("-", "")
            ib_options.append(ibi.Option(req.ticker, expiry, l.strike, l.right, "SMART", currency="USD"))
            
        async def _qualify_all():
            await ib.qualifyContractsAsync(*ib_options)
            results = []
            for i, opt in enumerate(ib_options):
                if not opt.conId:
                    raise Exception(f"Leg {i} not qualified by IBKR")
                ib.reqMarketDataType(2)
                [t_data] = await ib.reqTickersAsync(opt)
                
                def _safe_float(v):
                    try:
                        f = float(v)
                        return 0.0 if math.isnan(f) else f
                    except:
                        return 0.0
                        
                bid = _safe_float(t_data.bid)
                ask = _safe_float(t_data.ask)
                last = _safe_float(getattr(t_data, 'last', 0) or getattr(t_data, 'close', 0))
                mid = round((bid + ask) / 2, 2) if bid > 0 and ask > 0 else last
                
                results.append({"strike": req.legs[i].strike, "right": req.legs[i].right, "conId": opt.conId, "mid": mid})
            return results

        # Dispatch the complex qualification logic to the IB loop
        loop = asyncio.get_running_loop()
        legs_data = await loop.run_in_executor(None, lambda: run_ib(_qualify_all(), timeout=30))
        return {"ok": True, "legs": legs_data}
        
    except Exception as e:
        logger.error(f"Qualify error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/order/combo")
async def order_combo(req: PlaceComboRequest):
    if not ib.isConnected():
        raise HTTPException(status_code=503, detail="IBKR not connected")
        
    async def _place():
        combo_legs = []
        for l in req.legs:
            if not l.conId:
                raise ValueError(f"Missing conId for leg {l.strike} {l.right}")
            combo_legs.append(ibi.ComboLeg(conId=l.conId, ratio=l.qty, action=l.action, exchange='SMART'))
        bag = ibi.Bag(symbol=req.ticker, currency='USD', exchange='SMART', comboLegs=combo_legs)
        if req.use_market:
            order = ibi.MarketOrder('BUY', 1)
        else:
            order = ibi.LimitOrder('BUY', 1, req.limit_price)
            
        if req.scheduled_time:
            from datetime import datetime
            try: from zoneinfo import ZoneInfo
            except: from backports.zoneinfo import ZoneInfo
            now_ny = datetime.now(ZoneInfo("America/New_York"))
            hr, mn = map(int, req.scheduled_time.split(':'))
            sched_dt = now_ny.replace(hour=hr, minute=mn, second=0, microsecond=0)
            if sched_dt > now_ny:
                # Format: 20260427 15:50:00 EST
                order.conditionsIgnoreRth = True
                order.goodAfterTime = sched_dt.strftime('%Y%m%d %H:%M:%S EST')
            
        trade = ib.placeOrder(bag, order)
        return trade.order.orderId

    loop = asyncio.get_running_loop()
    try:
        oid = await loop.run_in_executor(None, lambda: run_ib(_place()))
        return {"ok": True, "result": {"order_id": oid}}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.post("/api/ibkr/place_order")
async def place_order(req: PlaceOrderRequest):
    return {"ok": True, "message": "Endpoint stub. Ready for implementation."}

@app.get("/api/orders/active")
async def get_active_orders():
    if not ib.isConnected():
        return {"ok": False, "error": "Not connected"}
    async def _fetch():
        return ib.openOrders()
    try:
        loop = asyncio.get_running_loop()
        orders = await loop.run_in_executor(None, lambda: run_ib(_fetch()))
        return {"ok": True, "orders": [{"orderId": o.orderId, "action": o.action, "totalQuantity": o.totalQuantity, "lmtPrice": getattr(o, 'lmtPrice', 0)} for o in orders]}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.get("/api/ibkr/get_iv/{ticker}")
async def get_iv(ticker: str):
    return {"ok": True, "message": "Endpoint stub. Ready for implementation."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
