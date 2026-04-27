"""
yahoo_worker.py — Standalone Yahoo Finance Service (port 8002)
Handles all yfinance requests natively, completely detached from the main UI.
Implements the SSL bypass to avoid Antivirus inspection errors.
"""
import ssl
import logging
import time
from datetime import datetime
from dateutil.parser import parse

from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import urllib3
import requests

import yfinance as yf

# ── SSL Bypass ─────────────────────────────────────────────────────────────
# 1. Global unverified context (most reliable for yfinance >= 0.2.x)
ssl._create_default_https_context = ssl._create_unverified_context
# 2. Disable urllib3 warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 3. Custom session as requested, though we fall back to standard if yfinance complains about curl_cffi
custom_session = requests.Session()
custom_session.verify = False

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Yahoo Finance Worker Service", version="2.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def get_ticker(symbol: str) -> yf.Ticker:
    """Helper to safely get a Ticker object with SSL bypassed."""
    try:
        # Try with custom session first
        return yf.Ticker(symbol, session=custom_session)
    except Exception as e:
        if "curl_cffi" in str(e).lower() or "session" in str(e).lower():
            # Fallback to default (global SSL patch handles the bypass)
            return yf.Ticker(symbol)
        raise

# ── Endpoints ──────────────────────────────────────────────────────────────

@app.get("/health")
def health_check():
    return {"status": "ok", "service": "yahoo_worker", "port": 8002}

@app.get("/api/yahoo/expected_move/{ticker}")
def get_expected_move(ticker: str):
    """
    Calculates the Expected Move for the nearest valid expiration date (>=5 DTE)
    using ATM Straddle pricing.
    """
    try:
        t = get_ticker(ticker.upper())
        
        # Spot price
        try:
            spot = float(t.fast_info.last_price or 0)
        except:
            spot = 0.0
            
        if spot <= 0:
            hist = t.history(period="1d")
            spot = float(hist["Close"].iloc[-1]) if not hist.empty else 0.0
            
        if spot <= 0:
            raise ValueError(f"Could not fetch spot price for {ticker}")

        exps = t.options
        if not exps:
            raise ValueError(f"No options available for {ticker}")

        today = datetime.now()
        nearest = None
        for e in sorted(exps):
            try:
                dte = (parse(e) - today).days
                if dte >= 5:
                    nearest = (e, dte)
                    break
            except:
                continue
                
        if not nearest:
            nearest = (exps[0], (parse(exps[0]) - today).days)

        exp_str, dte = nearest
        chain = t.option_chain(exp_str)
        calls = chain.calls
        puts = chain.puts

        # Find ATM Straddle
        atm_call = calls.iloc[(calls["strike"] - spot).abs().argsort()[:1]]
        atm_put = puts.iloc[(puts["strike"] - spot).abs().argsort()[:1]]

        call_ask = float(atm_call["ask"].values[0]) if not atm_call.empty else 0.0
        put_ask = float(atm_put["ask"].values[0]) if not atm_put.empty else 0.0

        if call_ask <= 0:
            call_ask = float(atm_call["lastPrice"].values[0]) if not atm_call.empty else 0.0
        if put_ask <= 0:
            put_ask = float(atm_put["lastPrice"].values[0]) if not atm_put.empty else 0.0

        em = round(call_ask + put_ask, 2)
        
        return {
            "ok": True,
            "data": {
                "ticker": ticker.upper(),
                "spot": round(spot, 2),
                "expiry": exp_str,
                "dte": dte,
                "call_ask": round(call_ask, 2),
                "put_ask": round(put_ask, 2),
                "expected_move": em,
            }
        }
    except Exception as e:
        logger.error(f"EM Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/yahoo/leaps/search")
def search_leaps(
    ticker: str = Query(...),
    min_dte: int = Query(540),
    target_delta: float = Query(0.80),
    n: int = Query(5),
):
    """Search Yahoo Finance for LEAPS call options."""
    try:
        t = get_ticker(ticker.upper())
        expiries = t.options
        if not expiries:
            return {"ok": True, "data": []}

        today = datetime.now()
        valid = []
        for e in expiries:
            try:
                dte = (parse(e) - today).days
                if dte >= min_dte:
                    valid.append((e, dte))
            except:
                continue
                
        if not valid:
            valid = sorted([(e, (parse(e) - today).days) for e in expiries], key=lambda x: x[1], reverse=True)[:1]
            
        if not valid:
            return {"ok": True, "data": []}

        valid.sort(key=lambda x: x[1])
        target_expiry, exp_dte = valid[0]
        
        chain = t.option_chain(target_expiry)
        calls = chain.calls
        if calls.empty:
            return {"ok": True, "data": []}
            
        try:
            underlying = float(t.fast_info.last_price or 0)
        except:
            underlying = 0.0
            
        if underlying <= 0:
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
                "ticker": ticker.upper(), "strike": round(strike, 2),
                "expiry": target_expiry, "dte": exp_dte, "right": "C",
                "delta": round(delta, 2), "mid": round(mid, 2),
                "bid": round(bid, 2), "ask": round(ask, 2),
                "source": "Yahoo Finance (yf)",
            })

        results.sort(key=lambda x: abs(x["delta"] - target_delta))
        return {"ok": True, "data": results[:n]}

    except Exception as e:
        logger.error(f"Search LEAPS error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/yahoo/options/search")
def search_options(
    ticker: str = Query(...),
    min_dte: int = Query(30),
    max_dte: int = Query(60),
    target_delta: float = Query(0.10),
    right: str = Query("C"),
    n: int = Query(4),
):
    """Search Yahoo Finance for options in a specific DTE range."""
    try:
        t = get_ticker(ticker.upper())
        expiries = t.options
        if not expiries:
            return {"ok": True, "data": []}

        today = datetime.now()
        valid = []
        for e in expiries:
            try:
                dte = (parse(e) - today).days
                if min_dte <= dte <= max_dte:
                    valid.append((e, dte))
            except:
                continue
                
        if not valid:
            mid_target = (min_dte + max_dte) / 2
            valid = sorted([(e, (parse(e) - today).days) for e in expiries], key=lambda x: abs(x[1] - mid_target))[:1]
            
        if not valid:
            return {"ok": True, "data": []}

        results = []
        for target_expiry, exp_dte in valid[:2]:
            chain = t.option_chain(target_expiry)
            opts = chain.calls if right.upper() == "C" else chain.puts
            if opts.empty: continue
                
            try: underlying = float(t.fast_info.last_price or 0)
            except: underlying = 0.0
            
            if underlying <= 0:
                underlying = float(opts['strike'].iloc[len(opts)//2])

            for idx, row in opts.iterrows():
                strike = float(row['strike'])
                bid, ask = float(row.get('bid', 0)), float(row.get('ask', 0))
                mid = (bid + ask) / 2 if (bid > 0 and ask > 0) else float(row.get('lastPrice', 0))
                if mid <= 0: continue
                
                mono = strike / underlying if underlying > 0 else 1.0
                if right.upper() == "C":
                    delta = max(0.05, min(0.99, 1.25 - mono * 0.75))
                else:
                    delta = max(0.05, min(0.99, mono * 0.75 - 0.25))

                results.append({
                    "ticker": ticker.upper(), "strike": round(strike, 2),
                    "expiry": target_expiry, "dte": exp_dte, "right": right.upper(),
                    "delta": round(delta, 2), "mid": round(mid, 2),
                    "bid": round(bid, 2), "ask": round(ask, 2),
                    "source": "Yahoo Finance",
                })

        results.sort(key=lambda x: abs(x["delta"] - target_delta))
        return {"ok": True, "data": results[:n]}

    except Exception as e:
        logger.error(f"Search Options error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    # Standalone server running on port 8002
    uvicorn.run(app, host="0.0.0.0", port=8002)
