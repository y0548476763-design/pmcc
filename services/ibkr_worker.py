import asyncio
import logging
import math
import threading
import time
from datetime import datetime, timezone
from typing import List, Optional, Dict

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import ib_insync as ibi

# ── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Global IB Setup ──────────────────────────────────────────────────────────
ib = ibi.IB()
_ib_loop: Optional[asyncio.AbstractEventLoop] = None

# ── Active Escalations Registry (in-memory) ──────────────────────────────────
# Key: order_id (int)
# Value: dict with escalation metadata
_active_escalations: Dict[int, dict] = {}
_escalations_lock = threading.Lock()


def _register_escalation(oid: int, ticker: str, limit_price: float,
                         step_pct: float, wait_secs: int):
    with _escalations_lock:
        _active_escalations[oid] = {
            "order_id": oid,
            "ticker": ticker,
            "start_price": limit_price,
            "current_price": limit_price,
            "step_pct": step_pct,
            "wait_secs": wait_secs,
            "escalation_count": 0,
            "status": "PENDING",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }
    logger.info(f"[ESCALATION REGISTRY] Registered order {oid} for {ticker} at ${limit_price}")


def _update_escalation(oid: int, new_price: float, status: str = "ACTIVE"):
    with _escalations_lock:
        if oid in _active_escalations:
            _active_escalations[oid]["current_price"] = new_price
            _active_escalations[oid]["escalation_count"] += 1
            _active_escalations[oid]["status"] = status
            _active_escalations[oid]["last_updated"] = datetime.now(timezone.utc).isoformat()


def _finish_escalation(oid: int, status: str):
    with _escalations_lock:
        if oid in _active_escalations:
            _active_escalations[oid]["status"] = status
            _active_escalations[oid]["last_updated"] = datetime.now(timezone.utc).isoformat()
    logger.info(f"[ESCALATION REGISTRY] Order {oid} finished with status: {status}")


# ── IB Thread with Auto-Reconnect ────────────────────────────────────────────

def _run_ib_thread():
    """Background thread running its own dedicated asyncio event loop for IB.
    Reconnects automatically if the connection drops.
    """
    global _ib_loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _ib_loop = loop

    async def _connect_loop():
        """Keep trying to connect and stay connected forever."""
        ports = [4002, 7497, 4001, 7496]
        while True:
            if not ib.isConnected():
                logger.info("IB Worker: attempting to connect to IBKR...")
                connected = False
                for port in ports:
                    try:
                        await ib.connectAsync('127.0.0.1', port, clientId=10, timeout=5)
                        logger.info(f"IB Worker: Connected to IBKR on port {port}")
                        connected = True
                        break
                    except Exception as e:
                        logger.warning(f"IB Worker: Failed on port {port}: {e}")
                if not connected:
                    logger.error("IB Worker: All ports failed. Retrying in 10s...")
                    await asyncio.sleep(10)
            else:
                await asyncio.sleep(5)   # Check every 5 seconds

    # Schedule the keep-alive loop
    loop.create_task(_connect_loop())
    loop.run_forever()


# Start the dedicated IB thread
_th = threading.Thread(target=_run_ib_thread, daemon=True, name="ibkr_loop_thread")
_th.start()
# Give the thread a moment to initialise the loop reference
time.sleep(0.3)


def run_ib(coro, timeout=25):
    """Safely dispatches an ib_insync coroutine to the background IB event loop."""
    if _ib_loop is None:
        raise RuntimeError("IB event loop is not running")
    future = asyncio.run_coroutine_threadsafe(coro, _ib_loop)
    return future.result(timeout=timeout)


app = FastAPI(title="IBKR Worker Service")


# ── Pydantic Models ───────────────────────────────────────────────────────────

class ComboLeg(BaseModel):
    strike: float
    expiry: str
    right: str
    action: str  # BUY or SELL
    qty: int = 1
    conId: Optional[int] = None

class PlaceComboRequest(BaseModel):
    ticker: str
    legs: List[ComboLeg]
    limit_price: float
    use_market: bool = False
    escalation_step_pct: float = 1.0
    escalation_wait_secs: int = 180
    scheduled_time: Optional[str] = None

class QualifyComboRequest(BaseModel):
    ticker: str
    legs: List[ComboLeg]

class PlaceOrderRequest(BaseModel):
    ticker: str
    strike: float
    expiry: str
    right: str = "C"
    action: str = "BUY"
    qty: int = 1
    limit_price: Optional[float] = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "ibkr_connected": ib.isConnected(),
        "active_escalations": len(_active_escalations)
    }


@app.get("/api/escalations/status")
async def get_escalations_status():
    """Return the live status of all active escalation loops."""
    with _escalations_lock:
        return {"ok": True, "escalations": list(_active_escalations.values())}


@app.delete("/api/escalations/{order_id}")
async def cancel_escalation(order_id: int):
    """Mark an escalation as cancelled so the loop stops at the next iteration."""
    with _escalations_lock:
        if order_id not in _active_escalations:
            raise HTTPException(status_code=404, detail="Order not found")
        _active_escalations[order_id]["status"] = "CANCEL_REQUESTED"
    return {"ok": True, "message": f"Cancellation requested for order {order_id}"}


@app.post("/api/ibkr/connect")
async def connect_ibkr(mode: str = "DEMO"):
    """Force connection to IBKR Gateway. Dispatches to the IB thread."""
    if ib.isConnected():
        if hasattr(ib, 'disconnect'):
            ib.disconnect()
        await asyncio.sleep(1)

    ports = [4002, 7497] if mode.upper() == "DEMO" else [4001, 7496]

    for port in ports:
        try:
            logger.info(f"Trying to connect to port {port}...")
            run_ib(ib.connectAsync('127.0.0.1', port, clientId=10, timeout=4))
            return {"ok": True, "mode": mode, "port": port}
        except Exception as e:
            logger.warning(f"Failed on port {port}: {e}")

    raise HTTPException(status_code=503, detail="Could not connect to IBKR Gateway")


@app.get("/api/ibkr/positions")
async def get_positions():
    if not ib.isConnected():
        raise HTTPException(status_code=503, detail="IBKR not connected")

    async def _get_pos():
        pos = await ib.reqPositionsAsync()
        acc = await ib.accountSummaryAsync()
        return pos, acc

    positions, acc_summary = await asyncio.get_running_loop().run_in_executor(
        None, lambda: run_ib(_get_pos()))

    cash = 0.0
    net_liq = 0.0
    for item in acc_summary:
        if item.tag == "AvailableFunds":  cash = float(item.value)
        elif item.tag == "NetLiquidation": net_liq = float(item.value)

    pos_list = [{"ticker": p.contract.symbol, "secType": p.contract.secType,
                 "position": p.position, "avgCost": p.avgCost} for p in positions]

    return {"ok": True, "cash": cash, "net_liq": net_liq, "positions": pos_list}


@app.post("/api/ibkr/qualify_combo")
async def qualify_combo(req: QualifyComboRequest):
    if not ib.isConnected():
        raise HTTPException(status_code=503, detail="IBKR not connected")

    try:
        ib_options = []
        for l in req.legs:
            expiry = str(l.expiry).replace("-", "")
            ib_options.append(ibi.Option(req.ticker, expiry, l.strike, l.right, "SMART", currency="USD"))

        async def _qualify_all():
            await ib.qualifyContractsAsync(*ib_options)

            # Try delayed data first, fall back to frozen
            for data_type in [3, 4, 2]:
                ib.reqMarketDataType(data_type)
                tickers = await ib.reqTickersAsync(*ib_options)
                logger.info(f"Data type {data_type}: Requested {len(tickers)} tickers. Waiting...")
                await asyncio.sleep(3)

                # Check if any data came in
                has_data = any(
                    (not math.isnan(t.bid) and t.bid > 0) or
                    (not math.isnan(t.last) and t.last > 0) or
                    (not math.isnan(t.close) and t.close > 0)
                    for t in tickers
                )
                if has_data:
                    logger.info(f"Got market data with type {data_type}")
                    break
                logger.warning(f"No data with type {data_type}, trying next...")

            results = []
            for i, ticker in enumerate(tickers):
                def _safe_float(v):
                    try:
                        f = float(v)
                        return 0.0 if math.isnan(f) else f
                    except:
                        return 0.0

                bid  = _safe_float(ticker.bid)
                ask  = _safe_float(ticker.ask)
                last = _safe_float(ticker.last if not math.isnan(ticker.last) else 0)
                close = _safe_float(ticker.close if not math.isnan(ticker.close) else 0)

                if bid > 0 and ask > 0:
                    mid = round((bid + ask) / 2, 2)
                elif last > 0:
                    mid = last
                elif close > 0:
                    mid = close
                else:
                    mid = 0.0

                logger.info(
                    f"Leg {i} ({req.legs[i].right} {req.legs[i].strike}): "
                    f"BID={bid}, ASK={ask}, LAST={last}, CLOSE={close} -> MID={mid}"
                )

                results.append({
                    "strike": req.legs[i].strike,
                    "right": req.legs[i].right,
                    "conId": ticker.contract.conId,
                    "mid": mid
                })
            return results

        loop = asyncio.get_running_loop()
        legs_data = await loop.run_in_executor(None, lambda: run_ib(_qualify_all(), timeout=40))
        return {"ok": True, "legs": legs_data}

    except Exception as e:
        logger.error(f"Qualify error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/order/combo")
async def order_combo(req: PlaceComboRequest):
    if not ib.isConnected():
        raise HTTPException(status_code=503, detail="IBKR not connected")

    async def _escalate_and_report():
        """Places the order, registers it, then escalates until filled or cancelled."""
        combo_legs = []
        for l in req.legs:
            if not l.conId:
                raise ValueError(f"Missing conId for leg {l.strike} {l.right}")
            combo_legs.append(ibi.ComboLeg(
                conId=l.conId, ratio=l.qty, action=l.action, exchange='SMART'))
        bag = ibi.Bag(symbol=req.ticker, currency='USD', exchange='SMART', comboLegs=combo_legs)

        # 1. Wait for scheduled time
        if req.scheduled_time:
            try:
                from zoneinfo import ZoneInfo
            except ImportError:
                from backports.zoneinfo import ZoneInfo
            while True:
                now_ny = datetime.now(ZoneInfo("America/New_York"))
                hr, mn = map(int, req.scheduled_time.split(':'))
                sched_dt = now_ny.replace(hour=hr, minute=mn, second=0, microsecond=0)
                wait_secs = (sched_dt - now_ny).total_seconds()
                if wait_secs <= 0:
                    break
                logger.info(f"Waiting {int(wait_secs)}s for scheduled time {req.scheduled_time}")
                await asyncio.sleep(min(wait_secs, 10))

        # 2. Place initial order
        # For Iron Condors (Model B), we always treat the price as a CREDIT (Negative in IBKR)
        current_price = -abs(req.limit_price)
        logger.info(f"[COMBO] Using CREDIT pricing: UI price {req.limit_price} -> IBKR price {current_price}")
        
        if req.use_market:
            order = ibi.MarketOrder('BUY', 1)
        else:
            order = ibi.LimitOrder('BUY', 1, current_price)
            order.outsideRth = True

        trade = ib.placeOrder(bag, order)
        oid = trade.order.orderId
        logger.info(f"[COMBO ESCALATOR] Order placed ID={oid} for {req.ticker} at ${current_price} (Credit)")

        # Register in the escalation registry
        _register_escalation(oid, req.ticker, current_price,
                             req.escalation_step_pct, req.escalation_wait_secs)

        # Signal HTTP handler
        _shared_result["oid"] = oid
        _shared_event.set()

        # 3. Escalation loop
        if req.use_market or req.escalation_step_pct <= 0:
            _finish_escalation(oid, "MARKET_ORDER")
            return

        esc_step_usd = max(0.01, round(abs(current_price) * (req.escalation_step_pct / 100.0), 2))

        while True:
            await asyncio.sleep(req.escalation_wait_secs)

            # Check if cancel was requested from UI
            with _escalations_lock:
                status = _active_escalations.get(oid, {}).get("status", "")
            if status == "CANCEL_REQUESTED":
                logger.info(f"[COMBO ESCALATOR] Order {oid} cancellation requested — stopping.")
                _finish_escalation(oid, "CANCELLED")
                break

            # Check order status
            current_status = trade.orderStatus.status
            error_code     = trade.log[-1].errorCode if trade.log else 0

            # If filled — we're done
            if current_status in ("Filled", "ApiCancelled") and error_code not in (201,):
                logger.info(f"[COMBO ESCALATOR] Order {oid} DONE (status={current_status})")
                _finish_escalation(oid, f"DONE:{current_status}")
                break

            # If rejected with Error 201 (Guaranteed-to-Lose) or any Cancelled — escalate
            if current_status == "Cancelled" or error_code == 201:
                current_price = round(current_price + esc_step_usd, 2)
                logger.info(
                    f"[COMBO ESCALATOR] Order {oid} was rejected (err={error_code}) → "
                    f"placing NEW order at ${current_price} "
                    f"(step #{_active_escalations.get(oid, {}).get('escalation_count', 0) + 1})"
                )
                _update_escalation(oid, current_price)
                # CRITICAL: create a brand-new order object so IBKR assigns a new orderId
                new_order = ibi.LimitOrder('BUY', 1, current_price)
                new_order.outsideRth = True
                trade = ib.placeOrder(bag, new_order)
                oid = trade.order.orderId   # Track the new order ID
                logger.info(f"[COMBO ESCALATOR] New orderId={oid} placed at ${current_price}")
                continue

            # Not filled yet — normal escalation
            current_price = round(current_price + esc_step_usd, 2)
            logger.info(
                f"[COMBO ESCALATOR] Order {oid} ({req.ticker}) not filled → "
                f"escalating to ${current_price} "
                f"(step #{_active_escalations.get(oid, {}).get('escalation_count', 0) + 1})"
            )
            _update_escalation(oid, current_price)
            # Create a new order object to avoid duplicate orderId rejection
            new_order = ibi.LimitOrder('BUY', 1, current_price)
            new_order.outsideRth = True
            trade = ib.placeOrder(bag, new_order)
            oid = trade.order.orderId
            logger.info(f"[COMBO ESCALATOR] New orderId={oid} placed at ${current_price}")

    _shared_result = {}
    _shared_event = threading.Event()

    asyncio.run_coroutine_threadsafe(_escalate_and_report(), _ib_loop)

    loop = asyncio.get_running_loop()
    try:
        def _wait_for_oid():
            if not _shared_event.wait(timeout=60):
                raise TimeoutError("Timed out waiting for IBKR to accept order")
            return _shared_result.get("oid", 0)

        oid = await loop.run_in_executor(None, _wait_for_oid)
        return {"ok": True, "result": {"order_id": oid}}
    except Exception as e:
        logger.error(f"[COMBO] Failed: {e}")
        return {"ok": False, "error": str(e)}


@app.get("/api/ibkr/get_iv/{ticker}")
async def get_iv(ticker: str):
    return {"ok": True, "message": "Endpoint stub. Ready for implementation."}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
