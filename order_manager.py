"""
order_manager.py — Smart Price Escalation + Adaptive Algo order tracking
"""
import threading
import time
import logging
from datetime import datetime
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, field

import config

logger = logging.getLogger(__name__)


@dataclass
class ManagedOrder:
    """Tracks lifecycle of one order through escalation."""
    order_id:      Optional[int]
    ticker:        str
    right:         str
    strike:        float
    expiry:        str
    action:        str          # BUY | SELL
    qty:           int
    initial_price: float        # Mid price at submission
    current_price: float        # May be escalated to Ask
    algo_speed:    str
    status:        str = "PENDING"   # PENDING | ESCALATED | FILLED | CANCELLED
    submitted_at:  datetime = field(default_factory=datetime.utcnow)
    escalated_at:  Optional[datetime] = None
    filled_price:  Optional[float] = None
    order_type:    str = "LMT"
    escalation_count: int = 0


class OrderManager:
    """
    Manages order submission and smart price escalation via a background thread.
    Works in Demo mode (no actual orders placed) or Live mode (via TWSClient).
    """

    def __init__(self):
        self._orders: Dict[str, ManagedOrder] = {}   # key: internal_id
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._tws = None
        self._log_cb: Optional[Callable[[str, str], None]] = None
        self._counter = 0

    def set_tws(self, tws) -> None:
        self._tws = tws

    def set_log_callback(self, fn: Callable[[str, str], None]) -> None:
        self._log_cb = fn

    def _log(self, level: str, msg: str) -> None:
        logger.info(msg)
        if self._log_cb:
            self._log_cb(level, msg)

    # ─── Public API ──────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._escalation_loop,
                                        daemon=True, name="OrderEscalation")
        self._thread.start()
        self._log("INFO", "Order Manager started (escalation loop active).")

    def stop(self) -> None:
        self._running = False

    def submit_order(self, ticker: str, right: str, strike: float, expiry: str,
                     action: str, qty: int, limit_price: float, escalation_step_pct: float,
                     algo_speed: str = "Normal", escalation_wait_mins: int = 1,
                     order_type: str = "LMT") -> str:
        """
        Submit a new order.
        For BUY:  limit_price increases by escalation_step_pct every N minutes.
        For SELL: limit_price decreases by escalation_step_pct every N minutes.
        """
        with self._lock:
            self._counter += 1
            internal_id = f"ORD-{self._counter:04d}"

        order_id = None
        initial_status = "PENDING"
        if self._tws and getattr(self._tws, "ib", None) and self._tws.ib.isConnected():
            order_id = self._tws.place_adaptive_order(
                action=action,
                qty=qty,
                ticker=ticker,
                right=right,
                strike=strike,
                expiry=expiry,
                limit_price=limit_price,
                algo_speed=algo_speed,
                order_type=order_type
            )
            if order_id is None:
                initial_status = "REJECTED"

        mo = ManagedOrder(
            order_id=order_id,
            ticker=ticker,
            right=right,
            strike=strike,
            expiry=expiry,
            action=action,
            qty=qty,
            initial_price=limit_price,
            current_price=limit_price,
            algo_speed=algo_speed,
            status=initial_status,
            escalation_count=0,
            submitted_at=datetime.utcnow(),
            order_type=order_type
        )
        # Store custom properties required for our escalation logic
        mo.__dict__["_escalation_step_pct"] = escalation_step_pct
        mo.__dict__["_escalation_wait_mins"] = escalation_wait_mins
        mo.__dict__["_limit_price"]      = limit_price

        with self._lock:
            self._orders[internal_id] = mo

        self._log(
            "ACTION",
            f"📤 Order {internal_id}: {action} {qty}x {ticker} {strike}{right} "
            f"{expiry} @ Limit=${limit_price:.2f} [{algo_speed}]"
        )
        return internal_id

    def cancel_order(self, internal_id: str) -> bool:
        with self._lock:
            mo = self._orders.get(internal_id)
            if not mo or mo.status not in ("PENDING", "ESCALATED"):
                return False
            mo.status = "CANCELLED"

        if self._tws and mo.order_id:
            self._tws.cancel_order(mo.order_id)

        self._log("WARN", f"❌ Order {internal_id} cancelled.")
        return True

    def get_all_orders(self) -> List[ManagedOrder]:
        with self._lock:
            return list(self._orders.values())

    def get_order(self, internal_id: str) -> Optional[ManagedOrder]:
        with self._lock:
            return self._orders.get(internal_id)

    def mark_filled(self, internal_id: str, fill_price: float) -> None:
        with self._lock:
            mo = self._orders.get(internal_id)
            if mo:
                mo.status = "FILLED"
                mo.filled_price = fill_price
        self._log("INFO", f"✅ Order {internal_id} filled @ ${fill_price:.2f}")

    # ─── Escalation Loop ─────────────────────────────────────────────────────

    def _escalation_loop(self) -> None:
        """Background thread: check pending orders every 10 s."""
        while self._running:
            time.sleep(10)

            try:
                with self._lock:
                    active_orders = [
                        (iid, mo) for iid, mo in self._orders.items()
                        if mo.status in ("PENDING", "ESCALATED") and mo.order_type != "MKT"
                    ]

                for iid, mo in active_orders:
                    last_time = mo.escalated_at if mo.escalated_at else mo.submitted_at
                    elapsed = (datetime.utcnow() - last_time).total_seconds()
                    
                    wait_mins = mo.__dict__.get("_escalation_wait_mins", config.ESCALATION_WAIT_MINUTES)
                    wait_seconds = int(wait_mins) * 60
                    
                    if elapsed >= wait_seconds:
                        self._escalate(iid, mo)
            except Exception as e:
                import traceback
                with open("C:\\Users\\User\\Desktop\\pmcc1\\order_thread_error.txt", "a") as f:
                    f.write(f"\\n--- Thread Error ---\\n{traceback.format_exc()}")

    def _escalate(self, internal_id: str, mo: ManagedOrder) -> None:
        """Modifies the order natively in TWS with the new stepped price."""
        step_pct = mo.__dict__.get("_escalation_step_pct", 1.0) / 100.0
        
        if mo.action == "BUY":
            escalation_price = mo.current_price * (1.0 + step_pct)
        else:
            escalation_price = mo.current_price * (1.0 - step_pct)
            
        escalation_price = max(0.01, round(escalation_price, 2))

        wait_mins = mo.__dict__.get("_escalation_wait_mins", config.ESCALATION_WAIT_MINUTES)

        self._log(
            "WARN",
            f"⏱️  Order {internal_id} unfilled after "
            f"{wait_mins}min → Escalating (+{step_pct*100:.1f}%) "
            f"(${mo.current_price:.2f} → ${escalation_price:.2f})"
        )

        # Attempt native modification if live
        modified = False
        if self._tws and mo.order_id and getattr(self._tws, "ib", None) and self._tws.ib.isConnected():
            modified = self._tws.modify_order(mo.order_id, escalation_price)
        
        # If native modification failed/unavailable or it's DEMO, we still track it internally
        if not modified:
            self._log("WARN", f"Order {internal_id} native modification failed (or DEMO mode). Tracking artificially.")

        with self._lock:
            mo.status = "ESCALATED"
            # Keep the old order_id because we modified it natively
            mo.current_price = escalation_price
            mo.escalated_at = datetime.utcnow()
            mo.escalation_count += 1


# Singleton
_manager = OrderManager()
_manager.start()


def get_manager() -> OrderManager:
    return _manager
