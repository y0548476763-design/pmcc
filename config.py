"""
config.py - Central configuration for PMCC Quant-Dashboard v2.0
"""
import os
from typing import Dict

# ─── TWS Connection ────────────────────────────────────────────────────────
TWS_HOST       = os.getenv("TWS_HOST", "127.0.0.1")
TWS_PORT_LIVE  = int(os.getenv("TWS_PORT_LIVE", 7496))
TWS_PORT_DEMO  = int(os.getenv("TWS_PORT_DEMO", 4002))
TWS_CLIENT_ID  = int(os.getenv("TWS_CLIENT_ID", 42))

# Remote GCP Gateway (permanent static IP)
REMOTE_TWS_HOST      = os.getenv("REMOTE_TWS_HOST", "")
REMOTE_COMMAND_PORT  = int(os.getenv("REMOTE_COMMAND_PORT", 5000))

# ─── Microservices URLs ────────────────────────────────────────────────────
IBKR_PORT  = int(os.getenv("IBKR_PORT", 8001))
YAHOO_PORT = int(os.getenv("YAHOO_PORT", 8002))

IBKR_API_URL  = f"http://localhost:{IBKR_PORT}"
YAHOO_API_URL = f"http://localhost:{YAHOO_PORT}"

# ─── File Paths ────────────────────────────────────────────────────────────
BASE_DIR      = os.getenv("PMCC_BASE_DIR", os.path.dirname(os.path.abspath(__file__)))
DB_PATH       = os.path.join(BASE_DIR, "pmcc_data.db")
LOG_PATH      = os.path.join(BASE_DIR, "ibkr_bot.log")
SETTINGS_PATH = os.path.join(BASE_DIR, "user_settings.json")

# ─── Telegram ──────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8442918441:AAEZjhExbEzsP7nJtYlg_hL9eHebg08F59M")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "7910834714")

# ─── Bot Mode ─────────────────────────────────────────────────────────────
# 0 = OFF (bot does nothing)
# 1 = MONITOR (sends Telegram alerts, no execution links) ← DEFAULT
# 2 = EXECUTE (sends Telegram alerts WITH approval links for execution)
BOT_MODE_DEFAULT = 1

# ─── Webhook (LEAPS Roll alerts from external monitor) ─────────────────────
WEBHOOK_PORT    = int(os.getenv("WEBHOOK_PORT", 8502))
WEBHOOK_SECRET  = os.getenv("WEBHOOK_SECRET", "pmcc_leaps_webhook_2025")

# ─── Quant Engine Thresholds ───────────────────────────────────────────────
RSI_OVERSOLD         = 35
RSI_DEFENSIVE_LOW    = 40
RSI_DEFENSIVE_HIGH   = 50
RSI_NORMAL           = 60
BOLLINGER_WINDOW     = 20
BOLLINGER_STD        = 2.0
MA_PERIOD            = 200
SMA_SURVIVAL_PERIOD  = 150

# ─── Delta Targets per signal mode (from 20-year backtest) ────────────────
DELTA_TARGETS: Dict[str, float] = {
    "NO_TRADE":   0.00,
    "DEFENSIVE":  0.05,
    "NORMAL":     0.10,
    "AGGRESSIVE": 0.20,
}

HV30_AGGRESSIVE_THRESHOLD = 0.20

# ─── Delta health and rolling thresholds ──────────────────────────────────
DELTA_HEALTH_WARN  = 0.50
ROLL_UP_THRESHOLD  = 0.40
ROLL_DOWN_THRESHOLD = 0.05

# ─── Exit rules for short calls ───────────────────────────────────────────
TAKE_PROFIT_PCT  = 0.30
TIME_STOP_DAYS   = 21
SHORT_DTE_TARGET = 45

# ─── LEAPS management ─────────────────────────────────────────────────────
LEAPS_DTE_TARGET   = 540
LEAPS_DELTA_TARGET = 0.80
LEAPS_ROLL_DTE     = 360
LEAPS_EMERGENCY_DTE = 180   # Emergency roll target DTE

# ─── Cash Tank Thresholds ─────────────────────────────────────────────────
TANK_TARGET_PCT  = 0.30    # Blue Line: 30% of total LEAPS cost basis
TANK_WARNING_PCT = 0.20    # Yellow Line: 20%
TANK_FLOOR_PCT   = 0.15    # Red Line: 15% (fleet reduction trigger)
MONTHLY_SAVINGS_USD = 300

# ─── Expansion / Dip-Buy Rules ────────────────────────────────────────────
CORRECTION_THRESHOLD = -0.10  # -10% → watch
DIP_TRIGGER_A        = -0.20  # -20% → Tranche A (30% surplus per 10% drop)
DIP_TRIGGER_B        = -0.35  # -35% → Tranche B (aggressive)
TRANCHE_PCT          = 0.30   # 30% of free cash per tranche
VIX_AGGRESSIVE_ENTRY = 35.0   # VIX > 35 → deploy all free cash

# ─── Monitored Tickers for Expansion ─────────────────────────────────────
EXPANSION_TICKERS  = ["QQQ"]
WATCHLIST_TICKERS  = ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "QQQ", "QQQM"]

# ─── Order Execution ──────────────────────────────────────────────────────
ESCALATION_WAIT_MINUTES = 3
ESCALATION_STEP_PCT     = 1.0
ALGO_SPEEDS = ["Patient", "Normal", "Urgent"]

# ─── UI Color Palette ─────────────────────────────────────────────────────
COLORS = {
    "bg":         "#050810",
    "panel":      "#0e1525",
    "accent":     "#38bdf8",
    "accent2":    "#818cf8",
    "green":      "#34d399",
    "red":        "#f87171",
    "yellow":     "#fbbf24",
    "text":       "#f1f5f9",
    "text_muted": "#64748b",
    "border":     "#1a2540",
}

# ─── Fallback Demo Portfolio ───────────────────────────────────────────────
DEMO_POSITIONS = [
    {"ticker": "QQQ",  "type": "LEAPS",      "strike": 300.0, "expiry": "2027-01-15", "qty":  1, "delta": 0.80, "cost_basis": 110.00, "current_price": 125.00, "premium_received": 0.0,  "underlying_price": 415.00},
    {"ticker": "MSFT",  "type": "LEAPS",      "strike": 300.0, "expiry": "2027-01-15", "qty":  1, "delta": 0.80, "cost_basis": 110.00, "current_price": 125.00, "premium_received": 0.0,  "underlying_price": 415.00},
    {"ticker": "MSFT",  "type": "SHORT_CALL", "strike": 430.0, "expiry": "2026-06-19", "qty": -1, "delta": 0.10, "cost_basis":   0.00, "current_price":   5.50, "premium_received": 5.50, "underlying_price": 415.00},
    {"ticker": "GOOGL", "type": "LEAPS",      "strike": 100.0, "expiry": "2027-01-15", "qty":  1, "delta": 0.85, "cost_basis":  50.00, "current_price":  72.00, "premium_received": 0.0,  "underlying_price": 165.00},
    {"ticker": "GOOGL", "type": "SHORT_CALL", "strike": 175.0, "expiry": "2026-06-19", "qty": -1, "delta": 0.10, "cost_basis":   0.00, "current_price":   3.20, "premium_received": 3.20, "underlying_price": 165.00},
    {"ticker": "AMZN",  "type": "LEAPS",      "strike": 120.0, "expiry": "2027-01-15", "qty":  1, "delta": 0.78, "cost_basis":  45.00, "current_price":  60.00, "premium_received": 0.0,  "underlying_price": 175.00},
    {"ticker": "AMZN",  "type": "SHORT_CALL", "strike": 190.0, "expiry": "2026-06-19", "qty": -1, "delta": 0.05, "cost_basis":   0.00, "current_price":   2.80, "premium_received": 2.80, "underlying_price": 175.00},
    {"ticker": "META",  "type": "LEAPS",      "strike": 350.0, "expiry": "2027-01-15", "qty":  1, "delta": 0.81, "cost_basis": 130.00, "current_price": 155.00, "premium_received": 0.0,  "underlying_price": 490.00},
    {"ticker": "META",  "type": "SHORT_CALL", "strike": 520.0, "expiry": "2026-06-19", "qty": -1, "delta": 0.10, "cost_basis":   0.00, "current_price":   6.10, "premium_received": 6.10, "underlying_price": 490.00},
]
