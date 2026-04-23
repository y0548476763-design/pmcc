"""
ibkr_auto_bot.py — PMCC Bot (HTTP client mode)
Reads portfolio from api_ibkr (:8002), technicals from api_yahoo (:8001).
No direct TWS connection — relies on the singleton in api_ibkr.
"""
import sys, time, logging, requests
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime
import config
import settings_manager

# ── Logging ────────────────────────────────────────────────────────────────
file_handler = TimedRotatingFileHandler(
    config.LOG_PATH, when="midnight", backupCount=3, encoding="utf-8")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[file_handler, logging.StreamHandler()])
log = logging.getLogger("ibkr_bot")

YAHOO = config.YAHOO_API_URL   # http://localhost:8001
IBKR  = config.IBKR_API_URL    # http://localhost:8002
TIMEOUT = 10


# ── Helpers ────────────────────────────────────────────────────────────────

def is_market_hours() -> bool:
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo("America/New_York"))
    if now.weekday() >= 5:
        return False
    o = now.replace(hour=9, minute=30, second=0, microsecond=0)
    c = now.replace(hour=16, minute=0, second=0, microsecond=0)
    return o <= now <= c


def get_dte(expiry_str: str) -> int:
    try:
        exp = datetime.strptime(str(expiry_str).replace("-", ""), "%Y%m%d")
        return max(0, (exp.date() - datetime.utcnow().date()).days)
    except Exception:
        return 999


def _get(path: str, base: str = IBKR, params: dict = None) -> dict:
    try:
        r = requests.get(f"{base}{path}", params=params, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.error(f"GET {base}{path} failed: {e}")
        return {"ok": False}


def _post(path: str, base: str = IBKR, body: dict = None) -> dict:
    try:
        r = requests.post(f"{base}{path}", json=body or {}, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.error(f"POST {base}{path} failed: {e}")
        return {"ok": False}


# ── Bot Logic ──────────────────────────────────────────────────────────────

def _get_signal(ticker: str) -> str:
    """Fetch quant signal for ticker from api_yahoo."""
    data = _get(f"/technicals/{ticker}", base=YAHOO)
    if not data.get("ok"):
        return "NO_TRADE"
    tech = data.get("data", {})
    close = tech.get("close", 0)
    ma200 = tech.get("ma200", 0)
    rsi   = tech.get("rsi", 50)
    hv30  = tech.get("hv30", 0.20)

    if rsi < config.RSI_OVERSOLD or tech.get("at_bb_lower"):
        return "NO_TRADE"
    if close > ma200 and rsi > config.RSI_NORMAL and hv30 >= config.HV30_AGGRESSIVE_THRESHOLD:
        return "AGGRESSIVE"
    if close > ma200 and rsi > config.RSI_DEFENSIVE_HIGH:
        return "NORMAL"
    if config.RSI_DEFENSIVE_LOW <= rsi <= config.RSI_DEFENSIVE_HIGH and close > ma200:
        return "DEFENSIVE"
    return "DEFENSIVE"


def _handle_leaps_rolls(positions: list, bot_active: bool) -> None:
    for p in positions:
        if p.get("type") != "LEAPS":
            continue
        ticker = p.get("ticker", "")
        dte = get_dte(p.get("expiry", "20990101"))
        if dte >= config.LEAPS_ROLL_DTE:
            continue

        log.info(f"[{ticker}] LEAPS DTE ({dte}) < {config.LEAPS_ROLL_DTE} — searching roll targets")
        data = _get("/leaps/search", base=YAHOO,
                    params={"ticker": ticker, "min_dte": 540, "target_delta": 0.8, "n": 1})
        if not data.get("ok") or not data.get("data"):
            log.warning(f"[{ticker}] No LEAPS roll targets found")
            continue

        tgt = data["data"][0]
        log.info(f"[{ticker}] Roll target: ${tgt['strike']} {tgt['expiry']} DTE={tgt['dte']}")

        if not bot_active:
            log.warning(f"[{ticker}] Bot inactive — alert only: LEAPS roll needed!")
            continue

        result = _post("/order/combo", body={
            "ticker": ticker,
            "qty": abs(p.get("qty", 1)),
            "sell_strike": float(p["strike"]),
            "sell_expiry": str(p["expiry"]),
            "buy_strike": float(tgt["strike"]),
            "buy_expiry": str(tgt["expiry"]),
            "limit_price": 0.0,
            "use_market": False,
            "escalation_step_pct": config.ESCALATION_STEP_PCT,
            "escalation_wait_secs": config.ESCALATION_WAIT_MINUTES * 60,
        })
        if result.get("ok"):
            log.info(f"[{ticker}] Combo roll submitted: {result.get('result', {})}")
        else:
            log.error(f"[{ticker}] Combo roll failed")


def _handle_shorts(positions: list, bot_active: bool) -> None:
    shorts = [p for p in positions if p.get("type") == "SHORT_CALL"]
    leaps  = [p for p in positions if p.get("type") == "LEAPS"]
    covered = {s.get("ticker") for s in shorts}

    for sc in shorts:
        ticker   = sc.get("ticker", "")
        expiry   = sc.get("expiry", "")
        strike   = sc.get("strike", 0)
        dte      = get_dte(expiry)
        delta    = abs(float(sc.get("delta", 0)))
        qty      = abs(int(sc.get("qty", 1)))
        cur_px   = float(sc.get("current_price", 0.01))
        cb_raw   = float(sc.get("cost_basis", 0))
        entry_px = cb_raw / 100.0 if cb_raw > 5 else (cb_raw if cb_raw > 0 else cur_px)

        if dte <= 0:
            log.warning(f"[{ticker}] Expired position {expiry} — skipping")
            continue

        # Take Profit
        if entry_px > 0 and cur_px > 0:
            profit_pct = (entry_px - cur_px) / entry_px
            if profit_pct >= config.TAKE_PROFIT_PCT:
                log.info(f"[{ticker}] TAKE PROFIT {profit_pct:.0%}")
                if bot_active:
                    _post("/qualify", body={"ticker": ticker, "strike": strike,
                                            "expiry": expiry, "right": "C"})
                else:
                    log.warning(f"[{ticker}] Bot inactive — TP alert only")
                continue

        # Risk stops
        reason = None
        if dte < config.TIME_STOP_DAYS:
            reason = f"DTE={dte}"
        elif delta >= config.ROLL_UP_THRESHOLD:
            reason = f"Delta={delta:.2f}"

        if reason:
            log.info(f"[{ticker}] Close: {reason}")
            if not bot_active:
                log.warning(f"[{ticker}] Bot inactive — roll alert: {reason}")

    # Uncovered LEAPS
    for lp in leaps:
        t = lp.get("ticker", "")
        if t in covered:
            continue
        log.info(f"[{t}] No short call — checking for entry signal")
        sig = _get_signal(t)
        if sig == "NO_TRADE":
            log.info(f"[{t}] NO_TRADE signal — skip")
            continue
        log.info(f"[{t}] Signal={sig}, could open short call")


def run_bot_cycle() -> None:
    bot_active = settings_manager.get_bot_active()
    log.info(f"--- Scan cycle [{'ACTIVE' if bot_active else 'MONITOR'}] ---")

    data = _get("/portfolio")
    if data.get("ok"):
        positions = data.get("positions", [])
        log.info(f"Portfolio from {data.get('source','?')}: {len(positions)} positions")
    else:
        log.warning("api_ibkr unreachable — using demo positions")
        positions = list(config.DEMO_POSITIONS)

    if not positions:
        log.warning("No positions found")
        return

    _handle_leaps_rolls(positions, bot_active)
    _handle_shorts(positions, bot_active)
    log.info("--- Scan cycle complete ---")


def main():
    log.info(f"PMCC Bot started — YAHOO={YAHOO} IBKR={IBKR}")
    while True:
        try:
            if is_market_hours():
                run_bot_cycle()
                time.sleep(60)
            else:
                log.info("Market closed — waiting 5 min")
                time.sleep(300)
        except KeyboardInterrupt:
            log.info("Stopped by user")
            break
        except Exception as e:
            log.error(f"Cycle error: {e}")
            time.sleep(30)


if __name__ == "__main__":
    main()
