"""
quant_engine.py — Scoring engine: RSI, Bollinger, MA200, Delta Health Monitor
"""
import logging
from typing import Dict, List, Callable, Optional
from datetime import datetime
from dataclasses import dataclass

import config
from data_feed import compute_technicals

logger = logging.getLogger(__name__)

# ─── Signal Definitions ───────────────────────────────────────────────────────

SIGNAL_NO_TRADE   = "NO_TRADE"
SIGNAL_DEFENSIVE  = "DEFENSIVE"
SIGNAL_NORMAL     = "NORMAL"
SIGNAL_AGGRESSIVE = "AGGRESSIVE"

SIGNAL_COLORS = {
    SIGNAL_NO_TRADE:   "#ef4444",   # red
    SIGNAL_DEFENSIVE:  "#f59e0b",   # yellow
    SIGNAL_NORMAL:     "#10b981",   # green
    SIGNAL_AGGRESSIVE: "#00d4ff",   # cyan
}


@dataclass
class QuantResult:
    ticker:          str
    signal:          str        # one of the four signals
    delta_target:    float
    delta_health:    float      # LEAPS_delta - short_delta
    delta_health_ok: bool
    rsi:             float
    ma200:           float
    close:           float
    bb_lower:        float
    bb_upper:        float
    above_ma200:     bool
    at_bb_lower:     bool
    reasoning:       List[str]  # Log lines for Machine Thinking Console
    timestamp:       str


class QuantEngine:
    """
    Analyses each PMCC position pair and emits trading signals.
    Logs reasoning to an internal queue consumed by the Console UI.
    """

    def __init__(self):
        self._log_queue: List[Dict] = []      # [{"level": str, "msg": str}]
        self._external_cb: Optional[Callable] = None

    def set_log_callback(self, fn: Callable[[str, str], None]) -> None:
        self._external_cb = fn

    def _emit(self, level: str, msg: str) -> None:
        entry = {
            "level": level,
            "msg": msg,
            "ts": datetime.utcnow().strftime("%H:%M:%S"),
        }
        self._log_queue.append(entry)
        logger.info(msg)
        if self._external_cb:
            self._external_cb(level, msg)

    def flush_logs(self) -> List[Dict]:
        """Return and clear accumulated log entries."""
        entries = list(self._log_queue)
        self._log_queue.clear()
        return entries

    # ─── Main Analysis ────────────────────────────────────────────────────────

    def analyse_ticker(self, ticker: str,
                       leaps_delta: float = 0.80,
                       short_delta: float = 0.30) -> QuantResult:
        """
        Run full technical analysis for one ticker.
        Returns QuantResult with signal + reasoning.
        """
        self._emit("INFO", f"━━━ Analysing {ticker} ━━━")
        tech = compute_technicals(ticker)

        rsi       = tech["rsi"]
        close     = tech["close"]
        ma200     = tech["ma200"]
        bb_lower  = tech["bb_lower"]
        bb_upper  = tech["bb_upper"]
        above_ma200 = tech["above_ma200"]
        at_bb_lower = tech["at_bb_lower"]

        self._emit("INFO",  f"  [{ticker}] Close=${close:.2f}  RSI={rsi:.1f}  "
                            f"MA200=${ma200:.2f}  BB_Low=${bb_lower:.2f}")

        reasoning: List[str] = []
        signal = SIGNAL_NORMAL   # default

        # ── NO_TRADE conditions ───────────────────────────────────────────────
        if rsi < config.RSI_OVERSOLD:
            signal = SIGNAL_NO_TRADE
            msg = (f"  [{ticker}] RSI={rsi:.1f} < {config.RSI_OVERSOLD} → "
                   f"OVERSOLD → ⛔ Blocking Call Sale (whipsaw risk)")
            self._emit("BLOCK", msg)
            reasoning.append(msg)

        elif at_bb_lower:
            signal = SIGNAL_NO_TRADE
            msg = (f"  [{ticker}] Price touches/breaks BB Lower (${bb_lower:.2f}) → "
                   f"⛔ Blocking Call Sale (downtrend risk)")
            self._emit("BLOCK", msg)
            reasoning.append(msg)

        # ── DEFENSIVE conditions ──────────────────────────────────────────────
        elif (config.RSI_DEFENSIVE_LOW <= rsi <= config.RSI_DEFENSIVE_HIGH
              and above_ma200):
            signal = SIGNAL_DEFENSIVE
            msg = (f"  [{ticker}] RSI={rsi:.1f} in defensive zone [40-50] "
                   f"+ price above MA200 → 🛡️  Sell delta ≈ "
                   f"{config.DELTA_TARGETS[SIGNAL_DEFENSIVE]} for theta-only")
            self._emit("WARN", msg)
            reasoning.append(msg)

        # ── NORMAL market ─────────────────────────────────────────────────────
        elif above_ma200 and rsi > config.RSI_DEFENSIVE_HIGH:
            signal = SIGNAL_NORMAL
            msg = (f"  [{ticker}] Stable/bullish: price above MA200, "
                   f"RSI={rsi:.1f} → ✅ Sell delta ≈ "
                   f"{config.DELTA_TARGETS[SIGNAL_NORMAL]}")
            self._emit("INFO", msg)
            reasoning.append(msg)

        else:
            signal = SIGNAL_DEFENSIVE
            msg    = (f"  [{ticker}] Below MA200 or ambiguous → 🛡️  Defensive mode")
            self._emit("WARN", msg)
            reasoning.append(msg)

        # ── Delta Health ──────────────────────────────────────────────────────
        delta_health = leaps_delta - abs(short_delta)
        health_ok    = delta_health >= config.DELTA_HEALTH_WARN

        dh_msg = (f"  [{ticker}] Delta Health = {leaps_delta:.2f} - "
                  f"{abs(short_delta):.2f} = {delta_health:.2f} "
                  f"{'✅ OK' if health_ok else '🚨 BELOW 0.50 – strategy structure at risk!'}")
        self._emit("WARN" if not health_ok else "INFO", dh_msg)
        reasoning.append(dh_msg)

        delta_target = config.DELTA_TARGETS[signal]
        self._emit("INFO", f"  [{ticker}] → Signal: {signal}  "
                            f"Target delta: {delta_target}")

        return QuantResult(
            ticker=ticker,
            signal=signal,
            delta_target=delta_target,
            delta_health=delta_health,
            delta_health_ok=health_ok,
            rsi=rsi,
            ma200=ma200,
            close=close,
            bb_lower=bb_lower,
            bb_upper=bb_upper,
            above_ma200=above_ma200,
            at_bb_lower=at_bb_lower,
            reasoning=reasoning,
            timestamp=datetime.utcnow().isoformat(),
        )

    def analyse_portfolio(self, positions: List[Dict]) -> Dict[str, QuantResult]:
        """
        Analyse all unique tickers in a position list.
        Pairs LEAPS + SHORT_CALL for delta health calculation.
        """
        self._emit("INFO", f"🧠 Quant Engine started — {len(positions)} positions")
        results: Dict[str, QuantResult] = {}

        # Group by ticker
        by_ticker: Dict[str, Dict] = {}
        for pos in positions:
            t = pos["ticker"]
            if t not in by_ticker:
                by_ticker[t] = {"leaps_delta": 0.80, "short_delta": 0.30}
            if pos["type"] == "LEAPS":
                by_ticker[t]["leaps_delta"] = pos.get("delta", 0.80)
            elif pos["type"] == "SHORT_CALL":
                by_ticker[t]["short_delta"] = abs(pos.get("delta", 0.30))

        for ticker, deltas in by_ticker.items():
            result = self.analyse_ticker(
                ticker,
                leaps_delta=deltas["leaps_delta"],
                short_delta=deltas["short_delta"],
            )
            results[ticker] = result

        self._emit("INFO", "🧠 Quant Engine analysis complete.")
        return results


# Singleton
_engine = QuantEngine()


def get_engine() -> QuantEngine:
    return _engine
