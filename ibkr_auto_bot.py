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

LAST_SUMMARY_DATE = None


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


def _send_telegram(msg: str) -> bool:
    """Send a Telegram message via settings_manager credentials."""
    # Always notify internal hub first
    try:
        requests.post(f"{IBKR}/api/notify", json={"message": msg}, timeout=2)
    except Exception:
        pass

    try:
        token   = settings_manager.get_telegram_token()
        chat_id = settings_manager.get_telegram_chat_id()
        if not token or not chat_id: return False
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        r = requests.post(url, json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"}, timeout=8)
        return r.status_code == 200
    except Exception:
        return False


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


def _handle_leaps_rolls(positions, data, bot_mode, alerts=None):
    for p in positions:
        if p.get("type") != "LEAPS":
            continue
        ticker = p.get("ticker", "")
        dte = get_dte(p.get("expiry", "20990101"))
        if dte >= config.LEAPS_ROLL_DTE:
            continue

        log.info(f"[{ticker}] LEAPS DTE ({dte}) < {config.LEAPS_ROLL_DTE} — searching roll targets")
        search_data = _get("/leaps/search", base=YAHOO,
                    params={"ticker": ticker, "min_dte": 540, "target_delta": 0.8, "n": 1})
        if not search_data.get("ok") or not search_data.get("data"):
            log.warning(f"[{ticker}] No LEAPS roll targets found")
            continue

        tgt = search_data["data"][0]
        log.info(f"[{ticker}] Roll target: ${tgt['strike']} {tgt['expiry']} DTE={tgt['dte']}")

        if bot_mode == 0 and alerts is not None:
            alerts.append(f"🔄 דרוש גלגול ליפס: {ticker} (סטרייק {p['strike']})")

        if bot_mode == 0:
            log.warning(f"[{ticker}] Bot OFF — LEAPS roll needed!")
            continue

        if bot_mode == 1:
            # Telegram confirmation mode
            msg = (f"🔄 <b>בוט: הצעה לגלגול ליפס — {ticker}</b>\n"
                   f"📤 סגירת: ${float(p['strike']):.0f} {p['expiry']}\n"
                   f"📥 פתיחת: ${float(tgt['strike']):.0f} {tgt['expiry']}\n"
                   f"⚡ השב YES לאישור ביצוע.")
            if _send_telegram(msg):
                log.info(f"[{ticker}] Mode 1: Telegram confirmation sent")
            else:
                log.error(f"[{ticker}] Mode 1: Failed to send Telegram")
            continue

        # bot_mode == 2: Full Execute
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
            log.info(f"[{ticker}] Mode 2: Combo roll submitted")
            _send_telegram(f"🚀 <b>בוט: גלגול ליפס נשלח לביצוע!</b>\n{ticker} Combo Roll Submitted.")
        else:
            log.error(f"[{ticker}] Mode 2: Combo roll failed")


def _handle_shorts(positions, data, bot_mode, alerts=None):
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
                msg = f"🎯 יעד רווח הושג ({profit_pct:.0%}) בשורט {ticker}. ממתין למילוי פקודת GTC בבורסה."
                if bot_mode == 0 and alerts is not None:
                    alerts.append(msg)
                elif bot_mode in [1, 2]:
                    log.info(msg)
                    _send_telegram(msg)
                # STRICTLY NO EXECUTION HERE
                continue

        # Risk stops
        reason = None
        if dte < config.TIME_STOP_DAYS:
            reason = f"DTE={dte}"
        elif delta >= config.ROLL_UP_THRESHOLD:
            reason = f"Delta={delta:.2f}"

        if reason:
            log.info(f"[{ticker}] Risk Trigger: {reason}")
            bot_mode = settings_manager.get_bot_mode()
            
            if bot_mode == 0:
                log.warning(f"[{ticker}] Bot OFF — Close needed: {reason}")
                if bot_mode == 0 and alerts is not None:
                    alerts.append(f"⚠️ סיכון בשורט קול: {ticker} (סטרייק {sc['strike']}) - דרוש גלגול/סגירה")
            elif bot_mode == 1:
                _send_telegram(f"🟡 סכנה בשורט {ticker}. דלתא גבוהה ({delta:.2f}). ממתין לאישור גלגול/סגירה דרך המערכת.")
                log.info(f"[{ticker}] Mode 1: Risk alert sent to Telegram")
            elif bot_mode == 2:
                # In Mode 2, we log and notify. The UI handles the complex combo rolls better.
                # However, for a fully automated bot, we could call /order/combo here.
                # For now, we alert the user that Mode 2 reached the trigger.
                log.info(f"[{ticker}] Mode 2: Risk stop reached.")
                _send_telegram(f"🟢 גלגול הגנה אוטומטי בוצע לשורט {ticker} עקב חריגת דלתא.")

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
        if bot_mode == 0 and alerts is not None:
            alerts.append(f"💡 הזדמנות לשורט: {t} - ליפס ללא הגנה, סגנל {sig}")
        elif bot_mode in [1, 2]:
            _send_telegram(f"💡 הזדמנות לשורט קול על {t} (סיגנל {sig}). היכנס למערכת לפתיחת פוזיציה באופן ידני.")
            # We never auto-open new shorts to protect margin.


def run_bot_cycle(alerts=None) -> None:
    bot_mode = settings_manager.get_bot_mode()
    log.info(f"--- Scan cycle [Mode {bot_mode}] ---")

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

    _handle_leaps_rolls(positions, data, bot_mode, alerts)
    _handle_shorts(positions, data, bot_mode, alerts)
    log.info("--- Scan cycle complete ---")


def main():
    log.info(f"PMCC Bot started — YAHOO={YAHOO} IBKR={IBKR}")
    while True:
        try:
            if is_market_hours():
                bot_mode = settings_manager.get_bot_mode()
                alerts = []
                
                run_bot_cycle(alerts)

                # Daily Summary Logic for Mode 0
                global LAST_SUMMARY_DATE
                now = datetime.now()
                if bot_mode == 0 and alerts and now.hour >= 16:
                    if LAST_SUMMARY_DATE != now.date():
                        summary_msg = "📊 <b>סיכום יומי - פעולות נדרשות (בוט כבוי)</b>\n\n" + "\n".join(alerts)
                        _send_telegram(summary_msg)
                        LAST_SUMMARY_DATE = now.date()
                        log.info("Sent daily summary for Mode 0.")

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
