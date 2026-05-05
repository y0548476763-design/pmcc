"""
api_ibkr.py — HTTP Client for IBKR Worker
Provides Python wrapper functions to interact with the IBKR microservice.
No ib_insync logic here.
"""
import requests
import threading
import time
from datetime import datetime
from typing import List, Dict, Optional
import config

def schedule_internal_task(target_time_str: str, task_func, *args, **kwargs):
    def _runner():
        try:
            now = datetime.now()
            if ":" in target_time_str and "T" not in target_time_str:
                parts = target_time_str.split(":")
                target = now.replace(hour=int(parts[0]), minute=int(parts[1]), second=0, microsecond=0)
                if target < now: target = target.replace(day=target.day + 1)
            else:
                target = datetime.fromisoformat(target_time_str)
            delay = (target - now).total_seconds()
            if delay > 0: time.sleep(delay)
            task_func(*args, **kwargs)
        except Exception as e:
            print(f"Scheduler Error: {e}")
    threading.Thread(target=_runner, daemon=True).start()

# The IBKR worker is running on port 8001
WORKER_URL = config.IBKR_API_URL
TIMEOUT = 30

def health_check() -> dict:
    try:
        r = requests.get(f"{WORKER_URL}/status", timeout=5).json()
        return {"ok": True, "connected": r.get("connected", False)}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def connect(mode: str = "DEMO") -> dict:
    try:
        return requests.post(f"{WORKER_URL}/connect", timeout=10).json()
    except Exception as e:
        return {"ok": False, "error": str(e)}

def get_positions() -> dict:
    """מושך את הפורטפוליו מהוורקר ומחזיר אותו במבנה שה-PMCC מכיר"""
    try:
        r = requests.get(f"{WORKER_URL}/portfolio", timeout=15).json()
        # PMCC מחפש את המפתח 'positions' כדי להציג את הטבלה
        return {"ok": True, "positions": r}
    except Exception as e:
        return {"ok": False, "error": str(e), "positions": []}

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
    try:
        payload = {"symbol": ticker, "secType": "OPT", "action": "BUY", "ratio": 1, "strike": strike, "expiry": expiry, "right": right}
        r = requests.post(f"{WORKER_URL}/qualify", json=payload, timeout=TIMEOUT).json()
        if not r.get("ok"): return {"ok": False, "error": r.get("error", "Error")}
        return {"ok": True, "conId": r.get("con_id"), "ticker": ticker, "strike": strike, "expiry": expiry, "mid": 0.0}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def place_order(ticker: str, strike: float, expiry: str, right: str = "C", action: str = "BUY", qty: int = 1, limit_price: float = None, order_type: str = "LMT", **kwargs) -> dict:
    try:
        # התאמה מלאה למודל OrderRequest של הוורקר
        payload = {
            "action": action,
            "order_type": order_type,
            "total_qty": float(qty),
            "lmt_price": float(limit_price or 0.0),
            "esc_pct": float(kwargs.get("esc_pct", 0.01)),
            "esc_interval": int(kwargs.get("esc_interval", 30)),
            "max_steps": int(kwargs.get("max_steps", 5)),
            "legs": [{
                "symbol": ticker,
                "secType": "OPT",
                "action": action,
                "ratio": 1.0,
                "strike": float(strike),
                "expiry": str(expiry).replace("-", ""), # וודוא פורמט YYYYMMDD
                "right": right,
                "con_id": int(kwargs.get("con_id", 0))
            }]
        }
        r = requests.post(f"{WORKER_URL}/submit", json=payload, timeout=15).json()
        return {"ok": True, "order_id": r.get("order_id"), "message": r.get("message")}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def place_combo(ticker: str, legs: List[dict], limit_price: float, use_market: bool = False, 
                escalation_step_pct: float = 1.0, escalation_wait_secs: int = 60, **kwargs) -> dict:
    """
    שליחת קומבו (כולל גלגולי ליפסים ודוחות) לוורקר החדש.
    הלוגיקה של יאהו נשמרת - הוורקר יבצע את ה-Qualify.
    """
    try:
        mapped_legs = []
        for l in legs:
            mapped_legs.append({
                "symbol": ticker,
                "secType": "OPT",
                "action": l.get("action", "BUY"),
                "ratio": l.get("qty", 1),
                "strike": l.get("strike"),
                "expiry": l.get("expiry"),
                "right": l.get("right", "C"),
                "con_id": l.get("con_id", 0)
            })
        
        payload = {
            "action": "BUY", # בדרך כלל BUY עבור נטו דביט/קרדיט בקומבו
            "order_type": "MKT" if use_market else "LMT",
            "total_qty": 1,
            "lmt_price": limit_price,
            "esc_pct": escalation_step_pct / 100.0,
            "esc_interval": escalation_wait_secs,
            "max_steps": 10,
            "legs": mapped_legs
        }
        r = requests.post(f"{WORKER_URL}/submit", json=payload, timeout=30).json()
        return {"ok": True, "order_id": r.get("order_id"), "message": "הבקשה נשלחה לוורקר"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def get_active_orders() -> dict:
    try:
        return requests.get(f"{WORKER_URL}/api/orders/active", timeout=10).json()
    except Exception as e:
        return {"ok": False, "error": str(e)}

def get_escalations_status() -> dict:
    try:
        r = requests.get(f"{WORKER_URL}/monitor", timeout=5).json()
        escalations = [{"order_id": oid, "status": info.get("internal_status", ""), "ib_status": info.get("ib_status", ""), "current_price": info.get("final_fill", 0.0)} for oid, info in r.items()]
        return {"ok": True, "escalations": escalations}
    except Exception as e:
        return {"ok": False, "escalations": [], "error": str(e)}

def cancel_escalation(order_id: int) -> dict:
    try:
        return requests.post(f"{WORKER_URL}/cancel_all", timeout=5).json()
    except Exception as e:
        return {"ok": False, "error": str(e)}

def get_iv(ticker: str) -> dict:
    try:
        r = requests.post(f"{WORKER_URL}/ticker", json={"symbol": ticker, "secType": "STK", "action": "BUY", "ratio": 1}, timeout=15).json()
        if "error" in r: return {"ok": False, "error": r["error"]}
        return {"ok": True, "iv": r.get("avg_iv") or r.get("iv") or 0.0, "price": r.get("price", 0.0), "rank": r.get("iv_rank", 0.0)}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def notify(message: str) -> dict:
    try:
        return requests.post(f"{WORKER_URL}/api/notify", json={"message": message}, timeout=5).json()
    except Exception as e:
        return {"ok": False, "error": str(e)}

