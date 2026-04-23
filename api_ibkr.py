"""
api_ibkr.py — IBKR TWS server (port 8002)
Singleton TWS connection shared across all requests.
Endpoints: GET /portfolio, POST /qualify, POST /order/combo
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import logging, threading, asyncio

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

def get_tws() -> TWSClient:
    global _tws
    with _lock:
        if _tws is None:
            _tws = TWSClient()
        if not _tws.connected:
            # In FastAPI, sync 'def' routes run in threads.
            # Each thread needs its own event loop for ib_insync.
            try:
                asyncio.get_event_loop()
            except RuntimeError:
                asyncio.set_event_loop(asyncio.new_event_loop())
            
            cid = 88
            logger.info("Attempting auto-connect to IBKR (7496/4002/7497)...")
            # Try ports sequentially. Port 4002 is often Paper. 7497 is TWS Paper.
            if not _tws.connect("LIVE", port=7496, client_id=cid, timeout=4):
                if not _tws.connect("DEMO", port=4002, client_id=cid, timeout=4):
                    _tws.connect("DEMO", port=7497, client_id=cid, timeout=4)
    return _tws


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


# ── Endpoints ──────────────────────────────────────────────────────────────

@app.get("/portfolio")
def get_portfolio():
    """Returns positions + account balances from TWS."""
    tws = get_tws()
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
def qualify_contract(req: QualifyRequest):
    """Qualify a single option contract and return conId + live bid/ask."""
    tws = get_tws()
    if not tws.connected or not tws.ib:
        raise HTTPException(status_code=503, detail="TWS not connected")
    try:
        from ib_insync import Option as IBOption
        expiry = str(req.expiry).replace("-", "")
        contract = IBOption(req.ticker, expiry, req.strike, req.right,
                            "SMART", currency="USD")
        tws.ib.qualifyContracts(contract)
        if not contract.conId:
            raise HTTPException(status_code=404, detail="Contract not found on IBKR")

        tickers = tws.ib.reqTickers(contract)
        tws.ib.sleep(0.5)
        bid = ask = mid = 0.0
        if tickers:
            t = tickers[0]
            bid = float(t.bid) if t.bid and t.bid > 0 else 0.0
            ask = float(t.ask) if t.ask and t.ask > 0 else 0.0
            mid = round((bid + ask) / 2, 2) if bid > 0 and ask > 0 else float(t.last or 0)

        return {
            "ok": True,
            "conId": contract.conId,
            "ticker": req.ticker,
            "strike": req.strike,
            "expiry": req.expiry,
            "right": req.right,
            "bid": round(bid, 2),
            "ask": round(ask, 2),
            "mid": round(mid, 2),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/order/combo")
def place_combo(req: ComboRequest):
    """Execute a BAG/Combo roll order (sell old LEAPS, buy new LEAPS)."""
    tws = get_tws()
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
            raise HTTPException(status_code=404, detail="Could not qualify one or both contracts")

        result = tws_combo.execute_combo_roll(
            ib=tws.ib,
            sell_conid=sell_c.conId, sell_strike=req.sell_strike,
            sell_expiry=sell_c.lastTradeDateOrContractMonth,
            buy_conid=buy_c.conId,   buy_strike=req.buy_strike,
            buy_expiry=buy_c.lastTradeDateOrContractMonth,
            ticker=req.ticker, qty=req.qty,
            limit_price=req.limit_price,
            use_market=req.use_market,
            escalation_step_pct=req.escalation_step_pct,
            escalation_wait_secs=req.escalation_wait_secs,
        )
        return {"ok": True, "result": result}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/connect/{mode}")
def connect(mode: str):
    """Force connect/reconnect TWS. mode=LIVE|DEMO|NONE (NONE=disconnect)."""
    global _tws
    with _lock:
        if _tws is None:
            _tws = TWSClient()
    mode_up = mode.upper()
    if mode_up == "NONE":
        _tws.disconnect()
        return {"ok": True, "mode": "NONE", "account_id": ""}
    
    # Ensure thread loop
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
        
    ok = _tws.connect(mode_up, timeout=8)
    return {"ok": ok, "mode": _tws.mode, "account_id": _tws.account_id}


@app.get("/health")
def health():
    tws = get_tws()
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
    uvicorn.run(app, host="0.0.0.0", port=8002)
