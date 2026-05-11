import requests

def check_googl():
    url = "http://localhost:8002/api/yahoo/options/search"
    params = {
        "ticker": "GOOGL",
        "min_dte": 5,
        "max_dte": 60,
        "target_delta": 0.2,
        "right": "C",
        "n": 5
    }
    try:
        r = requests.get(url, params=params)
        print(f"Status: {r.status_code}")
        print(f"Data: {r.text}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_googl()
