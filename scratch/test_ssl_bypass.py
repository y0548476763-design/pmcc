import yfinance as yf
import ssl
import logging

# Global SSL bypass
ssl._create_default_https_context = ssl._create_unverified_context

def test_yf():
    try:
        t = yf.Ticker("GOOGL")
        print("Options:", len(t.options))
    except Exception as e:
        print("Error:", e)

if __name__ == "__main__":
    test_yf()
