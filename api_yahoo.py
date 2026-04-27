"""
api_yahoo.py — HTTP Client for Yahoo Worker
Provides Python wrapper functions to interact with the Yahoo microservice.
No yfinance logic here.
"""
import requests

# The Yahoo worker is running on port 8002
WORKER_URL = "http://localhost:8002"
TIMEOUT = 30

def health_check() -> dict:
    try:
        return requests.get(f"{WORKER_URL}/health", timeout=5).json()
    except Exception as e:
        return {"ok": False, "error": str(e)}

def get_expected_move(ticker: str) -> dict:
    try:
        return requests.get(f"{WORKER_URL}/api/yahoo/expected_move/{ticker}", timeout=TIMEOUT).json()
    except Exception as e:
        return {"ok": False, "error": str(e)}

def search_leaps(ticker: str, min_dte: int = 540, target_delta: float = 0.80, n: int = 5) -> dict:
    try:
        params = {"ticker": ticker, "min_dte": min_dte, "target_delta": target_delta, "n": n}
        return requests.get(f"{WORKER_URL}/api/yahoo/leaps/search", params=params, timeout=TIMEOUT).json()
    except Exception as e:
        return {"ok": False, "error": str(e)}

def search_options(ticker: str, min_dte: int = 30, max_dte: int = 60, target_delta: float = 0.10, right: str = "C", n: int = 4) -> dict:
    try:
        params = {
            "ticker": ticker, "min_dte": min_dte, "max_dte": max_dte,
            "target_delta": target_delta, "right": right, "n": n
        }
        return requests.get(f"{WORKER_URL}/api/yahoo/options/search", params=params, timeout=TIMEOUT).json()
    except Exception as e:
        return {"ok": False, "error": str(e)}
