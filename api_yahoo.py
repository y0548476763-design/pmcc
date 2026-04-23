"""
api_yahoo.py — Yahoo Finance data server (port 8001)
Endpoints: /technicals/{ticker}, /leaps/search, /analyse
"""
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import time, logging, dataclasses
from datetime import datetime, timezone

app = FastAPI(title="PMCC Yahoo API", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
logger = logging.getLogger(__name__)

# ── Technicals ─────────────────────────────────────────────────────────────

@app.get("/technicals/{ticker}")
def get_technicals(ticker: str):
    """RSI, SMA150/200, Bollinger Bands, HV30 for a ticker."""
    try:
        from data_feed import compute_technicals
        result = compute_technicals(ticker.upper())
        return {"ok": True, "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/cache")
def clear_cache():
    """Force-clear the 4-hour price cache."""
    from data_feed import clear_data_cache
    clear_data_cache()
    return {"ok": True, "msg": "Cache cleared"}

# ── LEAPS Search ───────────────────────────────────────────────────────────

_leaps_cache: dict = {}   # {key: (data, timestamp)}
_CACHE_TTL = 14400        # 4 hours

@app.get("/leaps/search")
def search_leaps(
    ticker: str = Query(...),
    min_dte: int = Query(540),
    target_delta: float = Query(0.80),
    n: int = Query(5),
):
    """Search Yahoo Finance for LEAPS call options using yfinance."""
    ticker = ticker.upper()
    key = f"leaps_{ticker}_{min_dte}_{target_delta}"
    now = time.time()

    if key in _leaps_cache:
        data, ts = _leaps_cache[key]
        if now - ts < _CACHE_TTL:
            return {"ok": True, "cached": True, "data": data}

    try:
        import yfinance as yf
        from dateutil.parser import parse
        
        stock = yf.Ticker(ticker)
        expiries = stock.options
        if not expiries:
            return {"ok": True, "cached": False, "data": []}

        today = datetime.now()
        valid = []
        for e in expiries:
            try:
                dte = (parse(e) - today).days
                if dte >= min_dte:
                    valid.append((e, dte))
            except:
                continue
        
        # Fallback to furthest if none match min_dte
        if not valid:
            valid = sorted([(e, (parse(e) - today).days) for e in expiries], key=lambda x: x[1], reverse=True)[:1]
        
        if not valid:
            return {"ok": True, "cached": False, "data": []}

        valid.sort(key=lambda x: x[1])
        target_expiry, exp_dte = valid[0]
        
        chain = stock.option_chain(target_expiry)
        calls = chain.calls
        if calls.empty:
            return {"ok": True, "cached": False, "data": []}
            
        underlying = float(stock.fast_info.last_price or 0)
        if underlying <= 0:
            # Fallback for underlying price from mid strike
            underlying = float(calls['strike'].iloc[len(calls)//2])

        results = []
        for idx, row in calls.iterrows():
            strike = float(row['strike'])
            bid = float(row.get('bid', 0))
            ask = float(row.get('ask', 0))
            last = float(row.get('lastPrice', 0))
            mid = (bid + ask) / 2 if (bid > 0 and ask > 0) else last
            
            if mid <= 0: continue
            
            # Approximate delta
            mono = strike / underlying if underlying > 0 else 1.0
            delta = max(0.05, min(0.99, 1.25 - mono * 0.75))
            
            results.append({
                "ticker": ticker, "strike": round(strike, 2),
                "expiry": target_expiry, "dte": exp_dte, "right": "C",
                "delta": round(delta, 2), "mid": round(mid, 2),
                "bid": round(bid, 2), "ask": round(ask, 2),
                "source": "Yahoo Finance (yf)",
            })

        results.sort(key=lambda x: abs(x["delta"] - target_delta))
        final = results[:n]
        _leaps_cache[key] = (final, time.time())
        return {"ok": True, "cached": False, "data": final}

    except Exception as e:
        logger.error(f"Search LEAPS error: {e}")
        raise HTTPException(status_code=500, detail=str(e))



@app.get("/options/search")
def search_options(
    ticker: str = Query(...),
    min_dte: int = Query(30),
    max_dte: int = Query(60),
    target_delta: float = Query(0.10),
    right: str = Query("C"),
    n: int = Query(4),
):
    """Search Yahoo Finance for short-dated options using yfinance."""
    ticker = ticker.upper()
    key = f"opt_{ticker}_{min_dte}_{max_dte}_{target_delta}_{right}"
    now = time.time()

    if key in _leaps_cache:
        data, ts = _leaps_cache[key]
        if now - ts < 900:
            return {"ok": True, "cached": True, "data": data}

    try:
        import yfinance as yf
        from dateutil.parser import parse
        
        stock = yf.Ticker(ticker)
        expiries = stock.options
        if not expiries:
            return {"ok": True, "cached": False, "data": []}

        today = datetime.now()
        # Find expirations in DTE range
        valid = []
        for e in expiries:
            try:
                dte = (parse(e) - today).days
                if min_dte <= dte <= max_dte:
                    valid.append((e, dte))
            except:
                continue
        
        if not valid:
            # Fallback: closest to midpoint
            mid_target = (min_dte + max_dte) / 2
            valid = sorted([(e, (parse(e) - today).days) for e in expiries], key=lambda x: abs(x[1] - mid_target))[:1]
        
        if not valid:
            return {"ok": True, "cached": False, "data": []}

        results = []
        for target_expiry, exp_dte in valid[:2]: # check up to 2 expiries
            chain = stock.option_chain(target_expiry)
            calls_or_puts = chain.calls if right.upper() == "C" else chain.puts
            if calls_or_puts.empty: continue
                
            underlying = float(stock.fast_info.last_price or 0)
            if underlying <= 0:
                underlying = float(calls_or_puts['strike'].iloc[len(calls_or_puts)//2])

            for idx, row in calls_or_puts.iterrows():
                strike = float(row['strike'])
                bid, ask = float(row.get('bid', 0)), float(row.get('ask', 0))
                mid = (bid + ask) / 2 if (bid > 0 and ask > 0) else float(row.get('lastPrice', 0))
                
                if mid <= 0: continue
                
                mono = strike / underlying if underlying > 0 else 1.0
                if right.upper() == "C":
                    delta = max(0.01, min(0.99, 1.30 - mono * 0.80))
                else:
                    delta = max(0.01, min(0.99, mono * 0.80 - 0.30))
                
                results.append({
                    "ticker": ticker, "strike": round(strike, 2),
                    "expiry": target_expiry, "dte": exp_dte, "right": right.upper(),
                    "delta": round(delta, 2), "mid": round(mid, 2),
                    "bid": round(bid, 2), "ask": round(ask, 2),
                    "source": "Yahoo Finance (yf)",
                })

        results.sort(key=lambda x: abs(x["delta"] - target_delta))
        final = results[:n]
        _leaps_cache[key] = (final, time.time())
        return {"ok": True, "cached": False, "data": final}

    except Exception as e:
        logger.error(f"Search options error: {e}")
        raise HTTPException(status_code=500, detail=str(e))



@app.get("/health")
def health():
    return {"ok": True, "service": "api_yahoo", "port": 8001}


# ── Portfolio Analysis ──────────────────────────────────────────────────────

class AnalyseRequest(BaseModel):
    positions: List[dict]
    watchlist: Optional[List[str]] = None

@app.post("/analyse")
def analyse_portfolio(body: AnalyseRequest):
    """
    Run full quant engine analysis server-side.
    Returns QuantResult dicts (serialized) per ticker.
    Dashboard just displays the result — no heavy work on its end.
    """
    try:
        from quant_engine import QuantEngine
        engine = QuantEngine()
        results = engine.analyse_portfolio(body.positions, watchlist=body.watchlist)
        # Serialize dataclasses → plain dicts for JSON transport
        serialized = {ticker: dataclasses.asdict(qr) for ticker, qr in results.items()}
        return {"ok": True, "results": serialized}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
