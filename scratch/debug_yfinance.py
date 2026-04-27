import yfinance as yf
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_fetch(symbol):
    try:
        t = yf.Ticker(symbol)
        print(f"Ticker: {symbol}")
        print(f"Options available: {len(t.options) if t.options else 0}")
        if not t.options:
            return None
        
        nearest_expiry = t.options[0]
        print(f"Nearest Expiry: {nearest_expiry}")
        chain = t.option_chain(nearest_expiry)
        
        # Try different ways to get spot
        try:
            spot = t.fast_info.last_price
            print(f"Spot (fast_info): {spot}")
        except Exception as e:
            print(f"fast_info failed: {e}")
            spot = None
            
        if not spot:
            hist = t.history(period="1d")
            if not hist.empty:
                spot = hist['Close'].iloc[-1]
                print(f"Spot (history): {spot}")
        
        if not spot:
            print("Failed to get spot price")
            return None
            
        # ATM
        idx = (chain.calls['strike'] - spot).abs().idxmin()
        atm_strike = chain.calls.loc[idx, 'strike']
        print(f"ATM Strike: {atm_strike}")
        
        c_ask = chain.calls.loc[idx, 'ask']
        # Find put
        p_idx = (chain.puts['strike'] - atm_strike).abs().idxmin()
        p_ask = chain.puts.loc[p_idx, 'ask']
        
        print(f"Call Ask: {c_ask}, Put Ask: {p_ask}")
        straddle = c_ask + p_ask
        print(f"Straddle: {straddle}")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_fetch("GOOGL")
