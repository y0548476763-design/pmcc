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
        """Connect to the standalone IBKR worker."""
        self.mode = mode
        try:
            r = requests.post(f"{config.IBKR_API_URL}/connect", timeout=15).json()
            if "status" in r and "Connected successfully" in r["status"]:
                self.connected = True
                self._refresh_account()
                self._log("INFO", f"✅ חיבור הוקם לוורקר: {mode}")
                return True
            else:
                self._log("WARN", f"חיבור דרך הוורקר נכשל: {r}")
                self.connected = False
                return False
        except Exception as e:
            self._log("WARN", f"שגיאת תקשורת עם שרת הוורקר: {e}")
            self.connected = False
            return False

    async def connectAsync(self, mode: str = "DEMO", host: str = "127.0.0.1", port: int = None, client_id: int = None, timeout: int = 5) -> bool:
        """Wrapper for sync connect."""
        return self.connect(mode, host, port, client_id, timeout)

    def run_ib(self, coro, timeout: int = 20):
        """Deprecated: worker handles its own async loop."""
        self._log("WARN", "run_ib called but is deprecated with new worker architecture.")
        return None

    def disconnect(self) -> None:
        try:
            requests.post(f"{config.IBKR_API_URL}/disconnect", timeout=5)
        except: pass
        self.connected = False
        self._log("INFO", "🔌 נותק משרת הוורקר.")

    def _refresh_account(self) -> None:
        if not self.connected: return
        try:
            r = requests.get(f"{config.IBKR_API_URL}/account", timeout=5).json()
            if "error" not in r:
                self.cash_balance = r.get("TotalCashValue", 0.0)
                self.net_liquidation = r.get("NetLiquidation", 0.0)
        except Exception as e:
            self._log("WARN", f"Account refresh error: {e}")

    def get_positions(self) -> List[Dict]:
        if not self.connected: return []
        try:
            import api_ibkr
            r = api_ibkr.get_positions()
            if r.get("ok"):
                pos_list = []
                for p in r.get("positions", []):
                    # p format from api_ibkr: {"symbol": "UNH 20260605 480C", "qty": 1, "avg_cost": 15.83, "current_price": 16.0...}
                    sym_parts = str(p.get("symbol", "")).split()
                    base_sym = sym_parts[0] if sym_parts else "UNKNOWN"
                    is_opt = len(sym_parts) >= 3
                    
                    strike = 0.0
                    expiry = "—"
                    opt_type = "STOCK"
                    dte = 9999
                    delta = float(p.get("delta") or (1.0 if not is_opt else 0.0))
                    
                    if is_opt:
                        expiry = sym_parts[1]
                        try:
                            strike = float(sym_parts[2][:-1]) if sym_parts[2][:-1].replace('.','',1).isdigit() else 0.0
                            from datetime import datetime as dt
                            exp_date = dt.strptime(expiry, "%Y%m%d")
                            dte = (exp_date.date() - dt.utcnow().date()).days
                        except: pass
                        qty = float(p.get("qty", 0))
                        opt_type = "LEAPS" if (dte > 270 and qty > 0) else ("SHORT_CALL" if qty < 0 else "OTHER")
                    
                    pos_list.append({
                        "conId": p.get("con_id", 0), "ticker": base_sym, "type": opt_type,
                        "strike": strike, "expiry": expiry,
                        "qty": float(p.get("qty", 0)), "dte": dte, "delta": delta,
                        "cost_basis": float(p.get("avg_cost", 0)), "current_price": float(p.get("current_price") or p.get("marketPrice") or 0),
                        "premium_received": 0.0, "underlying_price": float(p.get("marketPrice", 0)),
                    })
                return pos_list
        except Exception as e:
            self._log("WARN", f"get_positions error: {e}")
        return []

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
        if not self.connected: return None
        try:
            import api_ibkr
            leg = {"strike": strike, "expiry": expiry.replace("-", ""), "right": right, "action": action, "qty": qty}
            r = api_ibkr.place_combo(ticker, [leg], limit_price, use_market=False, escalation_step_pct=1.0, escalation_wait_secs=30)
            if r.get("ok"):
                return r.get("order_id")
            return None
        except Exception as e:
            self._log("WARN", f"place_order error: {e}")
            return None

    def panic_close_all(self) -> int:
        if not self.connected: return 0
        try:
            import requests, config
            r = requests.post(f"{config.IBKR_API_URL}/cancel_all", timeout=10).json()
            if r.get("ok"):
                return 1
            return 0
        except Exception as e:
            self._log("WARN", f"panic_close_all error: {e}")
            return 0

    def restart_remote_gateway(self) -> bool:
        self._log("INFO", "Restarting remote gateway (stub)")
        return True

    def inject_remote_2fa(self, code: str) -> bool:
        self._log("INFO", f"Injecting 2FA code (stub)")
        return True


# ── Singleton ──
_client_instance = None

def get_client() -> TWSClient:
    global _client_instance
    if _client_instance is None:
        _client_instance = TWSClient()
    return _client_instance
