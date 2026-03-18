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
from datetime import datetime, timedelta

# Cache with TTL: {key: (dataframe, timestamp)}
_hist_cache: Dict[str, tuple] = {}
_CACHE_TTL_SECONDS = 1800  # 30 minutes


def get_historical_bars(ticker: str, period: str = "1y",
                        interval: str = "1d") -> pd.DataFrame:
    """
    Fetch OHLCV daily bars via yfinance (free).
    Uses explicit date range for consistency. Caches with 30-min TTL.
    Returns empty DataFrame on failure.
    """
    key = f"{ticker}_{interval}"
    now = time.time()

    # Return cached data if still fresh
    if key in _hist_cache:
        cached_df, cached_at = _hist_cache[key]
        if now - cached_at < _CACHE_TTL_SECONDS:
            return cached_df

    if not YFINANCE_OK:
        return _make_synthetic_bars(ticker)

    try:
        import requests
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        session = requests.Session()
        session.verify = False

        # Use explicit start/end to get a deterministic 1-year window
        end_date   = datetime.utcnow().date()
        start_date = end_date - timedelta(days=400)   # ~1yr + buffer for MA200
        df = yf.download(
            ticker,
            start=str(start_date),
            end=str(end_date),
            interval=interval,
            progress=False,
            auto_adjust=True,
            session=session,
        )
        if df.empty:
            logger.warning(f"[{ticker}] yfinance returned empty dataframe")
            return _make_synthetic_bars(ticker)
        df.index = pd.to_datetime(df.index)
        _hist_cache[key] = (df, now)
        logger.info(f"[{ticker}] Fetched {len(df)} bars ending {df.index[-1].date()} "
                    f"(TTL cache for {_CACHE_TTL_SECONDS//60} min)")
        return df
    except Exception as e:
        logger.warning(f"yfinance error for {ticker}: {e}")
        return _make_synthetic_bars(ticker)


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
        return _synthetic_technicals(ticker)

    close = df["Close"].squeeze()

    if PANDAS_TA_OK:
        try:
            rsi = ta.rsi(close, length=14)
            bbands = ta.bbands(close, length=20, std=2.0)
            ma200 = ta.sma(close, length=200)

            latest_rsi  = float(rsi.iloc[-1]) if rsi is not None else 50.0
            latest_ma200 = float(ma200.iloc[-1]) if ma200 is not None else float(close.mean())
            latest_close = float(close.iloc[-1])

            bb_upper = bb_lower = None
            if bbands is not None and not bbands.empty:
                # pandas_ta column names: BBL_20_2.0, BBM_20_2.0, BBU_20_2.0
                upper_col = [c for c in bbands.columns if c.startswith("BBU")]
                lower_col = [c for c in bbands.columns if c.startswith("BBL")]
                if upper_col:
                    bb_upper = float(bbands[upper_col[0]].iloc[-1])
                if lower_col:
                    bb_lower = float(bbands[lower_col[0]].iloc[-1])

            return {
                "ticker":       ticker,
                "close":        latest_close,
                "rsi":          latest_rsi,
                "ma200":        latest_ma200,
                "bb_upper":     bb_upper or latest_close * 1.05,
                "bb_lower":     bb_lower or latest_close * 0.95,
                "above_ma200":  latest_close > latest_ma200,
                "at_bb_lower":  latest_close <= (bb_lower or (latest_close * 0.95)),
                "at_bb_upper":  latest_close >= (bb_upper or (latest_close * 1.05)),
            }
        except Exception as e:
            logger.warning(f"pandas_ta error for {ticker}: {e}")

    # Fallback manual computation
    return _manual_technicals(close, ticker)


def _manual_technicals(close: pd.Series, ticker: str) -> Dict:
    """Fallback: compute RSI and Bollinger manually with numpy."""
    close = close.dropna()
    if len(close) < 20:
        return _synthetic_technicals(ticker)

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

    # MA200
    ma200 = close.rolling(min(200, len(close))).mean()

    c = float(close.iloc[-1])
    return {
        "ticker":       ticker,
        "close":        c,
        "rsi":          float(rsi.iloc[-1]) if not rsi.empty else 50.0,
        "ma200":        float(ma200.iloc[-1]),
        "bb_upper":     float(bb_upper.iloc[-1]),
        "bb_lower":     float(bb_lower.iloc[-1]),
        "above_ma200":  c > float(ma200.iloc[-1]),
        "at_bb_lower":  c <= float(bb_lower.iloc[-1]),
        "at_bb_upper":  c >= float(bb_upper.iloc[-1]),
    }


def _synthetic_technicals(ticker: str) -> Dict:
    """Return plausible synthetic technicals for demo mode."""
    demo = {
        "NVDA": {"close": 853.0, "rsi": 31.0, "ma200": 780.0,
                 "bb_upper": 920.0, "bb_lower": 790.0},
        "AAPL": {"close": 187.4, "rsi": 54.0, "ma200": 175.0,
                 "bb_upper": 200.0, "bb_lower": 172.0},
        "TSLA": {"close": 246.8, "rsi": 68.0, "ma200": 210.0,
                 "bb_upper": 265.0, "bb_lower": 225.0},
    }
    d = demo.get(ticker, {"close": 200.0, "rsi": 50.0, "ma200": 190.0,
                           "bb_upper": 215.0, "bb_lower": 185.0})
    c = d["close"]
    return {
        "ticker":      ticker,
        "close":       c,
        "rsi":         d["rsi"],
        "ma200":       d["ma200"],
        "bb_upper":    d["bb_upper"],
        "bb_lower":    d["bb_lower"],
        "above_ma200": c > d["ma200"],
        "at_bb_lower": c <= d["bb_lower"],
        "at_bb_upper": c >= d["bb_upper"],
    }


def _make_synthetic_bars(ticker: str) -> pd.DataFrame:
    """Minimal synthetic price series for fallback."""
    import pandas as pd
    dates = pd.date_range(end=pd.Timestamp.today(), periods=250, freq="B")
    base = {"NVDA": 753, "AAPL": 175, "TSLA": 220}.get(ticker, 180)
    np.random.seed(hash(ticker) % 2**31)
    prices = base + np.cumsum(np.random.randn(250) * 2)
    df = pd.DataFrame({
        "Open": prices * 0.999,
        "High": prices * 1.005,
        "Low":  prices * 0.994,
        "Close": prices,
        "Volume": np.random.randint(1_000_000, 50_000_000, 250),
    }, index=dates)
    return df


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
            session.verify = False

            t = yf.Ticker(ticker, session=session)
            info = t.fast_info
            price = info.last_price or info.previous_close or 0.0
            return {"ticker": ticker, "last": price, "bid": 0.0, "ask": 0.0,
                    "source": "yfinance"}
        except Exception:
            pass

    # Final fallback
    demo = {"NVDA": 853.0, "AAPL": 187.4, "TSLA": 246.8, "SPY": 520.0}
    return {"ticker": ticker, "last": demo.get(ticker, 200.0),
            "bid": 0.0, "ask": 0.0, "source": "demo"}
