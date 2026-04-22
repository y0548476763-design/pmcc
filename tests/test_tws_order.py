import config
config.TWS_CLIENT_ID = 188  # Prevent clientId 42 collision with Streamlit!
from tws_client import TWSClient
import time
import logging

logging.basicConfig(level=logging.INFO)

def run_test():
    print(f"Connecting to TWS on client ID {config.TWS_CLIENT_ID}...")
    client = TWSClient()
    if not client.connect("DEMO"):
        print("COULD NOT CONNECT TO TWS.")
        return

    print("Connected successfully. Attempting to place an adaptive order for AAPL 2026-03-20 200C...")
    
    oid = client.place_adaptive_order(
        action="BUY",
        qty=1,
        ticker="AAPL",
        right="C",
        strike=200.0,
        expiry="2026-03-20",
        limit_price=5.50,
        order_type="LMT",
        algo_speed="Normal"
    )
    
    if oid:
        print(f"SUCCESS! Order placed with ID: {oid}")
        time.sleep(1)
        client.cancel_order(oid)
        print("Order cancelled.")
    else:
        print("FAILED to place order.")
        
    client.disconnect()

if __name__ == "__main__":
    run_test()
