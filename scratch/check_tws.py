import asyncio
from ib_insync import IB
import config

async def test_conn():
    ib = IB()
    print(f"Testing connection to 127.0.0.1:{config.TWS_PORT_LIVE} (LIVE)...")
    try:
        await ib.connectAsync('127.0.0.1', config.TWS_PORT_LIVE, clientId=999, timeout=5)
        print("✅ Connected to LIVE!")
        ib.disconnect()
    except Exception as e:
        print(f"❌ LIVE failed: {e}")
        print(f"Testing connection to 127.0.0.1:{config.TWS_PORT_DEMO} (DEMO)...")
        try:
            await ib.connectAsync('127.0.0.1', config.TWS_PORT_DEMO, clientId=999, timeout=5)
            print("✅ Connected to DEMO!")
            ib.disconnect()
        except Exception as e2:
            print(f"❌ DEMO failed: {e2}")

if __name__ == "__main__":
    asyncio.run(test_conn())
