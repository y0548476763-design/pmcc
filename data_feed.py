"""
data_feed.py — Hybrid data sourcing: TWS real-time + yfinance historical
"""
import logging
from typing import Dict, Optional, Tuple
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

try:
    import yfinance as yf
    YFINANCE_OK = True
except ImportError:
    YFINANCE_OK = False
    logger.warning("yfinance not installed")

try:
    import pandas_ta as ta
    PANDAS_TA_OK = True
except ImportError:
    PANDAS_TA_OK = False
    logger.warning("pandas_ta not installed")


import time
import random
from datetime import datetime, timedelta

# Cache with TTL: {key: (dataframe, timestamp)}
_hist_cache: Dict[str, tuple] = {}
_CACHE_TTL_SECONDS = 14400  # 4 hours — reduce Yahoo rate-limit pressure


def get_historical_bars(ticker: str, period: str = "1y",
                        interval: str = "1d") -> pd.DataFrame:
    """
    Fetch OHLCV daily bars using direct Yahoo Finance full JSON API (bypassing yfinance library bugs).
    Caches with 4-hour TTL.
    """
    key = f"{ticker}_{interval}"
    now = time.time()

    # Return cached data if still fresh
    if key in _hist_cache:
        cached_df, cached_at = _hist_cache[key]
        if now - cached_at < _CACHE_TTL_SECONDS:
            return cached_df

    import requests
    import urllib3
    urllib3.disable_warnings((urllib3.exceptions.InsecureRequestWarning))
    
    # Direct Yahoo endpoint (very fast, rarely blocked if user-agent is randomized/modern)
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval={interval}&range=2y"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/json",
    }

    last_err = None
    for attempt in range(3):
        try:
            if attempt > 0:
                wait_sec = (attempt * 2) + random.uniform(1, 3)
                logger.info(f"[{ticker}] JSON API Retry {attempt}/3 — waiting {wait_sec:.1f}s...")
                time.sleep(wait_sec)

            r = requests.get(url, headers=headers, timeout=10)
            
            if r.status_code != 200:
                raise ValueError(f"HTTP {r.status_code}: {r.text[:100]}")
                
            data = r.json()
            res = data["chart"]["result"]
            if not res:
                raise ValueError("JSON 'result' is null")
                
            timestamps = res[0]["timestamp"]
            quote = res[0]["indicators"]["quote"][0]
            
            # Construct DataFrame exactly like yfinance
            df = pd.DataFrame({
                "Open": quote.get("open", []),
                "High": quote.get("high", []),
                "Low": quote.get("low", []),
                "Close": quote.get("close", []),
                "Volume": quote.get("volume", []),
            })
            
            # Convert unix timestamps to UTC datetimes
            df.index = pd.to_datetime(timestamps, unit="s")
            df = df.dropna(subset=["Close"]) # drop missing days
            
            if df.empty:
                raise ValueError("No valid Close prices found in JSON")
                
            _hist_cache[key] = (df, now)
            logger.info(f"[{ticker}] Fetched {len(df)} bars via direct JSON (attempt {attempt+1})")
            return df

        except Exception as e:
            last_err = e
            logger.warning(f"[{ticker}] Attempt {attempt+1} failed: {e}")

    raise ValueError(f"Direct Yahoo fetch failed after 3 attempts: {last_err}")


def clear_data_cache() -> None:
    """Force-clear the price cache so next analysis fetches fresh data."""
    _hist_cache.clear()
    logger.info("Data cache cleared — next analysis will fetch fresh data")


def compute_technicals(ticker: str) -> Dict:
    """
    Compute RSI(14), Bollinger Bands(20,2), MA200 using pandas_ta.
    Returns dict with scalar values for the latest bar.
    """
    df = get_historical_bars(ticker)
    if df.empty:
        raise ValueError(f"No historical data returned for {ticker}.")

    close = df["Close"].squeeze()

    if PANDAS_TA_OK:
        try:
            rsi = ta.rsi(close, length=14)
            bbands = ta.bbands(close, length=20, std=2.0)
            # MA200 & 150
            ma200 = ta.sma(close, length=200)
            ma150 = ta.sma(close, length=150)

            latest_rsi  = float(rsi.iloc[-1]) if rsi is not None else 50.0
            latest_ma200 = float(ma200.iloc[-1]) if ma200 is not None else float(close.mean())
            latest_ma150 = float(ma150.iloc[-1]) if ma150 is not None else float(close.mean())
            latest_close = float(close.iloc[-1])

            # Simple Breakout on 150-SMA (from backtests):
            # Price crossed above SMA 150
            prev_close = float(close.iloc[-2]) if len(close) > 1 else latest_close
            prev_ma150 = float(ma150.iloc[-2]) if ma150 is not None and len(ma150) > 1 else latest_ma150
            cross_above_150 = (prev_close <= prev_ma150) and (latest_close > latest_ma150)

            bb_upper = bb_lower = None
            if bbands is not None and not bbands.empty:
                upper_col = [c for c in bbands.columns if c.startswith("BBU")]
                lower_col = [c for c in bbands.columns if c.startswith("BBL")]
                if upper_col:
                    bb_upper = float(bbands[upper_col[0]].iloc[-1])
                if lower_col:
                    bb_lower = float(bbands[lower_col[0]].iloc[-1])

            # HV30: 30-day annualised historical volatility
            log_ret = np.log(close / close.shift(1))
            hv30_series = log_ret.rolling(30).std() * np.sqrt(252)
            hv30_val = float(hv30_series.iloc[-1]) if not hv30_series.empty else 0.25

            # 52-week high
            high52_val = float(close.rolling(min(252, len(close))).max().iloc[-1])

            return {
                "ticker":           ticker,
                "close":            latest_close,
                "rsi":              latest_rsi,
                "ma200":            latest_ma200,
                "ma150":            latest_ma150,
                "bb_upper":         bb_upper or latest_close * 1.05,
                "bb_lower":         bb_lower or latest_close * 0.95,
                "above_ma200":      latest_close > latest_ma200,
                "above_ma150":      latest_close > latest_ma150,
                "cross_above_150":  cross_above_150,
                "at_bb_lower":      latest_close <= (bb_lower or (latest_close * 0.95)),
                "at_bb_upper":      latest_close >= (bb_upper or (latest_close * 1.05)),
                "hv30":             hv30_val,
                "high52":           high52_val,
            }
        except Exception as e:
            logger.warning(f"pandas_ta error for {ticker}: {e}")

    # Fallback manual computation
    return _manual_technicals(close, ticker)


def _manual_technicals(close: pd.Series, ticker: str) -> Dict:
    """Fallback: compute RSI and Bollinger manually with numpy."""
    close = close.dropna()
    if len(close) < 20:
        raise ValueError(f"Not enough data points ({len(close)}) for {ticker}.")

    # RSI
    delta = close.diff()
    gain  = delta.clip(lower=0)
    loss  = (-delta).clip(lower=0)
    avg_g = gain.rolling(14).mean()
    avg_l = loss.rolling(14).mean()
    rs    = avg_g / avg_l.replace(0, np.nan)
    rsi   = 100 - (100 / (1 + rs))

    # Bollinger
    sma20    = close.rolling(20).mean()
    std20    = close.rolling(20).std()
    bb_upper = sma20 + 2 * std20
    bb_lower = sma20 - 2 * std20

    # MA200 & 150
    ma200 = close.rolling(min(200, len(close))).mean()
    ma150 = close.rolling(min(150, len(close))).mean()

    # HV30
    log_ret = close.diff()
    hv30_s  = (np.log(close / close.shift(1))).rolling(30).std() * np.sqrt(252)
    hv30_v  = float(hv30_s.iloc[-1]) if not hv30_s.empty else 0.25

    # 52-week high
    high52_v = float(close.rolling(min(252, len(close))).max().iloc[-1])

    c = float(close.iloc[-1])
    m200 = float(ma200.iloc[-1])
    m150 = float(ma150.iloc[-1])
    
    # CrossAbove
    prev_c = float(close.iloc[-2]) if len(close) > 1 else c
    prev_m150 = float(ma150.iloc[-2]) if len(ma150) > 1 else m150
    cross_above_150 = (prev_c <= prev_m150) and (c > m150)

    return {
        "ticker":           ticker,
        "close":            c,
        "rsi":              float(rsi.iloc[-1]) if not rsi.empty else 50.0,
        "ma200":            m200,
        "ma150":            m150,
        "bb_upper":         float(bb_upper.iloc[-1]),
        "bb_lower":         float(bb_lower.iloc[-1]),
        "above_ma200":      c > m200,
        "above_ma150":      c > m150,
        "cross_above_150":  cross_above_150,
        "at_bb_lower":      c <= float(bb_lower.iloc[-1]),
        "at_bb_upper":      c >= float(bb_upper.iloc[-1]),
        "hv30":             hv30_v,
        "high52":           high52_v,
    }


# Synthetic data generators removed per strict safety protocols.


def get_realtime_quote(ticker: str, tws=None) -> Dict:
    """
    Get latest price. Uses TWS if connected, yfinance otherwise.
    """
    if tws and tws.connected:
        try:
            from ib_insync import Stock
            contract = Stock(ticker, "SMART", "USD")
            tws.ib.qualifyContracts(contract)
            [td] = tws.ib.reqTickers(contract)
            return {
                "ticker": ticker,
                "last":   float(td.last),
                "bid":    float(td.bid),
                "ask":    float(td.ask),
                "source": "TWS",
            }
        except Exception:
            pass

    if YFINANCE_OK:
        try:
            import requests
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            session = requests.Session()
            session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"})
            session.verify = False

            t = yf.Ticker(ticker, session=session)
            info = t.fast_info
            price = info.last_price or info.previous_close or 0.0
            return {"ticker": ticker, "last": price, "bid": 0.0, "ask": 0.0,
                    "source": "yfinance"}
        except Exception:
            pass

    # Final fallback
    raise ValueError(f"Could not fetch real-time quote for {ticker}")
