"""
quant_engine.py — Adaptive 3-Tier Delta Engine + comprehensive PMCC alerts
"""
import logging
from typing import Dict, List, Callable, Optional
from datetime import datetime, date
from dataclasses import dataclass

import config
from data_feed import compute_technicals

logger = logging.getLogger(__name__)

SIGNAL_NO_TRADE   = "NO_TRADE"
SIGNAL_DEFENSIVE  = "DEFENSIVE"
SIGNAL_NORMAL     = "NORMAL"
SIGNAL_AGGRESSIVE = "AGGRESSIVE"

SIGNAL_COLORS = {
    SIGNAL_NO_TRADE:   "#ef4444",
    SIGNAL_DEFENSIVE:  "#f59e0b",
    SIGNAL_NORMAL:     "#10b981",
    SIGNAL_AGGRESSIVE: "#00d4ff",
}


@dataclass
class QuantResult:
    ticker:          str
    signal:          str
    delta_target:    float
    delta_health:    float
    delta_health_ok: bool
    rsi:             float
    ma200:           float
    close:           float
    bb_lower:        float
    bb_upper:        float
    hv30:            float
    above_ma200:     bool
    at_bb_lower:     bool
    drawdown_pct:    float
    reasoning:       List[str]
    alerts:          List[str]
    timestamp:       str
    ma150:           float = 0.0
    above_ma150:     bool = False
    cross_above_150: bool = False


class QuantEngine:
    def __init__(self):
        self._log_queue: List[Dict] = []
        self._external_cb: Optional[Callable] = None

    def set_log_callback(self, fn: Callable[[str, str], None]) -> None:
        self._external_cb = fn

    def _emit(self, level: str, msg: str) -> None:
        entry = {"level": level, "msg": msg,
                 "ts": datetime.utcnow().strftime("%H:%M:%S")}
        self._log_queue.append(entry)
        logger.info(msg)
        if self._external_cb:
            self._external_cb(level, msg)

    def flush_logs(self) -> List[Dict]:
        entries = list(self._log_queue)
        self._log_queue.clear()
        return entries

    def analyse_ticker(
        self, ticker: str,
        leaps_delta: float = 0.80,
        short_delta: float = 0.10,
        leaps_expiry: Optional[str] = None,
        short_entry_price: Optional[float] = None,
        short_current_price: Optional[float] = None,
        short_entry_date: Optional[str] = None,
    ) -> QuantResult:
        self._emit("INFO", f"=== Analysing {ticker} ===")
        try:
            tech = compute_technicals(ticker)
        except Exception as e:
            msg = f"  [{ticker}] SYSTEM BLOCK: {e}"
            self._emit("BLOCK", msg)
            return QuantResult(
                ticker=ticker, signal=SIGNAL_NO_TRADE,
                delta_target=0.0, delta_health=0.0, delta_health_ok=False,
                rsi=0.0, ma200=0.0, close=0.0, bb_lower=0.0, bb_upper=0.0,
                hv30=0.0, above_ma200=False, at_bb_lower=False, drawdown_pct=0.0,
                reasoning=[msg], alerts=[msg],
                timestamp=datetime.utcnow().isoformat(),
            )

        rsi         = tech["rsi"]
        close       = tech["close"]
        ma200       = tech["ma200"]
        bb_lower    = tech["bb_lower"]
        bb_upper    = tech["bb_upper"]
        above_ma200 = tech["above_ma200"]
        at_bb_lower = tech["at_bb_lower"]
        hv30        = tech.get("hv30", 0.25)
        high52      = tech.get("high52", close)
        drawdown    = (close - high52) / high52 if high52 > 0 else 0.0

        self._emit("INFO",
            f"  [{ticker}] Close=${close:.2f}  RSI={rsi:.1f}  "
            f"MA200=${ma200:.2f}  HV30={hv30:.1%}  DD={drawdown:.1%}")

        reasoning: List[str] = []
        alerts:    List[str] = []
        signal = SIGNAL_NORMAL

        # NO_TRADE conditions
        if rsi < config.RSI_OVERSOLD:
            signal = SIGNAL_NO_TRADE
            msg = (f"  [{ticker}] RSI={rsi:.1f} < {config.RSI_OVERSOLD} "
                   f"-> OVERSOLD -> Blocking short call sale")
            self._emit("BLOCK", msg); reasoning.append(msg)

        elif at_bb_lower:
            signal = SIGNAL_NO_TRADE
            msg = f"  [{ticker}] Price at BB Lower ({bb_lower:.2f}) -> Blocking"
            self._emit("BLOCK", msg); reasoning.append(msg)

        elif drawdown < -0.15 and not above_ma200:
            signal = SIGNAL_NO_TRADE
            msg = f"  [{ticker}] Drawdown {drawdown:.1%} + below MA200 -> Macro Sidelining"
            self._emit("BLOCK", msg); reasoning.append(msg)

        # ADAPTIVE 3-TIER — Aggressive (delta 0.20)
        elif (above_ma200 and rsi > config.RSI_NORMAL
              and hv30 >= config.HV30_AGGRESSIVE_THRESHOLD):
            signal = SIGNAL_AGGRESSIVE
            msg = (f"  [{ticker}] AGGRESSIVE: RSI={rsi:.1f}>65, "
                   f"HV30={hv30:.1%}>20% -> Delta 0.20")
            self._emit("INFO", msg); reasoning.append(msg)

        # Normal (delta 0.10)
        elif above_ma200 and rsi > config.RSI_DEFENSIVE_HIGH:
            signal = SIGNAL_NORMAL
            msg = f"  [{ticker}] NORMAL: RSI={rsi:.1f} 50-65, above MA200 -> Delta 0.10"
            self._emit("INFO", msg); reasoning.append(msg)

        # Defensive (delta 0.05)
        elif config.RSI_DEFENSIVE_LOW <= rsi <= config.RSI_DEFENSIVE_HIGH and above_ma200:
            signal = SIGNAL_DEFENSIVE
            msg = f"  [{ticker}] DEFENSIVE: RSI={rsi:.1f} in 40-50 -> Delta 0.05"
            self._emit("WARN", msg); reasoning.append(msg)

        else:
            signal = SIGNAL_DEFENSIVE
            msg = f"  [{ticker}] DEFENSIVE: Below MA200 or ambiguous"
            self._emit("WARN", msg); reasoning.append(msg)

        # --- Action Alerts ---

        # Roll Emergency (delta >= 0.40)
        if abs(short_delta) >= config.ROLL_UP_THRESHOLD:
            alerts.append(
                f"ROLL EMERGENCY [{ticker}]: Short delta "
                f"{abs(short_delta):.2f} >= {config.ROLL_UP_THRESHOLD}. "
                f"Buy back immediately and re-sell at delta "
                f"{config.DELTA_TARGETS.get(signal, 0.10):.2f}."
            )
            self._emit("BLOCK", f"  [{ticker}] ROLL EMERGENCY! Short delta {abs(short_delta):.2f}")

        # Take Profit (30%)
        if short_entry_price and short_current_price and short_entry_price > 0:
            gained_pct = 1.0 - (short_current_price / short_entry_price)
            if gained_pct >= config.TAKE_PROFIT_PCT:
                profit = (short_entry_price - short_current_price) * 100
                alerts.append(
                    f"TAKE PROFIT [{ticker}]: "
                    f"Gained {gained_pct:.0%} (target {config.TAKE_PROFIT_PCT:.0%}). "
                    f"Close for ~${profit:.0f} profit."
                )
                self._emit("INFO", f"  [{ticker}] TAKE PROFIT: {gained_pct:.0%}")

        # Time Stop (21 days)
        if short_entry_date:
            try:
                entry_dt = datetime.fromisoformat(short_entry_date[:10]).date()
                days_held = (date.today() - entry_dt).days
                if days_held >= config.TIME_STOP_DAYS:
                    alerts.append(
                        f"TIME STOP [{ticker}]: "
                        f"Short held {days_held} days (max {config.TIME_STOP_DAYS}). "
                        f"Close unconditionally."
                    )
                    self._emit("WARN", f"  [{ticker}] TIME STOP: {days_held}d")
            except Exception:
                pass

        # LEAPS Roll Alert (<= 360 DTE)
        if leaps_expiry:
            try:
                exp_dt = datetime.strptime(leaps_expiry[:10], "%Y-%m-%d").date()
                dte = (exp_dt - date.today()).days
                if dte <= config.LEAPS_ROLL_DTE:
                    alerts.append(
                        f"LEAPS ROLL [{ticker}]: "
                        f"{dte} DTE remaining (threshold {config.LEAPS_ROLL_DTE}). "
                        f"Sell old LEAPS, buy new 540-DTE at Delta 0.80."
                    )
                    self._emit("WARN", f"  [{ticker}] LEAPS ROLL due: {dte} DTE")
            except Exception:
                pass

        # Dip-Buy Triggers
        if drawdown <= config.DIP_TRIGGER_B:
            alerts.append(
                f"DIP-BUY TRANCHE B [{ticker}]: "
                f"Stock down {drawdown:.1%} from 52W high. "
                f"Deploy remaining 50% of reserve -> buy LEAPS."
            )
        elif drawdown <= config.DIP_TRIGGER_A:
            alerts.append(
                f"DIP-BUY TRANCHE A [{ticker}]: "
                f"Stock down {drawdown:.1%} from 52W high. "
                f"Deploy first 50% of reserve for this ticker -> buy LEAPS."
            )

        # Delta Health
        delta_health = leaps_delta - abs(short_delta)
        health_ok    = delta_health >= config.DELTA_HEALTH_WARN
        dh_msg = (f"  [{ticker}] Delta Health = {leaps_delta:.2f} - "
                  f"{abs(short_delta):.2f} = {delta_health:.2f} "
                  f"{'OK' if health_ok else 'BELOW 0.50 - at risk!'}")
        self._emit("WARN" if not health_ok else "INFO", dh_msg)
        reasoning.append(dh_msg)

        delta_target = config.DELTA_TARGETS.get(signal, 0.10)
        self._emit("INFO", f"  [{ticker}] Signal: {signal}  Target delta: {delta_target}")

        return QuantResult(
            ticker=ticker, signal=signal, delta_target=delta_target,
            delta_health=delta_health, delta_health_ok=health_ok,
            rsi=rsi, ma200=ma200, close=close, bb_lower=bb_lower, bb_upper=bb_upper,
            hv30=hv30, above_ma200=above_ma200, at_bb_lower=at_bb_lower,
            drawdown_pct=drawdown, reasoning=reasoning, alerts=alerts,
            timestamp=datetime.utcnow().isoformat(),
            ma150=tech.get("ma150", 0.0),
            above_ma150=tech.get("above_ma150", False),
            cross_above_150=tech.get("cross_above_150", False)
        )

    def analyse_portfolio(self, positions: List[Dict], watchlist: List[str] = None) -> Dict[str, QuantResult]:
        self._emit("INFO", f"Quant Engine started - {len(positions)} positions")
        results: Dict[str, QuantResult] = {}
        by_ticker: Dict[str, Dict] = {}

        # 1. Existing positions
        for pos in positions:
            t = pos.get("ticker")
            if not t: continue
            if t not in by_ticker:
                by_ticker[t] = {
                    "leaps_delta": 0.80, "short_delta": 0.10,
                    "leaps_expiry": None, "short_entry_price": None,
                    "short_current_price": None, "short_entry_date": None,
                }
            if pos.get("type") == "LEAPS":
                by_ticker[t]["leaps_delta"] = pos.get("delta", 0.80)
                by_ticker[t]["leaps_expiry"] = pos.get("expiry")
            elif pos.get("type") in ("SHORT_CALL", "SHORT"):
                by_ticker[t]["short_delta"]         = abs(pos.get("delta", 0.10))
                by_ticker[t]["short_entry_price"]   = pos.get("cost_basis") or pos.get("premium_received")
                by_ticker[t]["short_current_price"] = pos.get("current_price")
                by_ticker[t]["short_entry_date"]    = pos.get("entry_date")

        # 2. Watchlist integration (tickers that we don't hold yet but want to analyze)
        if watchlist:
            for t in watchlist:
                t = t.strip().upper()
                if t and t not in by_ticker:
                    by_ticker[t] = {
                        "leaps_delta": 0.80, "short_delta": 0.10,
                        "leaps_expiry": None, "short_entry_price": None,
                        "short_current_price": None, "short_entry_date": None,
                    }

        for ticker, d in by_ticker.items():
            import time, random
            sleep_t = 3.0 + random.uniform(1.0, 3.0)
            time.sleep(sleep_t)
            results[ticker] = self.analyse_ticker(ticker, **d)

        self._emit("INFO", "Quant Engine complete.")
        return results


_engine = QuantEngine()

def get_engine() -> QuantEngine:
    return _engine
