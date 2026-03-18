"""
config.py — Central configuration for PMCC Quant-Dashboard
"""
from dataclasses import dataclass, field
from typing import Dict

# ─── TWS Connectivity ─────────────────────────────────────────────────────────
TWS_HOST = "127.0.0.1"
TWS_PORT_DEMO  = 7497   # Paper / Demo trading
TWS_PORT_LIVE  = 7496   # Live trading
TWS_CLIENT_ID  = 42

# ─── Quant Engine Thresholds ───────────────────────────────────────────────────
RSI_OVERSOLD          = 35      # Below → NO_TRADE
RSI_DEFENSIVE_LOW     = 40      # 40–50 → DEFENSIVE
RSI_DEFENSIVE_HIGH    = 50
RSI_NORMAL            = 60      # 60+ → AGGRESSIVE possible
BOLLINGER_WINDOW      = 20
BOLLINGER_STD         = 2.0
MA_PERIOD             = 200

# Delta targets per signal mode
DELTA_TARGETS: Dict[str, float] = {
    "NO_TRADE":  0.00,
    "DEFENSIVE": 0.12,
    "NORMAL":    0.30,
    "AGGRESSIVE":0.40,
}

# Delta health thresholds for rolling alerts
DELTA_HEALTH_WARN     = 0.50    # LEAPS delta - short delta below this → WARN
ROLL_UP_THRESHOLD     = 0.60    # Short call delta above → roll up (red)
ROLL_DOWN_THRESHOLD   = 0.10    # Short call delta below → roll down (yellow)

# ─── Order Execution ───────────────────────────────────────────────────────────
ESCALATION_WAIT_MINUTES = 3     # Wait before escalating mid→ask
ALGO_SPEEDS = ["Patient", "Normal", "Urgent"]

# ─── UI / Color Palette ────────────────────────────────────────────────────────
COLORS = {
    "bg":           "#0a0e1a",
    "panel":        "#111827",
    "accent":       "#00d4ff",
    "accent2":      "#7c3aed",
    "green":        "#10b981",
    "red":          "#ef4444",
    "yellow":       "#f59e0b",
    "text":         "#e2e8f0",
    "text_muted":   "#64748b",
    "border":       "#1e293b",
}

# ─── Demo Portfolio (no TWS) ──────────────────────────────────────────────────
DEMO_POSITIONS = [
    # NVDA
    {"ticker": "NVDA", "type": "LEAPS", "strike": 400.0, "expiry": "2026-01-16", "qty": 1, "delta": 0.82, "cost_basis": 145.30, "current_price": 162.50, "premium_received": 0.0, "underlying_price": 853.00},
    {"ticker": "NVDA", "type": "SHORT_CALL", "strike": 900.0, "expiry": "2025-03-21", "qty": -1, "delta": 0.28, "cost_basis": 0.0, "current_price": 8.40, "premium_received": 8.40, "underlying_price": 853.00},
    # AAPL
    {"ticker": "AAPL", "type": "LEAPS", "strike": 150.0, "expiry": "2026-01-16", "qty": 1, "delta": 0.76, "cost_basis": 38.20, "current_price": 41.00, "premium_received": 0.0, "underlying_price": 187.40},
    {"ticker": "AAPL", "type": "SHORT_CALL", "strike": 195.0, "expiry": "2025-03-21", "qty": -1, "delta": 0.08, "cost_basis": 0.0, "current_price": 1.20, "premium_received": 1.20, "underlying_price": 187.40},
    # TSLA
    {"ticker": "TSLA", "type": "LEAPS", "strike": 180.0, "expiry": "2026-01-16", "qty": 1, "delta": 0.79, "cost_basis": 72.50, "current_price": 88.10, "premium_received": 0.0, "underlying_price": 246.80},
    {"ticker": "TSLA", "type": "SHORT_CALL", "strike": 270.0, "expiry": "2025-03-21", "qty": -1, "delta": 0.63, "cost_basis": 0.0, "current_price": 14.20, "premium_received": 14.20, "underlying_price": 246.80},
    # MSFT
    {"ticker": "MSFT", "type": "LEAPS", "strike": 300.0, "expiry": "2026-01-16", "qty": 1, "delta": 0.80, "cost_basis": 110.00, "current_price": 125.00, "premium_received": 0.0, "underlying_price": 415.00},
    {"ticker": "MSFT", "type": "SHORT_CALL", "strike": 430.0, "expiry": "2025-03-21", "qty": -1, "delta": 0.30, "cost_basis": 0.0, "current_price": 5.50, "premium_received": 5.50, "underlying_price": 415.00},
    # GOOGL   
    {"ticker": "GOOGL", "type": "LEAPS", "strike": 100.0, "expiry": "2026-01-16", "qty": 1, "delta": 0.85, "cost_basis": 50.00, "current_price": 72.00, "premium_received": 0.0, "underlying_price": 165.00},
    {"ticker": "GOOGL", "type": "SHORT_CALL", "strike": 175.0, "expiry": "2025-03-21", "qty": -1, "delta": 0.35, "cost_basis": 0.0, "current_price": 3.20, "premium_received": 3.20, "underlying_price": 165.00},
    # AMZN
    {"ticker": "AMZN", "type": "LEAPS", "strike": 120.0, "expiry": "2026-01-16", "qty": 1, "delta": 0.78, "cost_basis": 45.00, "current_price": 60.00, "premium_received": 0.0, "underlying_price": 175.00},
    {"ticker": "AMZN", "type": "SHORT_CALL", "strike": 190.0, "expiry": "2025-03-21", "qty": -1, "delta": 0.25, "cost_basis": 0.0, "current_price": 2.80, "premium_received": 2.80, "underlying_price": 175.00},
    # META
    {"ticker": "META", "type": "LEAPS", "strike": 350.0, "expiry": "2026-01-16", "qty": 1, "delta": 0.81, "cost_basis": 130.00, "current_price": 155.00, "premium_received": 0.0, "underlying_price": 490.00},
    {"ticker": "META", "type": "SHORT_CALL", "strike": 520.0, "expiry": "2025-03-21", "qty": -1, "delta": 0.28, "cost_basis": 0.0, "current_price": 6.10, "premium_received": 6.10, "underlying_price": 490.00},
    # UNH
    {"ticker": "UNH", "type": "LEAPS", "strike": 400.0, "expiry": "2026-01-16", "qty": 1, "delta": 0.75, "cost_basis": 95.00, "current_price": 110.00, "premium_received": 0.0, "underlying_price": 495.00},
    {"ticker": "UNH", "type": "SHORT_CALL", "strike": 530.0, "expiry": "2025-03-21", "qty": -1, "delta": 0.22, "cost_basis": 0.0, "current_price": 4.50, "premium_received": 4.50, "underlying_price": 495.00},
]
