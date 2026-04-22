"""
settings_manager.py — Persistent user settings with dual portfolio support.
All settings stored in user_settings.json.
"""
import json
import os
from datetime import datetime
from typing import Optional, List, Dict, Any
import config

SETTINGS_FILE = config.SETTINGS_PATH


# ─── Core I/O ──────────────────────────────────────────────────────────────

def load_settings() -> dict:
    if not os.path.exists(SETTINGS_FILE):
        return {}
    try:
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Failed to read settings: {e}")
        return {}


def save_settings(settings_dict: dict) -> bool:
    try:
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings_dict, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"Failed to write settings: {e}")
        return False


def _get(key: str, default=None):
    return load_settings().get(key, default)


def _set(key: str, value) -> None:
    s = load_settings()
    s[key] = value
    save_settings(s)


# ─── Cash ──────────────────────────────────────────────────────────────────

def get_external_cash() -> float:
    return float(_get("external_cash", 10000.0))


def set_external_cash(amount: float) -> None:
    _set("external_cash", float(amount))


# ─── Bot Mode (0=OFF, 1=MONITOR, 2=EXECUTE) ───────────────────────────────

def get_bot_mode() -> int:
    """0=OFF, 1=MONITOR (default), 2=EXECUTE"""
    return int(_get("bot_mode", config.BOT_MODE_DEFAULT))


def set_bot_mode(mode: int) -> None:
    _set("bot_mode", int(mode))


def get_bot_active() -> bool:
    """Returns True ONLY in full EXECUTE mode (2)."""
    return get_bot_mode() == 2


def set_bot_active(is_active: bool) -> None:
    """Legacy compatibility."""
    _set("bot_mode", 1 if is_active else 0)


# ─── Telegram ──────────────────────────────────────────────────────────────

def get_telegram_token() -> str:
    return str(_get("telegram_token", config.TELEGRAM_BOT_TOKEN))


def set_telegram_token(token: str) -> None:
    _set("telegram_token", token)


def get_telegram_chat_id() -> str:
    return str(_get("telegram_chat_id", config.TELEGRAM_CHAT_ID))


def set_telegram_chat_id(chat_id: str) -> None:
    _set("telegram_chat_id", str(chat_id))


# ─── Connection Profile ────────────────────────────────────────────────────

def get_connection_profile() -> dict:
    """Returns saved connection profile dict."""
    default = {
        "mode":   "DEMO",       # DEMO | LIVE
        "host":   "local",      # local | remote
        "interval_sec": 60,
    }
    return _get("connection_profile", default)


def set_connection_profile(mode: str, host: str, interval_sec: int = 60) -> None:
    _set("connection_profile", {
        "mode":         mode,
        "host":         host,
        "interval_sec": interval_sec,
    })


def get_bot_interval() -> int:
    profile = get_connection_profile()
    return int(profile.get("interval_sec", 60))


# ─── Dual Portfolio Persistence ────────────────────────────────────────────

def save_portfolio_snapshot(mode: str, positions: List[Dict]) -> None:
    """
    Saves portfolio snapshot for 'DEMO' or 'LIVE'.
    Positions are serialized with a timestamp.
    """
    s = load_settings()
    key = f"portfolio_{mode.upper()}"
    s[key] = {
        "positions":    positions,
        "updated_at":  datetime.utcnow().isoformat(),
    }
    save_settings(s)


def get_portfolio_snapshot(mode: str) -> List[Dict]:
    """Retrieve saved portfolio for given mode. Returns [] if none."""
    s = load_settings()
    key = f"portfolio_{mode.upper()}"
    snap = s.get(key, {})
    return snap.get("positions", [])


def get_portfolio_last_updated(mode: str) -> Optional[str]:
    """Return ISO timestamp of last save, or None."""
    s = load_settings()
    key = f"portfolio_{mode.upper()}"
    return s.get(key, {}).get("updated_at")


# ─── Rule Overrides (editable per-tab) ────────────────────────────────────

def get_rule(rule_key: str, default) -> Any:
    rules = _get("rules", {})
    return rules.get(rule_key, default)


def set_rule(rule_key: str, value: Any) -> None:
    s = load_settings()
    if "rules" not in s:
        s["rules"] = {}
    s["rules"][rule_key] = value
    save_settings(s)


# ─── Watchlist Tickers ────────────────────────────────────────────────────

def get_watchlist() -> List[str]:
    return _get("watchlist", list(config.WATCHLIST_TICKERS))


def set_watchlist(tickers: List[str]) -> None:
    _set("watchlist", list(tickers))


# ─── Last Webhook Payload ─────────────────────────────────────────────────

def save_webhook_payload(payload: dict) -> None:
    _set("last_webhook", {
        "payload":    payload,
        "received_at": datetime.utcnow().isoformat(),
    })


def get_webhook_payload() -> dict:
    return _get("last_webhook", {})
