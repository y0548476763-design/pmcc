"""
tws_client.py — Async TWS connector using ib_insync (dual-profile: Demo / Real)
"""
import asyncio
import logging
from typing import List, Dict, Optional, Callable
from datetime import datetime

logger = logging.getLogger(__name__)

# ib_insync requires TWS/IB Gateway running; graceful import fallback for demo mode
try:
    from ib_insync import (
        IB, Contract, Option, Stock, LimitOrder, MarketOrder,
        PortfolioItem, Position, Order, Trade
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

    def connect(self, mode: str = "DEMO") -> bool:
        """Try to connect to TWS. Returns True if successful."""
        if not IB_AVAILABLE:
            self._log("WARN", "ib_insync not installed. Staying in Demo mode.")
            return False

        # Always cleanly tear down any previous connection first
        if self.ib is not None:
            try:
                self.ib.disconnect()
            except Exception:
                pass
            self.ib = None
            self.connected = False

        self.mode = mode
        port = config.TWS_PORT_DEMO if mode == "DEMO" else config.TWS_PORT_LIVE

        # Try clientIds 42, 43, 44, 45, 46 in case a previous session is still holding one
        base_id = config.TWS_CLIENT_ID
        for attempt, cid in enumerate(range(base_id, base_id + 5)):
            try:
                self.ib = IB()
                self.ib.connect(config.TWS_HOST, port, clientId=cid,
                                timeout=8, readonly=False)
                self.connected = True
                # Critical: Pull all active TWS orders into memory so modify_order works after reconnect!
                self.ib.reqAllOpenOrders()
                self.ib.sleep(0.5)
                self._refresh_account()
                self._log("INFO",
                          f"✅ Connected to TWS [{mode}] on port {port} "
                          f"(clientId={cid}). Account: {self.account_id}")
                return True
            except Exception as e:
                err_str = str(e)
                self._log("WARN",
                          f"⚠️  Connect attempt {attempt+1} (clientId={cid}): {err_str}")
                try:
                    self.ib.disconnect()
                except Exception:
                    pass
                self.ib = None
                # If it's not a clientId conflict, don't retry
                if "clientId" not in err_str.lower() and attempt > 0:
                    break

        self._log("WARN", "❌ All TWS connect attempts failed → Demo mode active.")
        self.connected = False
        return False

    def disconnect(self) -> None:
        if self.ib and self.connected:
            self.ib.disconnect()
        self.connected = False
        self._log("INFO", "Disconnected from TWS.")

    # ─── Account & Positions ─────────────────────────────────────────────────

    def _refresh_account(self) -> None:
        if not self.connected or not self.ib:
            return
        try:
            # managedAccounts() is the reliable way to get the account ID
            accounts = self.ib.managedAccounts()
            if accounts:
                self.account_id = accounts[0]

            # Now pull cash + net liq from accountValues
            vals = self.ib.accountValues(self.account_id)
            for v in vals:
                if v.tag == "TotalCashValue" and v.currency == "USD":
                    self.cash_balance = float(v.value)
                if v.tag == "NetLiquidation" and v.currency == "USD":
                    self.net_liquidation = float(v.value)

            self._log("INFO",
                      f"Account: {self.account_id} | "
                      f"Cash: ${self.cash_balance:,.0f} | "
                      f"NetLiq: ${self.net_liquidation:,.0f}")
        except Exception as e:
            self._log("WARN", f"Account refresh error: {e}")

    def get_positions(self) -> List[Dict]:
        """Returns list of position dicts matching DEMO_POSITIONS schema."""
        if not self.connected or not self.ib:
            return []  # Caller should fall back to demo data

        positions = []
        try:
            for pos in self.ib.portfolio():
                c = pos.contract
                if c.secType != "OPT":
                    continue
                positions.append({
                    "ticker": c.symbol,
                    "type": "LEAPS" if (
                        (datetime.strptime(c.lastTradeDateOrContractMonth, "%Y%m%d")
                         - datetime.utcnow()).days > 270
                    ) else "SHORT_CALL",
                    "strike": float(c.strike),
                    "expiry": c.lastTradeDateOrContractMonth,
                    "qty": int(pos.position),
                    "delta": 0.0,          # will be enriched by data_feed
                    "cost_basis": float(pos.averageCost),
                    "current_price": float(pos.marketPrice),
                    "premium_received": 0.0,
                    "underlying_price": float(pos.marketValue),
                })
        except Exception as e:
            self._log("WARN", f"get_positions error: {e}")
        return positions

    def get_option_chain(self, ticker: str, right: str = "C",
                         min_dte: int = 14, max_dte: int = 60,
                         target_delta: float = 0.30,
                         n_strikes: int = 6) -> List[Dict]:
        """Fetch real option chain from Yahoo Finance to bypass IBKR data fees."""
        # This completely replaces the need for paid IBKR real-time data subscriptions!
        try:
            import yfinance as yf
            from datetime import datetime as dt
            from dateutil.parser import parse
            
            stock = yf.Ticker(ticker)
            expiries = stock.options
            
            if not expiries:
                self._log("WARN", f"Yahoo Finance returned no options for {ticker}.")
                return []
                
            today = dt.today()
            
            # Filter valid real expiries by DTE
            valid_expiries = []
            for e in expiries:
                try:
                    dte = (parse(e) - today).days
                    if min_dte <= dte <= max_dte:
                        valid_expiries.append((e, dte))
                except Exception:
                    continue
                    
            if not valid_expiries:
                self._log("WARN", f"No valid YF expiries in {min_dte}-{max_dte} DTE range.")
                return []
                
            # Pick the earliest expiry in range
            valid_expiries.sort(key=lambda x: x[1])
            target_expiry, dte = valid_expiries[0]
            
            # Fetch the real chain for this specific real expiry!
            chain = stock.option_chain(target_expiry)
            calls_or_puts = chain.calls if right.upper() == "C" else chain.puts
            
            if calls_or_puts.empty:
                return []
                
            # Get underlying price
            underlying = float(stock.fast_info.last_price or stock.fast_info.previous_close or 200.0)
            
            results = []
            for idx, row in calls_or_puts.iterrows():
                strike = float(row['strike'])
                bid = float(row.get('bid', 0.0))
                ask = float(row.get('ask', 0.0))
                iv = float(row.get('impliedVolatility', 0.0))
                
                # Approximate delta via moneyness for basic sorting
                if underlying > 0:
                    moneyness = strike / underlying
                    # Very rough synthetical delta for sorting (actual delta requires Black-Scholes)
                    if right.upper() == "C":
                        delta = max(0.01, min(0.99, 1.0 - (moneyness - 0.8) * 2.5)) if moneyness > 0.8 else 0.99
                    else:
                        delta = max(0.01, min(0.99, (moneyness - 0.8) * 2.5)) if moneyness > 0.8 else 0.01
                else:
                    delta = 0.50
                    
                mid = (bid + ask) / 2 if (bid > 0 and ask > 0) else float(row.get('lastPrice', 0.0))
                
                results.append({
                    "ticker": ticker,
                    "strike": strike,
                    "expiry": target_expiry, # YYYY-MM-DD
                    "right": right.upper(),
                    "delta": round(delta, 3),
                    "bid": round(bid, 2),
                    "ask": round(ask, 2),
                    "mid": round(mid, 2),
                    "premium": round(mid, 2),
                    "theta": -0.05, # YF doesn't provide Greeks directly
                    "iv": round(iv, 3),
                    "dte": dte
                })
                
            # Sort by proximity to target delta
            results.sort(key=lambda x: abs(x["delta"] - target_delta))
            return results[:n_strikes]
            
        except Exception as e:
            self._log("WARN", f"Yahoo Finance Option Chain Error: {e}")
            return []

    def place_adaptive_order(self, ticker: str, right: str, strike: float, expiry: str,
                             action: str, qty: int, limit_price: float, algo_speed: str = "Normal",
                             order_type: str = "LMT") -> Optional[int]:
        """
        Place option order via TWS API.
        Because Streamlit runs synchronously, ib.qualifyContracts blocks.
        By providing the exact Option contract (including multiplier='100'),
        TWS accepts the order directly without needing prior qualification.
        """
        if not self.connected or not self.ib:
            self._log("WARN", "Not connected to TWS - order NOT placed (Demo mode).")
            return None

        from datetime import datetime as _dt
        expiry_norm = expiry.replace("-", "").replace("/", "").replace(" ", "")
        try:
            exp_date = _dt.strptime(expiry_norm, "%Y%m%d")
            if exp_date.date() < _dt.utcnow().date():
                self._log("WARN", f"Order rejected: expiry {expiry} is in the PAST.")
                return None
        except ValueError:
            self._log("WARN", f"Invalid expiry format: {expiry}. Use YYYY-MM-DD.")
            return None

        try:
            self._log("INFO",
                      f"[System] Validating and Formulating Contract: "
                      f"{action} {qty}x {ticker} ${strike:.0f}{right} "
                      f"{expiry_norm} @ ${limit_price:.2f}")

            # Auto-Correct Synthetic Contracts to Nearest REAL Listed Contract
            try:
                from ib_insync import Stock
                underlying = Stock(ticker, 'SMART', 'USD')
                self.ib.qualifyContracts(underlying)
                chains = self.ib.reqSecDefOptParams(underlying.symbol, '', underlying.secType, underlying.conId)
                if chains:
                    chain = next((c for c in chains if c.exchange in ('SMART', 'NASDAQ', 'CBOE', 'AMEX', 'BATS', 'ISE')), chains[0])
                    # Snap Expiry
                    if expiry_norm not in set(chain.expirations):
                        valid_exp = sorted(list(chain.expirations), key=lambda x: abs((_dt.strptime(x, "%Y%m%d") - exp_date).days))
                        if valid_exp:
                            expiry_norm = valid_exp[0]
                    
                    # Snap Strike
                    f_strike = float(strike)
                    if f_strike not in set(chain.strikes):
                        valid_stri = sorted(list(chain.strikes), key=lambda x: abs(x - f_strike))
                        if valid_stri:
                            strike = valid_stri[0]
            except Exception as qc_err:
                self._log("WARN", f"Contract validation fallback error: {qc_err}")

            # Fully specified contract - currency='USD' is required to avoid ambiguous routing
            contract = Option(
                symbol=ticker,
                lastTradeDateOrContractMonth=expiry_norm,
                strike=float(strike),
                right=right,
                exchange="SMART",
                currency="USD",
                multiplier="100",
            )

            if order_type == "MKT":
                from ib_insync import MarketOrder
                order = MarketOrder(action, qty)
            else:
                order = LimitOrder(action, qty, round(limit_price, 2))
                order.tif = "DAY"
                try:
                    from ib_insync import TagValue
                    speed_map = {"Patient": "Patient", "Normal": "Normal",
                                 "Urgent": "Urgent", "patient": "Patient",
                                 "normal": "Normal", "urgent": "Urgent"}
                    order.algoStrategy = "Adaptive"
                    order.algoParams = [TagValue("adaptivePriority",
                                                 speed_map.get(algo_speed, "Normal"))]
                except Exception:
                    pass  # plain LimitOrder fallback

            self._log("INFO", "[System] Submitting Order directly to TWS...")
            
            # Place order - use plain time.sleep so the ib_insync background
            # thread can process TWS responses without deadlocking Streamlit.
            import time as _time
            trade = self.ib.placeOrder(contract, order)
            _time.sleep(1.0)  # background ib thread processes responses during this window
            
            oid    = trade.order.orderId
            status = trade.orderStatus.status
            
            if status in ("Cancelled", "Inactive"):
                err_msg = ""
                if trade.log and any("Error" in str(l) for l in trade.log):
                    err_msg = " | " + " ".join(str(l.message) for l in trade.log if "Error" in str(l))
                
                # FALLBACK: If a Market Order is rejected (e.g., TWS Demo lacks instant quotes), auto-convert to LMT Ask + 1%
                if order_type == "MKT":
                    self._log("WARN", f"Market Order rejected by Demo. Auto-converting to Aggressive Limit Order... {err_msg}")
                    fallback_price = limit_price * 1.01 if action == "BUY" else limit_price * 0.99
                    fallback_price = max(0.01, round(fallback_price, 2))
                    
                    fallback_order = LimitOrder(action, qty, fallback_price)
                    fallback_order.tif = "DAY"
                    fallback_trade = self.ib.placeOrder(contract, fallback_order)
                    _time.sleep(1.0)
                    
                    f_oid = fallback_trade.order.orderId
                    f_status = fallback_trade.orderStatus.status
                    if f_status not in ("Cancelled", "Inactive"):
                        self._log("ACTION", f"✅ Fallback Limit Order SENT: {action} {qty}x {ticker} MKT->LMT @ ${fallback_price:.2f} orderId={f_oid}")
                        return f_oid

                self._log("WARN", f"❌ Order instantly REJECTED by TWS (status: {status}){err_msg}. Contract may be invalid.")
                return None

            self._log("ACTION",
                      f"✅ Order SENT to TWS: {action} {qty}x {ticker} "
                      f"${strike:.0f}{right} {expiry} @ ${limit_price:.2f} "
                      f"[{order_type}] orderId={oid} status={status}")
            return oid

        except Exception as e:
            self._log("WARN", f"place_order error: {e}")
            return None

    def cancel_order(self, order_id: int) -> bool:
        if not self.connected or not self.ib:
            return False
        try:
            trades = [t for t in self.ib.trades() if t.order.orderId == order_id]
            if trades:
                def _do_cancel():
                    if self.ib and self.ib.isConnected():
                        self.ib.cancelOrder(trades[0].order)
                
                if self.ib.loop and self.ib.loop.is_running():
                    self.ib.loop.call_soon_threadsafe(_do_cancel)
                else:
                    _do_cancel()
                    
                self._log("INFO", f"Order {order_id} cancelled.")
                return True
        except Exception as e:
            self._log("WARN", f"cancel_order error: {e}")
        return False

    def modify_order(self, order_id: int, new_limit_price: float) -> bool:
        """Modifies the limit price of an active order in TWS."""
        if not self.connected or not self.ib:
            return False
        try:
            trades = [t for t in self.ib.trades() if t.order.orderId == order_id and t.orderStatus.status not in ("Filled", "Cancelled", "Inactive")]
            if trades:
                trade = trades[0]
                trade.order.lmtPrice = round(new_limit_price, 2)
                
                def _do_modify():
                    if self.ib and self.ib.isConnected():
                        try:
                            self.ib.placeOrder(trade.contract, trade.order)
                        except Exception as ex:
                            with open("C:\\Users\\User\\Desktop\\pmcc1\\tws_modify_error.txt", "a") as f:
                                f.write(f"Exception during placeOrder: {ex}\n")

                if self.ib.loop and self.ib.loop.is_running():
                    self.ib.loop.call_soon_threadsafe(_do_modify)
                else:
                    _do_modify()
                    
                # Dump TWS logs to see if it rejected
                with open("C:\\Users\\User\\Desktop\\pmcc1\\tws_modify_log.txt", "a") as f:
                    f.write(f"\\n--- Modification Log {order_id} ---\\n")
                    f.write(f"Old Price: {trade.order.lmtPrice} -> New Price: {new_limit_price}\\n")
                    for lg in trade.log:
                        f.write(f"{lg}\\n")
                        
                self._log("INFO", f"Order {order_id} MODIFIED (New Price: ${new_limit_price:.2f}).")
                return True
            else:
                with open("C:\\Users\\User\\Desktop\\pmcc1\\tws_missing_order.txt", "a") as f:
                    f.write(f"\\n--- Missing Order {order_id} ---\\n")
                    f.write(f"All Trades memory:\\n")
                    for tx in self.ib.trades():
                        f.write(f"ID={tx.order.orderId} | Status={tx.orderStatus.status} | Sym={tx.contract.symbol}\\n")
                self._log("WARN", f"modify_order: Order {order_id} not found or not active.")
        except Exception as e:
            self._log("WARN", f"modify_order error: {e}")
        return False

    def panic_close_all(self) -> int:
        """Market-sell all open option positions. Returns number of orders placed."""
        if not self.connected or not self.ib:
            self._log("WARN", "PANIC blocked – not connected to TWS (Demo mode).")
            return 0

        count = 0
        try:
            for pos in self.ib.portfolio():
                if pos.contract.secType == "OPT" and pos.position != 0:
                    action = "BUY" if pos.position < 0 else "SELL"
                    qty = abs(int(pos.position))
                    order = MarketOrder(action, qty)
                    self.ib.placeOrder(pos.contract, order)
                    count += 1
                    self._log("ACTION",
                              f"PANIC: {action} {qty}x {pos.contract.symbol} "
                              f"{pos.contract.strike} MKT")
        except Exception as e:
            self._log("WARN", f"panic_close_all error: {e}")
        return count

    # ─── Demo Helpers ────────────────────────────────────────────────────────

    def _demo_option_chain(self, ticker: str, right: str, target_delta: float,
                            n: int = 6) -> List[Dict]:
        """Generate synthetic option chain for demo mode — uses real price from yfinance."""
        if getattr(self, "mode", "DEMO") == "LIVE":
            return []
        # Try to get real current price via yfinance
        underlying = 200.0
        try:
            import yfinance as yf
            info = yf.Ticker(ticker).fast_info
            underlying = float(info.last_price or info.previous_close or 200.0)
        except Exception:
            # Hard-coded fallbacks
            underlying = {"NVDA": 115, "AAPL": 225, "TSLA": 280,
                          "SPY": 560, "QQQ": 480, "AMZN": 195,
                          "GOOGL": 170, "META": 600, "MSFT": 420,
                          "UNH": 490}.get(ticker, 200.0)

        import numpy as np
        # Strikes from 80% to 120% ATM
        strikes = np.linspace(underlying * 0.80, underlying * 1.20, 16)
        from datetime import datetime, timedelta
        # Next monthly expiry ~30-45 DTE
        today = datetime.utcnow()
        exp_date = today + timedelta(days=35)
        # Snap to 3rd Friday
        while exp_date.weekday() != 4:
            exp_date += timedelta(days=1)
        expiry_str = exp_date.strftime("%Y-%m-%d")

        rows = []
        for s in strikes:
            moneyness = s / underlying
            delta = max(0.02, min(0.95, 1.12 - moneyness))
            iv    = 0.30 + abs(delta - 0.50) * 0.15
            theta = -underlying * iv * delta * 0.004
            bid   = max(0.05, underlying * iv / 100 * delta * 18)
            ask   = bid * 1.06
            rows.append({
                "ticker":  ticker,
                "strike":  round(s, 1),
                "expiry":  expiry_str,
                "right":   right,
                "delta":   round(delta, 3),
                "bid":     round(bid, 2),
                "ask":     round(ask, 2),
                "mid":     round((bid + ask) / 2, 2),
                "premium": round((bid + ask) / 2, 2),
                "theta":   round(theta, 4),
                "iv":      round(iv, 3),
            })
        rows.sort(key=lambda x: abs(x["delta"] - target_delta))
        return rows[:n]


# Singleton
_client = TWSClient()


def get_client() -> TWSClient:
    return _client
