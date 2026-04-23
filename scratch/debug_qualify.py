import requests
url = "http://localhost:8002/qualify"
payload = {
    "ticker": "META",
    "strike": 280.0,
    "expiry": "2028-06-16",
    "right": "C"
}
try:
    r = requests.post(url, json=payload, timeout=20)
    print(f"Status: {r.status_code}")
    print(f"Response: {r.text}")
except Exception as e:
    print(f"Error: {e}")
