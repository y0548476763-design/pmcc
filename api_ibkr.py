"""
api_ibkr.py — IBKR TWS server (port 8002)
Singleton TWS connection shared across all requests.
Endpoints: GET /portfolio, POST /qualify, POST /order/combo
"""
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import logging, threading, asyncio, math
import ib_insync.util
try:
    import nest_asyncio
    nest_asyncio.apply()
except ImportError:
    pass
# ib_insync.util.patchAsyncio()  # Disabled to avoid uvicorn loop_factory conflict on Python 3.13

app = FastAPI(title="PMCC IBKR API", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
logger = logging.getLogger(__name__)

# ── Singleton TWS connection ───────────────────────────────────────────────
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tws_client import TWSClient
import config

_tws: Optional[TWSClient] = None
_lock = threading.Lock()

async def get_tws() -> TWSClient:
    global _tws
    if _tws is None:
        _tws = TWSClient()
    if not _tws.connected:
        cid = 88
        logger.info("Auto-connecting IBKR...")
        # Use standard connectAsync which now works thanks to patching
        if not await _tws.connectAsync("LIVE", port=7496, client_id=cid, timeout=4):
            if not await _tws.connectAsync("DEMO", port=4002, client_id=cid, timeout=4):
                await _tws.connectAsync("DEMO", port=7497, client_id=cid, timeout=4)
    return _tws


def is_market_open():
    """Helper to check if US Market is open (9:30-16:00 ET)."""
    from datetime import datetime
    try: from zoneinfo import ZoneInfo
    except: from backports.zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo("America/New_York"))
    if now.weekday() >= 5: return False
    o = now.replace(hour=9, minute=30, second=0, microsecond=0)
    c = now.replace(hour=16, minute=0, second=0, microsecond=0)
    return o <= now <= c

# ── Models ─────────────────────────────────────────────────────────────────

class QualifyRequest(BaseModel):
    ticker: str
    strike: float
    expiry: str          # YYYYMMDD or YYYY-MM-DD
    right: str = "C"

class ComboRequest(BaseModel):
    ticker: str
    qty: int
    sell_strike: float
    sell_expiry: str
    buy_strike: float
    buy_expiry: str
    limit_price: float = 0.0
    use_market: bool = False
    escalation_step_pct: float = 1.0
    escalation_wait_secs: int = 180

class PlaceOrderRequest(BaseModel):
    ticker: str
    strike: float
    expiry: str
    right: str = "C"
    action: str = "BUY"  # BUY or SELL
    qty: int = 1
    limit_price: Optional[float] = None


# ── Endpoints ──────────────────────────────────────────────────────────────

@app.get("/portfolio")
async def get_portfolio():
    """Returns positions + account balances from TWS."""
    tws = await get_tws()
    if not tws.connected:
        # Return demo positions so dashboard never breaks
        return {
            "ok": True,
            "source": "DEMO",
            "tws_connected": False,
            "account_id": "DEMO",
            "cash": 0.0,
            "net_liq": 0.0,
            "positions": list(config.DEMO_POSITIONS),
        }
    try:
        tws._refresh_account()
        positions = tws.get_positions()
        return {
            "ok": True,
            "source": tws.mode,
            "tws_connected": tws.connected,
            "account_id": tws.account_id,
            "cash": tws.cash_balance,
            "net_liq": tws.net_liquidation,
            "positions": positions,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/qualify")
async def qualify_contract(req: QualifyRequest):
    """Qualify a single option contract and return conId + live/frozen prices."""
    tws = await get_tws()
    if not tws.connected or not tws.ib:
        raise HTTPException(status_code=503, detail="TWS not connected")
    
    try:
        from ib_insync import Option as IBOption
        expiry = str(req.expiry).replace("-", "")
        contract = IBOption(req.ticker, expiry, req.strike, req.right,
                            "SMART", currency="USD")
        
        details = await tws.ib.reqContractDetailsAsync(contract)
        if not details:
            raise HTTPException(status_code=404, detail="Contract not found")
        
        contract = details[0].contract
        tws.ib.reqMarketDataType(2)
        tickers = await tws.ib.reqTickersAsync(contract)
        
        bid = ask = mid = 0.0
        if tickers:
            t = tickers[0]
            # Helper to safely convert to float and handle NaN
            def _safe(v):
                try:
                    f = float(v)
                    return 0.0 if math.isnan(f) else f
                except: return 0.0

            bid = _safe(t.bid or t.last or 0)
            ask = _safe(t.ask or t.last or 0)
            mid = round((bid + ask) / 2, 2) if (bid > 0 and ask > 0) else _safe(t.last or t.close or 0)
        
        return {
            "ok": True, "conId": contract.conId, "ticker": req.ticker,
            "strike": req.strike, "expiry": expiry, "mid": mid,
            "bid": bid, "ask": ask, "market_closed": (bid == 0 or ask == 0)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/order/place")
async def place_order(req: PlaceOrderRequest):
    """Place a standard adaptive/limit order for a single contract."""
    tws = await get_tws()
    if not tws.connected or not tws.ib:
        raise HTTPException(status_code=503, detail="TWS not connected")
    try:
        import order_manager
        mgr = order_manager.get_manager()
        mgr.set_tws(tws)

        from ib_insync import Option as IBOption
        expiry = str(req.expiry).replace("-", "")
        contract = IBOption(req.ticker, expiry, req.strike, req.right, "SMART", currency="USD")
        
        # Qualify
        await tws.ib.qualifyContractsAsync(contract)
        if not contract.conId:
            raise HTTPException(status_code=404, detail="Contract not found")
        
        # Submit to OrderManager (non-blocking)
        internal_id = mgr.submit_order(
            ticker=req.ticker,
            right=req.right,
            strike=req.strike,
            expiry=expiry,
            action=req.action,
            qty=req.qty,
            limit_price=req.limit_price or 0.0,
            escalation_step_pct=1.0, # Default
            escalation_wait_mins=1,   # Default
            algo_speed="Normal"
        )
        return {"ok": True, "order_id": internal_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/order/combo")
async def place_combo(req: ComboRequest, background_tasks: BackgroundTasks):
    """Execute a BAG/Combo roll order (sell old LEAPS, buy new LEAPS) in background."""
    tws = await get_tws()
    if not tws.connected or not tws.ib:
        raise HTTPException(status_code=503, detail="TWS not connected")
    try:
        from ib_insync import Option as IBOption
        import tws_combo

        sell_exp = str(req.sell_expiry).replace("-", "")
        buy_exp  = str(req.buy_expiry).replace("-", "")

        sell_c = IBOption(req.ticker, sell_exp, req.sell_strike, "C", "SMART", currency="USD")
        buy_c  = IBOption(req.ticker, buy_exp,  req.buy_strike,  "C", "SMART", currency="USD")
        tws.ib.qualifyContracts(sell_c, buy_c)

        if not sell_c.conId or not buy_c.conId:
            raise HTTPException(status_code=404, detail="Could not qualify contracts")

        market_open = is_market_open()
        
        # If market is closed, we don't want to escalate forever
        esc_step = req.escalation_step_pct if market_open else 0.0
        max_esc  = 10 if market_open else 0

        # Run the execution logic in the background to prevent HTTP timeout
        background_tasks.add_task(
            tws_combo.execute_combo_roll,
            ib=tws.ib,
            sell_conid=sell_c.conId, sell_strike=req.sell_strike,
            sell_expiry=sell_c.lastTradeDateOrContractMonth,
            buy_conid=buy_c.conId,   buy_strike=req.buy_strike,
            buy_expiry=buy_c.lastTradeDateOrContractMonth,
            ticker=req.ticker, qty=req.qty,
            limit_price=req.limit_price,
            use_market=req.use_market,
            escalation_step_pct=esc_step,
            escalation_wait_secs=req.escalation_wait_secs,
            max_escalations=max_esc
        )
        
        return {"ok": True, "result": {"status": "SUBMITTED", "message": "Order sent to background worker"}}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/connect/{mode}")
async def connect(mode: str):
    """Force connect/reconnect TWS. mode=LIVE|DEMO|NONE (NONE=disconnect)."""
    global _tws
    if _tws is None:
        _tws = TWSClient()
    mode_up = mode.upper()
    if mode_up == "NONE":
        _tws.disconnect()
        return {"ok": True, "mode": "NONE", "account_id": ""}
        
    ok = await _tws.connectAsync(mode_up, timeout=8)
    return {"ok": ok, "mode": _tws.mode, "account_id": _tws.account_id}


@app.get("/orders")
async def get_orders():
    """Returns all managed orders from the singleton manager."""
    import order_manager
    mgr = order_manager.get_manager()
    orders = mgr.get_all_orders()
    # Convert to list of dicts for JSON
    res = []
    for mo in orders:
        res.append({
            "internal_id": next((k for k, v in mgr._orders.items() if v == mo), "?"),
            "ticker": mo.ticker,
            "strike": mo.strike,
            "expiry": mo.expiry,
            "status": mo.status,
            "current_price": mo.current_price,
            "is_combo": mo.is_combo,
            "escalation_count": mo.escalation_count
        })
    return {"ok": True, "orders": res}


@app.get("/health")
async def health():
    tws = await get_tws()
    return {
        "ok": True,
        "service": "api_ibkr",
        "port": 8002,
        "tws_connected": tws.connected,
        "mode": tws.mode,
        "account_id": tws.account_id,
    }


if __name__ == "__main__":
    import uvicorn
    config = uvicorn.Config(app, host="0.0.0.0", port=8002, log_level="info")
    server = uvicorn.Server(config)
    loop = asyncio.get_event_loop()
    loop.run_until_complete(server.serve())
