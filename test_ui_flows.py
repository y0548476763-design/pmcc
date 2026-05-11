"""
test_ui_flows.py — E2E Integration Test with Valid Contracts
Uses intentionally extreme prices so orders reach IBKR but never fill.
All expiry dates are future dates (valid as of May 2026).
"""
import time
import api_ibkr

# ── Valid future expiry dates (as of May 2026) ────────────────────────────
EXP_NEAR  = "20260619"   # June 19, 2026  (~43 DTE)
EXP_FAR   = "20270115"   # Jan 15, 2027   (~250 DTE)
EXP_LEAPS = "20271217"   # Dec 17, 2027   (~590 DTE, LEAPS)


def print_header(title):
    print(f"\n{'='*55}\nTEST: {title}\n{'='*55}")

def safe_print(msg):
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode('ascii', 'replace').decode('ascii'))

def monitor_until_done(order_id, wait_secs=12):
    print(f"  Monitoring order {order_id}...")
    for i in range(wait_secs):
        res = api_ibkr.get_escalations_status()
        if res.get("ok"):
            for esc in res["escalations"]:
                if esc["order_id"] == order_id:
                    status    = esc.get('status', '')
                    ib_status = esc.get('ib_status', '')
                    safe_print(f"  [{i+1}s] Status: {status} | IBKR: {ib_status}")
                    done_keywords = [
                        "Cancelled", "Failed", "Finished", "Filled",
                        "בוטל", "נכשל", "הסתיימה", "בוצע"
                    ]
                    if any(kw in status or kw in ib_status for kw in done_keywords):
                        print(f"  >> Order reached terminal state at {i+1}s")
                        return
        time.sleep(1)
    print("  >> Monitoring timeout (order still pending — this is expected with extreme prices)")

# ─────────────────────────────────────────────────────────────────────────────

def test_1_single_short_call():
    """
    Simulates: UI 'Open Short Call' on AAPL
    SELL 1x AAPL $230C Jun-2026 @ $50.00 (absurdly high — will be Rejected/Pending by IBKR)
    TP = 30% of $50 = $35
    """
    print_header("Test 1: Single Short Call SELL + TP (AAPL)")
    res = api_ibkr.place_order(
        ticker="AAPL",
        strike=230.0,
        expiry=EXP_NEAR,
        right="C",
        action="SELL",
        qty=1,
        limit_price=50.0,   # Extreme high — will NOT fill
        order_type="LMT",
        tp_pct=30.0          # Worker should auto-place BUY @ $35 after fill
    )
    safe_print(f"  API Response: {res}")
    if res.get("ok"):
        monitor_until_done(res["order_id"], wait_secs=12)
        return True
    else:
        print(f"  FAIL: {res.get('error')}")
        return False


def test_2_roll_short_call():
    """
    Simulates: UI 'Roll Short Call' combo (BUY old AAPL Jun26, SELL new AAPL Jan27)
    Net debit of $2.00 — this is extreme (Jan27 calls cost more), so it WON'T fill.
    """
    print_header("Test 2: Roll Short Call Combo (AAPL Jun26 -> Jan27)")
    legs = [
        # BUY back old short (closing)
        {"strike": 230.0, "expiry": EXP_NEAR,  "right": "C", "action": "BUY",  "ratio": 1, "secType": "OPT"},
        # SELL new short (opening)
        {"strike": 240.0, "expiry": EXP_FAR,   "right": "C", "action": "SELL", "ratio": 1, "secType": "OPT"},
    ]
    res = api_ibkr.place_combo(
        ticker="AAPL",
        legs=legs,
        limit_price=2.00,        # Extreme debit — will NOT fill
        use_market=False,
        escalation_step_pct=1.0,
        escalation_wait_secs=5,
        total_qty=1
    )
    safe_print(f"  API Response: {res}")
    if res.get("ok"):
        monitor_until_done(res["order_id"], wait_secs=12)
        return True
    else:
        print(f"  FAIL: {res.get('error')}")
        return False


def test_3_buy_new_leaps():
    """
    Simulates: UI 'Buy New LEAPS' on MSFT
    BUY 1x MSFT $500C Dec-2027 @ $0.01 (absurdly low — will be Rejected by IBKR)
    """
    print_header("Test 3: Buy New LEAPS (MSFT Dec-2027)")
    legs = [
        {"strike": 500.0, "expiry": EXP_LEAPS, "right": "C", "action": "BUY", "ratio": 1, "secType": "OPT"},
    ]
    res = api_ibkr.place_combo(
        ticker="MSFT",
        legs=legs,
        limit_price=0.01,         # Extremely low — will NOT fill
        use_market=False,
        escalation_step_pct=0.5,
        escalation_wait_secs=5,
        total_qty=1
    )
    safe_print(f"  API Response: {res}")
    if res.get("ok"):
        monitor_until_done(res["order_id"], wait_secs=12)
        return True
    else:
        print(f"  FAIL: {res.get('error')}")
        return False


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 55)
    print("PMCC Worker E2E Integration Test (Safe Mode)")
    print("All prices are extreme — no real fills expected.")
    print("=" * 55)

    # Step 1: Verify connection
    health = api_ibkr.health_check()
    safe_print(f"Health Check: {health}")
    if not health.get("connected"):
        print("\nERROR: Worker is not connected to IBKR. Aborting.")
        exit(1)
    print("Connection OK\n")

    # Step 2: Run tests
    results = {}
    results["Test 1 - Single Short Call"] = test_1_single_short_call()
    time.sleep(2)
    results["Test 2 - Roll Short Call"]   = test_2_roll_short_call()
    time.sleep(2)
    results["Test 3 - Buy New LEAPS"]     = test_3_buy_new_leaps()

    # Step 3: Cancel all pending orders
    print_header("Cleanup: Cancelling all open worker orders")
    api_ibkr.cancel_escalation(0)
    print("  Cancel request sent.")

    # Step 4: Print summary
    print("\n" + "=" * 55)
    print("FINAL SUMMARY")
    print("=" * 55)
    for test_name, passed in results.items():
        status = "PASS (request accepted by worker)" if passed else "FAIL (worker rejected request)"
        print(f"  {test_name}: {status}")
    print("=" * 55)
    print("\nNOTE: 'PASS' means the worker accepted and routed the order to IBKR.")
    print("IBKR may still reject with 'Invalid price' — this is EXPECTED for extreme prices.")
    print("Check the worker terminal for the full IBKR response logs.\n")
