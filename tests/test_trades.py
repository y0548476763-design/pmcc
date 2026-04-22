import sys
from ib_insync import *
import json

def test_modify():
    ib = IB()
    try:
        # Default paper trading port
        ib.connect('127.0.0.1', 7497, clientId=33)
    except Exception as e:
        print("Could not connect:", e)
        return

    res = []
    for t in ib.trades():
        res.append({
            "orderId": t.order.orderId,
            "status": t.orderStatus.status,
            "action": t.order.action,
            "sym": t.contract.symbol,
            "lmtPrice": getattr(t.order, "lmtPrice", None)
        })

    with open("diagnostic_trades.json", "w") as f:
        json.dump(res, f, indent=2)

    ib.disconnect()

if __name__ == "__main__":
    test_modify()
