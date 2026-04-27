import asyncio
from ib_insync import IB

async def run():
    ib = IB()
    try:
        print("Connecting...")
        await ib.connectAsync('127.0.0.1', 4002, clientId=99)
        print("Connected!")
        print("Account:", ib.managedAccounts())
    except Exception as e:
        print("Error:", e)
    finally:
        ib.disconnect()

if __name__ == "__main__":
    asyncio.run(run())
