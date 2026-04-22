import sys, time
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

sys.path.append('c:/Users/User/Desktop/pmcc1')
from tws_client import TWSClient

print('Connecting...')
t = TWSClient()
if not t.connect('DEMO'):
    t.connect('LIVE')

if not t.connected:
    print('FAIL')
    sys.exit(1)

pos = t.get_positions()
leaps = [p for p in pos if p.get('type') == 'LEAPS']
if not leaps:
    print('No LEAPS')
    sys.exit(0)

lp = leaps[0]
print(f"Rolling {lp['ticker']} from {lp['strike']}/{lp['expiry']}")

tgt_list = t.get_leaps_options(lp['ticker'], min_dte=500, target_delta=0.80)
if not tgt_list:
    print('No targets')
    sys.exit(0)

tgt = tgt_list[0]
print(f"To {tgt['strike']}/{tgt['expiry']}")

# Calculate AGGRESSIVE limit (Ask of target - Bid of current, meaning we pay the most possible)
target_ask = float(tgt['ask']) if float(tgt.get('ask',0)) > 0 else float(tgt['mid']) * 1.05
lp_bid = float(lp.get('current_price', 0)) * 0.95 # Assume bid is lower
aggressive_limit = max(0.01, round(target_ask - lp_bid, 2)) + 0.50 # Overpay by $50 to FORCE execution

print(f"Aggressive LMT price (forcing fill): ${aggressive_limit}")

legs = [
    {'strike': lp['strike'], 'expiry': lp['expiry'], 'right': 'C', 'action': 'SELL'},
    {'strike': tgt['strike'], 'expiry': tgt['expiry'], 'right': 'C', 'action': 'BUY'}
]

oid = t.place_combo_order(lp['ticker'], legs, 'BUY', qty=abs(int(lp['qty'])), limit_price=aggressive_limit)
print(f'Placed order ID {oid}')

for i in range(15):
    t.ib.sleep(1)
    trades = [tr for tr in t.ib.trades() if tr.order.orderId == oid]
    if not trades: continue
    trade = trades[0]
    status = trade.orderStatus.status
    print(f'[{i+1}s] Status: {status} (Filled: {trade.orderStatus.filled})')
    if status == 'Filled':
        print(f'SUCCESS! Executed at ${trade.orderStatus.avgFillPrice}')
        break
t.disconnect()
