"""
ui/portfolio_tab.py — Signal cards per position (colour-coded by Quant signal)
"""
import streamlit as st
import pandas as pd
from typing import Optional

import config


# ── Signal meta ───────────────────────────────────────────────────────────────
_SIG_META = {
    "NO_TRADE": {
        "css": "sig-no-trade",
        "badge": "sig-badge-no-trade",
        "action_css": "sig-action-no-trade",
        "icon": "⛔",
        "label": "NO TRADE",
        "action": "אל תמכור קול כרגע — המניה oversold ועלולה לקפוץ",
    },
    "DEFENSIVE": {
        "css": "sig-defensive",
        "badge": "sig-badge-defensive",
        "action_css": "sig-action-defensive",
        "icon": "🛡️",
        "label": "DEFENSIVE",
        "action": "מכור קול דלטא נמוכה (0.10–0.15) — זהירות, מגמה חלשה",
    },
    "NORMAL": {
        "css": "sig-normal",
        "badge": "sig-badge-normal",
        "action_css": "sig-action-normal",
        "icon": "✅",
        "label": "NORMAL",
        "action": "מכור קול בדלטא 0.25–0.35 — תנאים טובים לאסטרטגיה",
    },
    "AGGRESSIVE": {
        "css": "sig-aggressive",
        "badge": "sig-badge-aggressive",
        "action_css": "sig-action-aggressive",
        "icon": "🚀",
        "label": "AGGRESSIVE",
        "action": "ניתן למכור קול בדלטא 0.35–0.45 — מגמה חזקה",
    },
}


def render_portfolio_tab(positions: list, quant_results: dict) -> None:
    # ── Top summary bar ────────────────────────────────────────────────────────
    leaps = [p for p in positions if p.get("type") == "LEAPS"]
    calls = [p for p in positions if p.get("type") == "SHORT"]
    premium = sum(abs(p.get("price", 0)) * 100 * abs(p.get("qty", 1))
                  for p in calls)
    cost_basis = sum(p.get("cost", 1) * 100 for p in leaps) or 1
    roc = premium / cost_basis * 100

    c1, c2, c3, c4 = st.columns(4)
    _metric(c1, "LEAPS",         str(len(leaps)),   "#38bdf8")
    _metric(c2, "Short Calls",   str(len(calls)),   "#818cf8")
    _metric(c3, "Premium",       f"${premium:,.0f}", "#34d399")
    _metric(c4, "Return/Cost",   f"{roc:.1f}%",     "#fbbf24")

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown('<div class="section-hdr">📊 פוזיציות ואותות מסחר</div>',
                unsafe_allow_html=True)

    # ── Group positions by ticker ──────────────────────────────────────────────
    tickers = []
    seen = set()
    for p in positions:
        t = p.get("ticker", "")
        if t and t not in seen:
            tickers.append(t)
            seen.add(t)

    # ── Render one card per ticker (pairs LEAPS + SHORT) ───────────────────────
    for ticker in tickers:
        ticker_pos = [p for p in positions if p.get("ticker") == ticker]
        leaps_p = next((p for p in ticker_pos if p.get("type") == "LEAPS"), None)
        short_p = next((p for p in ticker_pos if p.get("type") == "SHORT"), None)

        # Determine signal — quant_results values are QuantResult dataclasses
        qr = quant_results.get(ticker)
        sig_key = "DEFENSIVE"
        rsi_val   = None
        ma200_val = None
        close_val = None
        delta_tgt = 0.0
        reasoning = ""

        if qr is not None:
            # Support both dataclass and dict
            def _get(obj, attr, default=None):
                if hasattr(obj, attr):
                    return getattr(obj, attr)
                if isinstance(obj, dict):
                    return obj.get(attr, default)
                return default

            sig_key   = _get(qr, "signal", "DEFENSIVE")
            rsi_val   = _get(qr, "rsi")
            ma200_val = _get(qr, "ma200")
            close_val = _get(qr, "close")
            delta_tgt = _get(qr, "delta_target", 0.0)
            raw_rsn   = _get(qr, "reasoning", [])
            if isinstance(raw_rsn, list):
                reasoning = raw_rsn[-1] if raw_rsn else ""
            else:
                reasoning = str(raw_rsn)

        if sig_key not in _SIG_META:
            sig_key = "DEFENSIVE"
        meta = _SIG_META[sig_key]

        # Build a short human reason
        reason_parts = []
        if rsi_val is not None:
            emoji = "🔴" if rsi_val < 35 else ("🟡" if rsi_val < 50 else "🟢")
            reason_parts.append(f"RSI {rsi_val:.1f} {emoji}")
        if close_val and ma200_val:
            rel = "מעל MA200" if close_val > ma200_val else "מתחת MA200"
            emoji = "🟢" if close_val > ma200_val else "🔴"
            reason_parts.append(f"{rel} ({ma200_val:.0f}) {emoji}")
        if reasoning:
            reason_parts.append(reasoning)
        reason_str = " · ".join(reason_parts) if reason_parts else "ממתין לניתוח — לחץ Run Quant Analysis"

        # PnL
        short_pnl  = short_p.get("pnl", 0) if short_p else 0
        leaps_pnl  = leaps_p.get("pnl", 0) if leaps_p else 0
        total_pnl  = short_pnl + leaps_pnl
        pnl_color  = "#34d399" if total_pnl >= 0 else "#f87171"
        pnl_sign   = "+" if total_pnl >= 0 else ""

        # Delta health
        leaps_delta = leaps_p.get("delta", 0) if leaps_p else 0
        short_delta = abs(short_p.get("delta", 0)) if short_p else 0
        health      = leaps_delta - short_delta
        health_col  = "#34d399" if health > 0.5 else ("#fbbf24" if health > 0.25 else "#f87171")

        st.markdown(f"""
        <div class="sig-card {meta['css']}">
          <!-- Row 1: Ticker + Badge + Price -->
          <div style="display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:8px;">
            <div style="display:flex; align-items:center; gap:12px;">
              <span class="sig-ticker">{ticker}</span>
              <span class="sig-signal-badge {meta['badge']}">{meta['icon']} {meta['label']}</span>
            </div>
            <div style="text-align:right;">
              <div class="sig-label">PnL</div>
              <div class="sig-price" style="color:{pnl_color}">{pnl_sign}${total_pnl:,.0f}</div>
            </div>
          </div>

          <!-- Row 2: Chips -->
          <div class="chip-row">
            {_chip("מחיר", f"${close_val:.2f}" if close_val else "—")}
            {_chip("RSI", f"{rsi_val:.1f}" if rsi_val else "—")}
            {_chip("MA200", f"${ma200_val:.0f}" if ma200_val else "—")}
            {_chip_color("Delta Health", f"{health:.2f}", health_col)}
            {_chip("Target Δ", f"{delta_tgt:.2f}" if delta_tgt else "—")}
            {_chip("LEAPS Δ", f"{leaps_delta:.2f}")}
            {_chip("Short Δ", f"{short_delta:.2f}")}
          </div>

          <!-- Row 3: LEAPS & Short Calls detail -->
          <div style="display:flex; gap:16px; flex-wrap:wrap; margin-top:0.6rem;">
            {_pos_mini("LEAPS", leaps_p)}
            {_pos_mini("Short Call", short_p)}
          </div>

          <!-- Row 4: Reason + Action -->
          <div class="sig-reason">
            <div style="color:#94a3b8; font-size:0.78rem;">{reason_str}</div>
            <div class="sig-action-text {meta['action_css']}" style="margin-top:0.4rem;">
              {meta['icon']} {meta['action']}
            </div>
          </div>
        </div>
        """, unsafe_allow_html=True)

    # Spacer
    st.markdown("<br>", unsafe_allow_html=True)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _metric(col, label: str, value: str, color: str) -> None:
    with col:
        st.markdown(f"""
        <div class="metric-card">
          <div class="sig-label">{label}</div>
          <div class="metric-val" style="color:{color}">{value}</div>
        </div>""", unsafe_allow_html=True)


def _chip(label: str, value: str) -> str:
    return f'<span class="chip"><strong>{label}:</strong> {value}</span>'


def _chip_color(label: str, value: str, color: str) -> str:
    return (f'<span class="chip">'
            f'<strong>{label}:</strong> '
            f'<span style="color:{color};font-weight:700">{value}</span>'
            f'</span>')


def _pos_mini(role: str, pos: Optional[dict]) -> str:
    if not pos:
        return (f'<div style="background:rgba(255,255,255,0.03);border:1px solid '
                f'rgba(255,255,255,0.07);border-radius:10px;padding:0.5rem 0.8rem;flex:1;min-width:140px;">'
                f'<div class="sig-label">{role}</div>'
                f'<div style="color:#475569;font-size:0.82rem;">—</div>'
                f'</div>')
    strike = pos.get("strike", "—")
    expiry = pos.get("expiry", "—")
    price  = pos.get("price", 0)
    qty    = pos.get("qty", 0)
    return (f'<div style="background:rgba(255,255,255,0.03);border:1px solid '
            f'rgba(255,255,255,0.07);border-radius:10px;padding:0.5rem 0.8rem;flex:1;min-width:140px;">'
            f'<div class="sig-label">{role}</div>'
            f'<div style="font-size:1rem;font-weight:700;color:#f1f5f9;">${strike}</div>'
            f'<div style="font-size:0.72rem;color:#64748b;">{expiry} &nbsp;|&nbsp; '
            f'${price:.2f} &nbsp;|&nbsp; qty {qty:+d}</div>'
            f'</div>')
