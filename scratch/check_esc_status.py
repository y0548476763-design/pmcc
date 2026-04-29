import asyncio
import ib_insync as ibi

async def check_orders():
    ib = ibi.IB()
    try:
        await ib.connectAsync('127.0.0.1', 4002, clientId=98)
        ib.reqAllOpenOrders()
        trades = ib.trades()
        print(f"Total trades visible: {len(trades)}")
        for t in trades:
            if t.contract.secType == 'BAG':
                print(f"ORDER ID: {t.order.orderId}")
                print(f"LMT PRICE: {t.order.lmtPrice}")
                print(f"STATUS: {t.orderStatus.status}")
                print(f"FILLED QTY: {t.orderStatus.filled}")
                print(f"AVG FILL PRICE: {t.orderStatus.avgFillPrice}")
                print("-" * 20)
        ib.disconnect()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(check_orders())
