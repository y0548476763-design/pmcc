"""
api_ibkr.py — HTTP Client for IBKR Worker
Provides Python wrapper functions to interact with the IBKR microservice.
No ib_insync logic here.
"""
import requests
from typing import List, Dict, Optional

# The IBKR worker is running on port 8001
WORKER_URL = "http://localhost:8001"
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

def place_order(ticker: str, strike: float, expiry: str, right: str = "C", action: str = "BUY", qty: int = 1, limit_price: float = None) -> dict:
    try:
        payload = {
            "ticker": ticker, "strike": strike, "expiry": expiry,
            "right": right, "action": action, "qty": qty, "limit_price": limit_price
        }
        return requests.post(f"{WORKER_URL}/api/ibkr/place_order", json=payload, timeout=15).json()
    except Exception as e:
        return {"ok": False, "error": str(e)}

def get_iv(ticker: str) -> dict:
    try:
        return requests.get(f"{WORKER_URL}/api/ibkr/get_iv/{ticker}", timeout=15).json()
    except Exception as e:
        return {"ok": False, "error": str(e)}
