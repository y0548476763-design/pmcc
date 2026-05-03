import requests
import json

URL = "http://localhost:8002/health"

try:
    r = requests.get(URL, timeout=5)
    print(f"Health: {r.status_code}")
    print(r.json())
except Exception as e:
    print(f"Error connecting to 8002: {e}")

# Test a known ticker
URL_TECH = "http://localhost:8002/api/yahoo/expected_move/AAPL"
try:
    r = requests.get(URL_TECH, timeout=10)
    print(f"AAPL tech: {r.status_code}")
    print(r.json())
except Exception as e:
    print(f"Error calling AAPL tech: {e}")
