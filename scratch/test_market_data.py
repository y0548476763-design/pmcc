import asyncio
import ib_insync as ibi
import math
import logging

# Setup basic logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("DataTest")

async def test_data():
    ib = ibi.IB()
    port = 4002 # Demo port
    
    print(f"Connecting to IBKR on port {port}...")
    try:
        await ib.connectAsync('127.0.0.1', port, clientId=99)
    except Exception as e:
        print(f"FAILED to connect: {e}")
        return

    # 1. Define a liquid contract (e.g. GOOGL near-money call)
    # Using a known ticker from the user's screenshots
    contract = ibi.Option('GOOGL', '20260504', 385, 'C', 'SMART', currency='USD')
    print(f"Testing contract: {contract}")

    await ib.qualifyContractsAsync(contract)
    print(f"Qualified Contract: conId={contract.conId}")

    # 2. Test different market data types
    # Type 1: Live (Requires subscription)
    # Type 2: Frozen (Requires subscription, shows last price when closed)
    # Type 3: Delayed (Available for many users for free with 15min delay)
    # Type 4: Delayed-Frozen (Delayed price when closed)
    
    for dtype in [1, 3, 2, 4]:
        name = {1: "LIVE", 2: "FROZEN", 3: "DELAYED", 4: "DELAYED-FROZEN"}[dtype]
        print(f"\n--- Testing Market Data Type {dtype} ({name}) ---")
        
        ib.reqMarketDataType(dtype)
        
        # Request ticker and wait for update
        [ticker] = await ib.reqTickersAsync(contract)
        
        # Wait a bit more just in case
        await asyncio.sleep(2)
        
        bid = ticker.bid
        ask = ticker.ask
        last = ticker.last
        close = ticker.close
        
        print(f"  BID:  {bid}")
        print(f"  ASK:  {ask}")
        print(f"  LAST: {last}")
        print(f"  CLOSE: {close}")
        
        if not math.isnan(bid) and bid > 0:
            print(f"  SUCCESS: Got valid BID/ASK using type {name}")
        else:
            print(f"  FAILED: No valid BID/ASK using type {name}")

    ib.disconnect()
    print("\nTest complete.")

if __name__ == "__main__":
    asyncio.run(test_data())
