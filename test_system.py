import requests
import time
import json

WORKER_URL = "http://127.0.0.1:8001"
REPORT = []

def log_result(test_name: str, success: bool, details: str = ""):
    status = "SUCCESS" if success else "FAILED"
    msg = f"{status} | {test_name}"
    if details:
        msg += f" | Details: {details}"
    print(msg)
    REPORT.append(msg)

def test_connection():
    try:
        res = requests.get(f"{WORKER_URL}/status", timeout=5).json()
        if res.get("connected"):
            log_result("IBKR Connection (status/)", True, f"Port: {res.get('port')}")
            return True
        else:
            log_result("IBKR Connection (status/)", False, "Worker reports NOT connected to TWS")
            return False
    except Exception as e:
        log_result("IBKR Connection (status/)", False, str(e))
        return False

def test_portfolio():
    try:
        res = requests.get(f"{WORKER_URL}/portfolio", timeout=10).json()
        if isinstance(res, list):
            log_result("Fetch Portfolio (portfolio/)", True, f"Retrieved {len(res)} positions")
        else:
            log_result("Fetch Portfolio (portfolio/)", False, f"Unexpected response: {res}")
    except Exception as e:
        log_result("Fetch Portfolio (portfolio/)", False, str(e))

def test_qualify():
    try:
        payload = {"symbol": "AAPL", "secType": "STK", "action": "BUY", "ratio": 1}
        res = requests.post(f"{WORKER_URL}/qualify", json=payload, timeout=10).json()
        if res.get("ok"):
            log_result("Qualify Contract (qualify/)", True, f"ConID: {res.get('con_id')}")
        else:
            log_result("Qualify Contract (qualify/)", False, res.get("error", "Unknown error"))
    except Exception as e:
        log_result("Qualify Contract (qualify/)", False, str(e))

def test_order_submission_and_monitor():
    try:
        payload = {
            "order_type": "LMT",
            "total_qty": 1,
            "lmt_price": 0.01,
            "esc_pct": 0.01,
            "esc_interval": 10,
            "max_steps": 3,
            "legs": [
                {
                    "symbol": "AAPL",
                    "secType": "STK",
                    "action": "BUY",
                    "ratio": 1
                }
            ]
        }
        
        submit_res = requests.post(f"{WORKER_URL}/submit", json=payload, timeout=10).json()
        order_id = submit_res.get("order_id")
        
        if order_id:
            log_result("Submit Order (submit/)", True, f"OrderID: {order_id}")
            time.sleep(2)
            monitor_res = requests.get(f"{WORKER_URL}/monitor", timeout=5).json()
            
            if order_id in monitor_res:
                internal_status = monitor_res[order_id].get("internal_status")
                log_result("Escalation Monitor (monitor/)", True, f"Status: {internal_status}")
            else:
                log_result("Escalation Monitor (monitor/)", False, "Order not found in monitor")
        else:
            log_result("Submit Order (submit/)", False, f"Server response: {submit_res}")
            
    except Exception as e:
        log_result("Order Submission & Monitor", False, str(e))

def test_cancel_all():
    try:
        res = requests.post(f"{WORKER_URL}/cancel_all", timeout=5).json()
        log_result("Cancel All (cancel_all/)", True, res.get("status", ""))
    except Exception as e:
        log_result("Cancel All (cancel_all/)", False, str(e))

def run_all_tests():
    print("=== Starting Worker Integration Tests ===")
    
    is_connected = test_connection()
    if not is_connected:
        print("\nWorker not connected. Aborting remaining tests.")
        return
        
    test_portfolio()
    test_qualify()
    test_order_submission_and_monitor()
    test_cancel_all()
    
    print("\n" + "="*40)
    print("Test Summary Report:")
    print("="*40)
    for line in REPORT:
        print(line)
    print("="*40)

if __name__ == "__main__":
    run_all_tests()
