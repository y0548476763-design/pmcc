"""
End-to-end LEAPS roll test: 
1. Connect to TWS
2. Get current MSFT or GOOGL LEAPS position
3. Find a 650+ DTE roll target
4. Submit the combo order
5. Monitor its status via open_orders for 30 seconds
"""
import sys, time
# Force UTF-8 output
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

sys.path.append('c:/Users/User/Desktop/pmcc1')
from tws_client import TWSClient
from order_manager import get_manager

print("Step 1: Connecting to TWS...")
t = TWSClient()
success = t.connect('DEMO')
if not success:
    success = t.connect('LIVE')
if not success:
    print("FAIL: Could not connect to TWS. Is IB Gateway running?")
    sys.exit(1)
print(f"Connected! Account: {t.account_id}")

om = get_manager()
om.set_tws(t)

print("\nStep 2: Fetching positions...")
pos = t.get_positions()
leaps = [p for p in pos if p.get('type') == 'LEAPS']
if not leaps:
    print("FAIL: No LEAPS found in account.")
    sys.exit(1)

lp = leaps[0]
print(f"Rolling: {lp['ticker']} ${lp['strike']} {lp['expiry']} (qty={lp['qty']}, current_price=${lp['current_price']})")

print("\nStep 3: Searching 650 DTE roll targets...")
targets = t.get_leaps_options(lp['ticker'], min_dte=650, target_delta=0.80)
if not targets:
    print("FAIL: No targets found.")
    sys.exit(1)

tgt = targets[0]
print(f"Target: {tgt['ticker']} ${tgt['strike']} {tgt['expiry']} DTE={tgt['dte']} Delta={tgt['delta']} Mid=${tgt['mid']}")
assert tgt['dte'] >= 650, f"FAIL: Target DTE {tgt['dte']} < 650!"
print(f"PASS: Target DTE {tgt['dte']} >= 650")

net_limit = max(0.01, round(float(tgt['mid']) - float(lp['current_price']), 2))
legs = [
    {'strike': lp['strike'], 'expiry': lp['expiry'], 'right': 'C', 'action': 'SELL'},
    {'strike': tgt['strike'], 'expiry': tgt['expiry'], 'right': 'C', 'action': 'BUY'},
]
print(f"\nStep 4: Submitting COMBO order. Net limit = ${net_limit}")
oid = om.submit_order(
    ticker=lp['ticker'], right='C',
    strike=float(tgt['strike']), expiry=str(tgt['expiry']),
    action='BUY', qty=abs(int(lp['qty'])), limit_price=net_limit,
    escalation_step_pct=0.5, escalation_wait_mins=1,
    is_combo=True, legs=legs,
)
print(f"Internal Order ID: {oid}")

print("\nStep 5: Monitoring open orders (30 seconds)...")
found = False
for i in range(30):
    open_orders = t.get_open_orders()
    bag_orders = [o for o in open_orders if o.get('sec_type') == 'BAG']
    lmt_orders = [o for o in open_orders if o.get('ticker') == lp['ticker']]
    
    if bag_orders:
        print(f"[{i+1}s] SUCCESS: FOUND COMBO/BAG ORDER in TWS: {bag_orders[0]}")
        found = True
        break
    elif lmt_orders:
        print(f"[{i+1}s] Found order (may be LMT): {lmt_orders[0]}")
    else:
        print(f"[{i+1}s] No orders visible yet ({len(open_orders)} total open)...")
    time.sleep(1)

t.ib.disconnect()

if found:
    print("\nSUCCESS: Combo order confirmed in TWS!")
else:
    print("\nWARNING: Order not confirmed as BAG in 30s (may still be pending/delayed data)")
