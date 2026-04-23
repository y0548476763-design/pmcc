import requests
url = "http://localhost:8002/order/combo"
payload = {
    "ticker": "META",
    "qty": 1,
    "sell_strike": 490,
    "sell_expiry": "2028-06-16",
    "buy_strike": 250,
    "buy_expiry": "2028-06-16",
    "limit_price": 59.67,
    "escalation_step_pct": 1.0,
    "escalation_wait_secs": 60
}
try:
    r = requests.post(url, json=payload, timeout=20)
    print(f"Status: {r.status_code}")
    print(f"Response: {r.text}")
except Exception as e:
    print(f"Error: {e}")
