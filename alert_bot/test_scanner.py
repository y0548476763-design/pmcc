import sys
import os

# Add current directory to path so we can import modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from scanner import AlertScanner
from datetime import datetime

# Mock configuration with very low thresholds to trigger alerts during test
test_config = {
    "tg_token": "MOCK_TOKEN",
    "tg_chat_id": "MOCK_ID",
    "index_drop_thresh": 0.01, # Trigger on 0.01% drop
    "index_rsi_thresh": 90.0,   # Trigger if RSI < 90 (almost always)
    "stock_drop_thresh": 0.01,
    "macro_qqq_thresh": -10.0,  # Always confirm macro
    "scan_interval_min": 1
}

def mock_log(msg):
    print(f"[TEST LOG] {msg}")

def test_run():
    print("--- STARTING BOT LOGIC TEST ---")
    scanner = AlertScanner(test_config, log_callback=mock_log)
    
    # We will override send_alert to not actually call Telegram API
    def mock_send_alert(ticker, message):
        mock_log(f"!!! TRIGGERED ALERT FOR {ticker} !!!")
        print(f"Message content:\n{message}\n")
        # Record hit
        hits.append(ticker)
        
    scanner.send_alert = mock_send_alert
    
    global hits
    hits = []
    
    try:
        scanner.scan_once()
        print("--- TEST COMPLETED ---")
        if len(hits) > 0:
            print(f"Success: Detected triggers for {len(hits)} tickers.")
        else:
            print("No triggers detected (market might be flat or data fetch failed).")
            
    except Exception as e:
        print(f"ERROR DURING TEST: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_run()
