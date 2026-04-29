import asyncio
import ib_insync as ibi
import logging
import math

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("PriceTestV2")

async def test_prices():
    ib = ibi.IB()
    try:
        await ib.connectAsync('127.0.0.1', 4002, clientId=100)
        logger.info("Connected to IBKR Demo")
        
        # Define a GOOGL option (from user's recent attempt)
        # GOOGL 2026-05-04 375 Call (conId=875357896)
        contract = ibi.Option('GOOGL', '20260504', 375, 'C', 'SMART')
        await ib.qualifyContractsAsync(contract)
        
        types_to_test = [3, 4, 1, 2] # Delayed, Delayed-Frozen, RealTime, Frozen
        
        for dt in types_to_test:
            logger.info(f"--- Testing Market Data Type: {dt} ---")
            ib.reqMarketDataType(dt)
            
            # Request ticker and wait
            tickers = await ib.reqTickersAsync(contract)
            t = tickers[0]
            
            logger.info(f"Initial (Type {dt}): Bid={t.bid}, Ask={t.ask}, Last={t.last}, Close={t.close}")
            
            # Wait 4 seconds to see if data flows
            for i in range(4):
                await asyncio.sleep(1)
                logger.info(f"Wait {i+1}s (Type {dt}): Bid={t.bid}, Ask={t.ask}, Last={t.last}")
                if not math.isnan(t.bid) and t.bid > 0:
                    logger.info("Data FOUND!")
                    break
            
            if not math.isnan(t.bid) and t.bid > 0:
                break

    except Exception as e:
        logger.error(f"Error during test: {e}")
    finally:
        ib.disconnect()

if __name__ == "__main__":
    asyncio.run(test_prices())
