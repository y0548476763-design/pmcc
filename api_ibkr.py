"""
api_ibkr.py — HTTP Client for IBKR Worker
Provides Python wrapper functions to interact with the IBKR microservice.
No ib_insync logic here.
"""
import requests
from typing import List, Dict, Optional
import config

# The IBKR worker is running on port 8001
WORKER_URL = config.IBKR_API_URL
TIMEOUT = 30

def health_check() -> dict:
    try:
        return requests.get(f"{WORKER_URL}/health", timeout=5).json()
    except Exception as e:
        return {"ok": False, "error": str(e)}

def connect(mode: str = "DEMO") -> dict:
    try:
        return requests.post(f"{WORKER_URL}/api/ibkr/connect", params={"mode": mode}, timeout=10).json()
    except Exception as e:
        return {"ok": False, "error": str(e)}

def get_positions() -> dict:
    try:
        return requests.get(f"{WORKER_URL}/api/ibkr/positions", timeout=15).json()
    except Exception as e:
        return {"ok": False, "error": str(e)}

def qualify_combo(ticker: str, legs: List[dict]) -> dict:
    """
    legs format: [{"strike": 380.0, "expiry": "20260504", "right": "C", "action": "BUY", "qty": 1}, ...]
    """
    try:
        payload = {"ticker": ticker, "legs": legs}
        return requests.post(f"{WORKER_URL}/api/ibkr/qualify_combo", json=payload, timeout=TIMEOUT).json()
    except Exception as e:
        return {"ok": False, "error": str(e)}

def qualify_contract(ticker: str, strike: float, expiry: str, right: str = "C") -> dict:
    """Wrapper around qualify_combo for a single leg."""
    try:
        payload = {
            "ticker": ticker,
            "legs": [{"strike": strike, "expiry": expiry, "right": right, "action": "BUY", "qty": 1}]
        }
        r = requests.post(f"{WORKER_URL}/api/ibkr/qualify_combo", json=payload, timeout=TIMEOUT).json()
        if not r.get("ok"): return {"ok": False, "error": r.get("detail", "Error")}
        leg = r["legs"][0]
        return {"ok": True, "conId": leg["conId"], "ticker": ticker, "strike": strike, "expiry": expiry, "mid": leg["mid"]}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def place_order(ticker: str, strike: float, expiry: str, right: str = "C", action: str = "BUY", qty: int = 1, limit_price: float = None, order_type: str = "LMT") -> dict:
    try:
        payload = {
            "ticker": ticker, "strike": strike, "expiry": expiry,
            "right": right, "action": action, "qty": qty, "limit_price": limit_price, "order_type": order_type
        }
        return requests.post(f"{WORKER_URL}/api/ibkr/place_order", json=payload, timeout=15).json()
    except Exception as e:
        return {"ok": False, "error": str(e)}

def place_combo(ticker: str, legs: List[dict], limit_price: float, use_market: bool = False, escalation_step_pct: float = 1.0, escalation_wait_secs: int = 180, scheduled_time: str = None) -> dict:
    try:
        payload = {
            "ticker": ticker, "legs": legs, "limit_price": limit_price, "use_market": use_market,
            "escalation_step_pct": escalation_step_pct, "escalation_wait_secs": escalation_wait_secs
        }
        if scheduled_time:
            payload["scheduled_time"] = scheduled_time
        return requests.post(f"{WORKER_URL}/order/combo", json=payload, timeout=60).json()
    except Exception as e:
        return {"ok": False, "error": str(e)}

def get_active_orders() -> dict:
    try:
        return requests.get(f"{WORKER_URL}/api/orders/active", timeout=10).json()
    except Exception as e:
        return {"ok": False, "error": str(e)}

def get_iv(ticker: str) -> dict:
    try:
        return requests.get(f"{WORKER_URL}/api/ibkr/get_iv/{ticker}", timeout=15).json()
    except Exception as e:
        return {"ok": False, "error": str(e)}

def notify(message: str) -> dict:
    try:
        return requests.post(f"{WORKER_URL}/api/notify", json={"message": message}, timeout=5).json()
    except Exception as e:
        return {"ok": False, "error": str(e)}
