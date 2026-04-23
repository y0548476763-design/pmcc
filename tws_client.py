"""
tws_client.py — Async TWS connector using ib_insync (dual-profile: Demo / Real)
"""
import asyncio
import logging
from typing import List, Dict, Optional, Callable
from datetime import datetime
import subprocess
import os
import requests
import streamlit as st

logger = logging.getLogger(__name__)

# ib_insync requires TWS/IB Gateway running; graceful import fallback for demo mode
try:
    from ib_insync import (
        IB, Contract, Option, Stock, LimitOrder, MarketOrder,
        PortfolioItem, Position, Order, Trade, ComboLeg, Bag
    )
    IB_AVAILABLE = True
except ImportError:
    IB_AVAILABLE = False
    logger.warning("ib_insync not installed – running in demo-only mode")

import config


class TWSTrade:
    """Simple dataclass mirroring ib_insync Trade for type safety."""
    def __init__(self, order_id: int, ticker: str, action: str,
                 qty: int, limit_price: float, status: str = "Submitted"):
        self.order_id = order_id
        self.ticker = ticker
        self.action = action
        self.qty = qty
        self.limit_price = limit_price
        self.status = status
        self.submitted_at = datetime.utcnow()


class TWSClient:
    """
    Manages connection to Interactive Brokers TWS / IB Gateway.
    Falls back to demo synthetic data when not connected.
    """

    def __init__(self):
        self.ib: Optional["IB"] = None
        self.connected: bool = False
        self.mode: str = "DEMO"          # "DEMO" or "REAL"
        self.account_id: str = ""
        self.cash_balance: float = 0.0
        self.net_liquidation: float = 0.0
        self._log_callback: Optional[Callable[[str, str], None]] = None

    # ─── Public API ──────────────────────────────────────────────────────────

    def set_log_callback(self, fn: Callable[[str, str], None]) -> None:
        """Register a function(level, message) for Machine Thinking Console."""
        self._log_callback = fn

    def _log(self, level: str, msg: str) -> None:
        logger.info(msg)
        if self._log_callback:
            self._log_callback(level, msg)

    def connect(self, mode: str = "DEMO", host: str = "127.0.0.1", port: int = None, client_id: int = None, timeout: int = 3) -> bool:
        """Try to connect to TWS. Returns True if successful."""
        if not IB_AVAILABLE:
            self._log("WARN", "⚠️ ספריית ib_insync לא מותקנת. המערכת תישאר במצב DEMO בלבד.")
            return False

        if self.connected and self.mode == mode and self.ib and self.ib.isConnected():
            return True

        if self.ib is not None:
            try: self.ib.disconnect()
            except: pass
            self.ib = None
            self.connected = False

        self.mode = mode
        port = port or (config.TWS_PORT_DEMO if mode == "DEMO" else config.TWS_PORT_LIVE)
        host = host or (config.REMOTE_TWS_HOST if config.REMOTE_TWS_HOST else config.TWS_HOST)
        cid  = client_id or config.TWS_CLIENT_ID

        # For auto-connect, we only try once and with a short timeout to prevent UI hang
        try:
            self.ib = IB()
            self.ib.connect(host, port, clientId=cid, timeout=timeout)
            self.connected = True
            self.ib.reqMarketDataType(2) # Enable frozen data
            self.ib.reqAllOpenOrders()
            self.ib.sleep(0.2)
            self._refresh_account()
            self._log("INFO", f"✅ חיבור הוקם: {mode} @ {host}:{port}")
            return True
        except Exception as e:
            self._log("WARN", f"חיבור ל-{mode} נכשל: {e}")
        
        self.connected = False
        return False

    async def connectAsync(self, mode: str = "DEMO", host: str = "127.0.0.1", port: int = None, client_id: int = None, timeout: int = 3) -> bool:
        """Async version of connect for loop-safe use."""
        if not IB_AVAILABLE: return False
        if self.connected and self.ib and self.ib.isConnected() and self.mode == mode:
            return True
        
        if self.ib and self.ib.isConnected():
            try: self.ib.disconnect()
            except: pass
        
        if self.ib is None:
            self.ib = IB()
        
        self.mode = mode
        port = port or (config.TWS_PORT_DEMO if mode == "DEMO" else config.TWS_PORT_LIVE)
        host = host or (config.REMOTE_TWS_HOST if config.REMOTE_TWS_HOST else config.TWS_HOST)
        cid  = client_id or config.TWS_CLIENT_ID

        try:
            # connectAsync will use the current loop
            await self.ib.connectAsync(host, port, clientId=cid, timeout=timeout)
            self.connected = True
            self.ib.reqMarketDataType(2) # Enable frozen data
            self.ib.reqAllOpenOrders()
            await asyncio.sleep(0.2)
            self._refresh_account()
            self._log("INFO", f"✅ (Async) חיבור הוקם: {mode} @ {host}:{port}")
            return True
        except Exception as e:
            self._log("WARN", f"חיבור (Async) ל-{mode} נכשל: {e}")
            self.connected = False
            return False

    def disconnect(self) -> None:
        if self.ib and self.connected:
            self.ib.disconnect()
        self.connected = False
        self._log("INFO", "🔌 נותק מ-TWS.")

    def _refresh_account(self) -> None:
        if not self.connected or not self.ib: return
        try:
            accounts = self.ib.managedAccounts()
            if accounts: self.account_id = accounts[0]
            vals = self.ib.accountValues(self.account_id)
            for v in vals:
                if v.tag == "TotalCashValue" and v.currency == "USD": self.cash_balance = float(v.value)
                if v.tag == "NetLiquidation" and v.currency == "USD": self.net_liquidation = float(v.value)
        except Exception as e:
            self._log("WARN", f"Account refresh error: {e}")

    def get_positions(self) -> List[Dict]:
        if not self.connected or not self.ib: return []
        positions = []
        try:
            for pos in self.ib.portfolio():
                c = pos.contract
                qty = int(pos.position)
                if qty == 0: continue

                if c.secType == "OPT":
                    raw_exp = c.lastTradeDateOrContractMonth
                    try:
                        # Handle both YYYYMMDD and YYYY-MM-DD
                        clean_exp = str(raw_exp).replace("-", "").replace("/", "")
                        exp = datetime.strptime(clean_exp, "%Y%m%d")
                        dte = (exp.date() - datetime.utcnow().date()).days
                    except: 
                        dte = 0
                    
                    opt_type = "LEAPS" if (dte > 270 and qty > 0) else ("SHORT_CALL" if qty < 0 else "OTHER")
                    
                    positions.append({
                        "conId": c.conId, "ticker": c.symbol, "type": opt_type,
                        "strike": float(c.strike), "expiry": raw_exp,
                        "qty": qty, "dte": dte, "delta": 0.0,
                        "cost_basis": float(pos.averageCost), "current_price": float(pos.marketPrice),
                        "premium_received": 0.0, "underlying_price": float(pos.marketValue),
                    })
                elif c.secType in ("STK", "ETF"):
                    positions.append({
                        "conId": c.conId, "ticker": c.symbol, "type": "STOCK",
                        "strike": 0.0, "expiry": "—", "qty": qty, "dte": 9999, "delta": 1.0,
                        "cost_basis": float(pos.averageCost), "current_price": float(pos.marketPrice),
                        "premium_received": 0.0, "underlying_price": float(pos.marketValue),
                    })
        except Exception as e:
            self._log("WARN", f"get_positions error: {e}")
        return positions

    def get_option_chain(self, ticker: str, right: str = "C",
                          min_dte: int = 14, max_dte: int = 60,
                          target_delta: float = 0.30,
                          n_strikes: int = 6) -> List[Dict]:
        try:
            import yfinance as yf
            from datetime import datetime as dt
            from dateutil.parser import parse
            stock = yf.Ticker(ticker)
            expiries = stock.options
            if not expiries: return []
            today = dt.today()
            valid = []
            for e in expiries:
                try:
                    dte = (parse(e) - today).days
                    if min_dte <= dte <= max_dte: valid.append((e, dte))
                except: continue
            if not valid: return []
            valid.sort(key=lambda x: abs(x[1] - 45))
            target_expiry, dte = valid[0]
            chain = stock.option_chain(target_expiry)
            calls_or_puts = chain.calls if right.upper() == "C" else chain.puts
            if calls_or_puts.empty: return []
            underlying = float(stock.fast_info.last_price or 100.0)
            results = []
            for idx, row in calls_or_puts.iterrows():
                strike = float(row['strike'])
                mid = (float(row.get('bid',0)) + float(row.get('ask',0)))/2 or float(row.get('lastPrice',0))
                moneyness = strike / underlying if underlying > 0 else 1.0
                delta = 1.0 - (moneyness-0.8)*2.5 if right.upper()=="C" else (moneyness-0.8)*2.5
                delta = max(0.01, min(0.99, delta))
                results.append({
                    "ticker": ticker, "strike": strike, "expiry": target_expiry, "right": right.upper(),
                    "delta": round(delta, 3), "mid": round(mid, 2), "dte": dte
                })
            results.sort(key=lambda x: abs(x["delta"] - target_delta))
            return results[:n_strikes]
        except Exception as e:
            self._log("WARN", f"get_option_chain error: {e}")
            return []

    def get_leaps_options(self, ticker: str, min_dte: int = 540,
                          target_delta: float = 0.80,
                          n_options: int = 5) -> List[Dict]:
        self._log("INFO", f"🔍 סורק LEAPS עבור {ticker} (מינימום {min_dte} ימים)...")
        try:
            import yfinance as yf
            from datetime import datetime as dt
            from dateutil.parser import parse
            
            stock = yf.Ticker(ticker)
            expiries = stock.options
            if not expiries:
                self._log("WARN", f"❌ לא נמצאו פקיעות עבור {ticker} ביאהו פיננס.")
                return []
            
            self._log("INFO", f"מצאתי {len(expiries)} פקיעות פוטנציאליות.")
            today = dt.today()
            valid = []
            for e in expiries:
                try:
                    dte = (parse(e) - today).days
                    if dte >= min_dte: valid.append((e, dte))
                except: continue
            
            if not valid:
                self._log("WARN", f"לא נמצאו פקיעות מעל {min_dte} ימים. מחפש את הפקיעה הכי רחוקה...")
                valid = sorted([(e, (parse(e)-today).days) for e in expiries], key=lambda x: x[1], reverse=True)[:1]
            
            if not valid: return []
            
            valid.sort(key=lambda x: x[1])
            target_expiry, dte = valid[0]
            self._log("INFO", f"נבחרה פקיעה: {target_expiry} ({dte} ימים)")
            
            chain = stock.option_chain(target_expiry)
            calls = chain.calls
            if calls.empty:
                self._log("WARN", f"שרשרת האופציות עבור {target_expiry} ריקה.")
                return []
            
            underlying = float(stock.fast_info.last_price or 0)
            if underlying <= 0:
                # Fallback for price
                underlying = float(calls['strike'].iloc[len(calls)//2]) # rough estimate
            
            self._log("INFO", f"מחיר נכס בסיס: ${underlying:.2f}")
            
            results = []
            for idx, row in calls.iterrows():
                strike = float(row['strike'])
                bid, ask = float(row.get('bid',0)), float(row.get('ask',0))
                mid = (bid+ask)/2 if (bid>0 and ask>0) else float(row.get('lastPrice',0))
                
                if mid <= 0: continue
                
                # Approximate delta: 1.0 - (strike/underlying - 0.8)*2.5 for calls
                moneyness = strike / underlying if underlying > 0 else 1.0
                approx_delta = max(0.05, min(0.99, 1.25 - moneyness * 0.75))
                
                results.append({
                    "ticker": ticker, "strike": strike, "expiry": target_expiry, "right": "C",
                    "delta": round(approx_delta, 2), "mid": round(mid, 2), "bid": round(bid, 2), "ask": round(ask, 2),
                    "dte": dte, "source": "Yahoo Finance"
                })
            
            # Filter results to be around the target delta
            results.sort(key=lambda x: abs(x["delta"] - target_delta))
            final_results = results[:n_options]
            self._log("INFO", f"סריקה הושלמה. נמצאו {len(final_results)} מועמדים.")
            return final_results
        except Exception as e:
            self._log("ERROR", f"שגיאה בסריקת LEAPS: {e}")
            return []

    def place_adaptive_order(self, ticker: str, right: str, strike: float, expiry: str,
                             action: str, qty: int, limit_price: float, algo_speed: str = "Normal") -> Optional[int]:
        if not self.connected or not self.ib: return None
        try:
            exp_norm = str(expiry).replace("-", "")
            contract = Option(ticker, exp_norm, strike, right, 'SMART', 'USD', multiplier='100')
            order = LimitOrder(action, qty, round(limit_price, 2))
            trade = self.ib.placeOrder(contract, order)
            return trade.order.orderId
        except Exception as e:
            self._log("WARN", f"place_order error: {e}")
            return None


# ── Singleton ──
_client_instance = None

def get_client() -> TWSClient:
    global _client_instance
    if _client_instance is None:
        _client_instance = TWSClient()
    return _client_instance
