from ib_insync import *
import time

def test_connection():
    ib = IB()
    host = '34.61.20.54'
    port = 4002
    client_id = 99  # Testing ID

    print(f"Attempting to connect to {host}:{port}...")
    try:
        ib.connect(host, port, clientId=client_id)
        print("[SUCCESS] Connected to IBKR Gateway!")
        
        # Pull basic account info to verify permissions
        account_summary = ib.accountSummary()
        print(f"Connected Account: {account_summary[0].account if account_summary else 'Unknown'}")
        
        ib.disconnect()
    except Exception as e:
        print(f"[FAILED] Could not connect to Gateway. Error: {e}")
        print("\nPossible reasons:")
        print("1. Firewall on GCP is blocking port 4002.")
        print("2. The Gateway container is not listening on 0.0.0.0 (check ibc_config.ini).")
        print("3. Public IP has changed (unlikely with static IP).")

if __name__ == "__main__":
    test_connection()
