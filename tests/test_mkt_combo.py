import sys, time
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
tgt_list = t.get_leaps_options(lp['ticker'], min_dte=500, target_delta=0.80)
if not tgt_list:
    print('No targets')
    sys.exit(0)

tgt = tgt_list[0]
print(f"Rolling {lp['ticker']} from {lp['strike']}/{lp['expiry']} to {tgt['strike']}/{tgt['expiry']}")

from ib_insync import Option, ComboLeg, Bag, MarketOrder

c_old = Option(symbol=lp['ticker'], lastTradeDateOrContractMonth=lp['expiry'].replace('-',''), strike=lp['strike'], right='C', exchange='SMART', currency='USD', multiplier='100')
c_new = Option(symbol=tgt['ticker'], lastTradeDateOrContractMonth=tgt['expiry'].replace('-',''), strike=tgt['strike'], right='C', exchange='SMART', currency='USD', multiplier='100')
t.ib.qualifyContracts(c_old, c_new)

leg_sell = ComboLeg(conId=c_old.conId, ratio=1, action='SELL', exchange='SMART')
leg_buy = ComboLeg(conId=c_new.conId, ratio=1, action='BUY', exchange='SMART')
bag = Bag(symbol=lp['ticker'], currency='USD', exchange='SMART', comboLegs=[leg_sell, leg_buy])

order = MarketOrder('BUY', abs(lp['qty']))
print('Placing MKT order for Combo...')
trade = t.ib.placeOrder(bag, order)

for i in range(15):
    t.ib.sleep(1)
    status = trade.orderStatus.status
    print(f"[{i+1}s] Order Status: {status}")
    if status == 'Filled':
        print(f"SUCCESS: Combo Executed! Fill Price: {trade.orderStatus.avgFillPrice}")
        break
    if status in ('Cancelled', 'Inactive'):
        print(f"FAIL: Order {status}")
        break

t.disconnect()
