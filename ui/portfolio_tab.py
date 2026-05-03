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
        "action": "אל תמכור קול כרגע (דלתא 0.00) — המניה oversold ועלולה לקפוץ",
    },
    "DEFENSIVE": {
        "css": "sig-defensive",
        "badge": "sig-badge-defensive",
        "action_css": "sig-action-defensive",
        "icon": "🛡️",
        "label": "DEFENSIVE",
        "action": "מכור קול דלתא נמוכה (0.05) — זהירות, מגמה חלשה",
    },
    "NORMAL": {
        "css": "sig-normal",
        "badge": "sig-badge-normal",
        "action_css": "sig-action-normal",
        "icon": "✅",
        "label": "NORMAL",
        "action": "מכור קול בדלתא 0.10 — תנאים טובים לאסטרטגיה",
    },
    "AGGRESSIVE": {
        "css": "sig-aggressive",
        "badge": "sig-badge-aggressive",
        "action_css": "sig-action-aggressive",
        "icon": "🚀",
        "label": "AGGRESSIVE",
        "action": "ניתן למכור קול בדלתא 0.20 — מומנטום חזק ותנודתיות גבוהה",
    },
}


# --- Black-Scholes Mathematics ---
import numpy as np
from scipy.stats import norm
from datetime import datetime

def _bs_calc(S, K, T, r, sigma, right="C"):
    T = max(T, 0.001); sigma = max(sigma, 0.001)
    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    if right == "C":
        price = S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
        delta = norm.cdf(d1)
    else:
        price = K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)
        delta = norm.cdf(d1) - 1.0
    return price, delta

def _calc_iv(target_price, S, K, T, r, right="C"):
    if target_price <= 0 or S <= 0 or K <= 0 or T <= 0: return 0.0
    low, high = 0.001, 2.5
    for _ in range(25):
        mid = (low + high) / 2
        price, _ = _bs_calc(S, K, T, r, mid, right)
        if price > target_price: high = mid
        else: low = mid
    return (low + high) / 2


@st.cache_data(ttl=600, show_spinner=False)
def _fetch_vol_data(ticker: str, strike: float, expiry_str: str, right: str = "C"):
    """
    Fetch from yfinance with a persistent, spoofed session to prevent 401 Unauthorized errors.
    """
    try:
        import yfinance as yf
        import numpy as np
        import requests

        # --- התיקון: יצירת סשן מתחזה לדפדפן כדי למנוע 401 ---
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive"
        })
        
        # שימוש בסשן בתוך האובייקט של יאהו
        yf_t = yf.Ticker(ticker, session=session)

        # 1. Spot price
        try:
            spot = float(yf_t.fast_info.last_price or yf_t.fast_info.previous_close or 0)
        except Exception:
            spot = 0.0

        # 2. HV30 – annualised σ of log-returns over last 30 trading days
        hv30 = 0.0
        try:
            hist = yf_t.history(period="3mo", interval="1d")
            if hist is not None and len(hist) >= 20:
                closes = hist["Close"].dropna().values
                log_rets = np.diff(np.log(closes))
                hv30 = float(np.std(log_rets[-30:]) * np.sqrt(252)) if len(log_rets) >= 20 else 0.0
        except Exception:
            pass

        # 3. IV – from option chain mid-price, then Black-Scholes inversion
        iv = 0.0
        iv_source = "—"
        try:
            if len(expiry_str) == 8:  # YYYYMMDD
                exp_fmt = f"{expiry_str[:4]}-{expiry_str[4:6]}-{expiry_str[6:8]}"
            else:
                exp_fmt = expiry_str[:10]

            avail = yf_t.options
            if avail:
                nearest = min(avail, key=lambda x: abs((
                    datetime.strptime(x, "%Y-%m-%d") -
                    datetime.strptime(exp_fmt, "%Y-%m-%d")
                ).days))
                chain = yf_t.option_chain(nearest)
                df = chain.calls if right.upper() == "C" else chain.puts
                if df is not None and not df.empty:
                    row = df.iloc[(df["strike"] - strike).abs().argsort().iloc[0]]
                    bid = float(row.get("bid", 0) or 0)
                    ask = float(row.get("ask", 0) or 0)
                    iv_yf = float(row.get("impliedVolatility", 0) or 0)

                    if bid > 0 and ask > 0:
                        mid = (bid + ask) / 2
                        dte_days = max(1, (datetime.strptime(nearest, "%Y-%m-%d") - datetime.utcnow()).days)
                        if spot > 0:
                            iv = _calc_iv(mid, spot, strike, dte_days / 365.0, 0.04, right.upper())
                            iv_source = "BS inversion (bid/ask mid)"
                    if iv == 0.0 and iv_yf > 0:
                        iv = iv_yf
                        iv_source = "yfinance direct"
        except Exception:
            pass

        return {"spot": spot, "hv30": hv30, "iv": iv, "iv_source": iv_source}

    except Exception as e:
        return {"spot": 0.0, "hv30": 0.0, "iv": 0.0, "iv_source": f"error: {str(e)}"}


def render_portfolio_tab(positions: list, quant_results: dict) -> None:
    import settings_manager as _sm

    # ── Memory Panel (collapsed) ────────────────────────────────────────────
    with st.expander("📁 תיקי זיכרון — DEMO / LIVE", expanded=False):
        _mode = st.session_state.get("positions_source", "DEMO")
        col_pm1, col_pm2 = st.columns(2)
        with col_pm1:
            snap_d = _sm.get_portfolio_snapshot("DEMO")
            ts_d   = _sm.get_portfolio_last_updated("DEMO") or "לא נשמר"
            st.markdown(f'<div class="kpi-card"><div class="kpi-label">תיק DEMO</div>'
                        f'<div class="kpi-val" style="color:#f59e0b;font-size:1rem;">{len(snap_d)} פוזיציות</div>'
                        f'<div class="kpi-sub">{ts_d[:16] if ts_d != "לא נשמר" else "לא נשמר"}</div></div>',
                        unsafe_allow_html=True)
            if st.button("📂 טען DEMO", key="load_demo_snap", use_container_width=True):
                if snap_d:
                    st.session_state["positions"] = snap_d
                    st.session_state["positions_source"] = "DEMO"
                    st.rerun()
        with col_pm2:
            snap_l = _sm.get_portfolio_snapshot("LIVE")
            ts_l   = _sm.get_portfolio_last_updated("LIVE") or "לא נשמר"
            st.markdown(f'<div class="kpi-card"><div class="kpi-label">תיק LIVE</div>'
                        f'<div class="kpi-val" style="color:#10b981;font-size:1rem;">{len(snap_l)} פוזיציות</div>'
                        f'<div class="kpi-sub">{ts_l[:16] if ts_l != "לא נשמר" else "לא נשמר"}</div></div>',
                        unsafe_allow_html=True)
            if st.button("📂 טען LIVE", key="load_live_snap", use_container_width=True):
                if snap_l:
                    st.session_state["positions"] = snap_l
                    st.session_state["positions_source"] = "LIVE"
                    st.rerun()

    # ── KPI Row ────────────────────────────────────────────────────────────
    leaps = [p for p in positions if p.get("type") == "LEAPS"]
    calls = [p for p in positions if p.get("type") in ("SHORT", "SHORT_CALL")]
    total_leaps_qty = sum(abs(p.get("qty", 1)) for p in leaps)
    total_calls_qty = sum(abs(p.get("qty", 1)) for p in calls)
    premium    = sum(abs(p.get("current_price", 0)) * 100 * abs(p.get("qty", 1)) for p in calls)
    cost_basis = sum(abs(p.get("cost_basis", 1)) * 100 * abs(p.get("qty", 1)) for p in leaps) or 1
    leaps_val  = sum(abs(p.get("current_price", p.get("cost_basis", 0))) * 100 * abs(p.get("qty", 1)) for p in leaps)
    roc        = (premium / cost_basis * 100) if cost_basis else 0
    uncovered  = sum(1 for lp in leaps if not any(s.get("ticker") == lp.get("ticker") for s in calls))

    st.markdown(f"""
    <div class="kpi-row" style="grid-template-columns:repeat(5,1fr);margin-top:0.8rem;">
      <div class="kpi-card">
        <div class="kpi-label">LEAPS בצי</div>
        <div class="kpi-val" style="color:#0ea5e9;">{total_leaps_qty}</div>
        <div class="kpi-sub">חוזי Long Call</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">שורטים פעילים</div>
        <div class="kpi-val" style="color:#8b5cf6;">{total_calls_qty}</div>
        <div class="kpi-sub">Short Calls</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">ללא כיסוי</div>
        <div class="kpi-val" style="color:{'#f43f5e' if uncovered else '#10b981'};">{uncovered}</div>
        <div class="kpi-sub">LEAPS ללא שורט</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">פרמיה כוללת</div>
        <div class="kpi-val" style="color:#10b981;">${premium:,.0f}</div>
        <div class="kpi-sub">ערך שורטים</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">ROC</div>
        <div class="kpi-val" style="color:#a78bfa;">{roc:.1f}%</div>
        <div class="kpi-sub">פרמיה / עלות</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown('<div class="sec-hdr" style="margin-top:1rem;">📊 צי ה-LEAPS — פוזיציות פעילות</div>', unsafe_allow_html=True)


    # ── Group positions by ticker ──────────────────────────────────────────────
    tickers = []
    seen = set()
    for p in positions:
        t = p.get("ticker", "")
        if t and t not in seen:
            tickers.append(t)
            seen.add(t)

    # ── Render one card per ticker ───────────────────────
    for ticker in tickers:
        ticker_pos = [p for p in positions if p.get("ticker") == ticker]
        leaps_list = [p for p in ticker_pos if p.get("type") == "LEAPS"]
        short_list = [p for p in ticker_pos if p.get("type") in ("SHORT", "SHORT_CALL")]
        
        total_ticker_leaps = sum(abs(p.get("qty", 1)) for p in leaps_list)

        qr = quant_results.get(ticker)
        has_qr = qr is not None

        def _get(obj, attr, default=None):
            if hasattr(obj, attr): return getattr(obj, attr)
            if isinstance(obj, dict): return obj.get(attr, default)
            return default

        sig_key   = _get(qr, "signal", "DEFENSIVE") if has_qr else "DEFENSIVE"
        rsi_val   = _get(qr, "rsi") if has_qr else None
        ma200_val = _get(qr, "ma200") if has_qr else None
        close_val = _get(qr, "close") if has_qr else None
        hv30_val  = _get(qr, "hv30") if has_qr else 0.25
        delta_tgt = _get(qr, "delta_target", 0.0) if has_qr else 0.0
        
        raw_rsn = _get(qr, "reasoning", []) if has_qr else []
        reasoning = raw_rsn[-1] if isinstance(raw_rsn, list) and raw_rsn else (raw_rsn if isinstance(raw_rsn, str) and raw_rsn != "[]" else "")

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

        # PnL Aggregation
        total_pnl = sum(p.get("pnl", p.get("unrealizedPNL", 0)) for p in ticker_pos)
        pnl_color = "#34d399" if total_pnl >= 0 else "#f87171"
        pnl_sign  = "+" if total_pnl >= 0 else ""

        # Construct pairs HTML
        pairs_html = ""
        if sum(abs(p.get("qty", 1)) for p in leaps_list) == 0 and sum(abs(p.get("qty", 1)) for p in short_list) == 0:
            pairs_html = "<div style='color:#94a3b8; font-size:0.9rem;'>אין כרגע פוזיציות פעילות או שורט קולים מוגנים במנייה זו.</div>"
            
        # Draw physical pairs by duplicating positions by their quantity for visual pairing
        visual_leaps = []
        for lp in leaps_list:
            visual_leaps.extend([lp] * abs(lp.get("qty", 1)))
            
        visual_shorts = []
        for sp in short_list:
            visual_shorts.extend([sp] * abs(sp.get("qty", 1)))
        
        available_shorts = list(visual_shorts)
        
        # Fetch real-time fallback data (Spot, HV30) if quant results are missing
        vol_baseline = _fetch_vol_data(ticker, 0, "", "C")
        ticker_spot = close_val if close_val else vol_baseline.get("spot", 0)
        ticker_hv30 = hv30_val if hv30_val and hv30_val > 0.01 else vol_baseline.get("hv30", 0.25)

        for leaps_p in visual_leaps:
            matched_short = available_shorts.pop(0) if available_shorts else None
            
            # Warn if LEAPS is close to 360 days (roughly 1 year)
            dte = leaps_p.get("dte", 999)
            if dte == 999 and leaps_p.get("expiry"):
                try: dte = (datetime.strptime(leaps_p["expiry"], "%Y%m%d") - datetime.utcnow()).days
                except: pass
            
            roll_warning = ""
            if dte <= 390: # Alert slightly before 360
                roll_warning = f"<div style='color:#ef4444; margin-bottom:4px;'>🚨 IMMEDIATE ROLL REQUIRED (DTE {dte:.0f} &lt; 360)</div>"
                
            pairs_html += f"""<div style="display:flex; flex-direction:column; gap:8px; background:rgba(0,0,0,0.2); padding:10px; border-radius:8px; margin-bottom:12px; border:1px solid rgba(255,255,255,0.05);">{roll_warning}<div style="display:flex; gap:16px; flex-wrap:wrap; align-items:stretch;">{_pos_mini("Long LEAPS", leaps_p, ticker_spot, ticker_hv30)}<div style="display:flex; align-items:center; color:#475569; font-size:1.5rem;">🔗</div>{_pos_mini("Covering Short", matched_short, ticker_spot, ticker_hv30)}</div></div>"""
            
        # Draw remaining naked shorts (if any bug caused them)
        for naked_short in available_shorts:
             pairs_html += f"""<div style="display:flex; flex-direction:column; gap:8px; background:rgba(239, 68, 68, 0.1); padding:10px; border-radius:8px; margin-bottom:12px; border:1px solid #ef4444;"><div style="color:#ef4444; margin-bottom:4px;">⚠️ NAKED SHORT CALL DETECTED</div><div style="display:flex; gap:16px; flex-wrap:wrap;">{_pos_mini("Covering Short", naked_short, ticker_spot, ticker_hv30)}</div></div>"""

        st.markdown(f"""<div class="sig-card {meta['css']}">
<!-- Row 1: Ticker + Badge + Price -->
<div style="display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:8px;">
<div style="display:flex; align-items:center; gap:12px;">
<span class="sig-ticker">{ticker}</span>
<span class="sig-signal-badge {meta['badge']}">{meta['icon']} {meta['label']}</span>
</div>
<div style="text-align:right;">
<div class="sig-label">Gross PnL</div>
<div class="sig-price" style="color:{pnl_color}">{pnl_sign}${total_pnl:,.0f}</div>
</div>
</div>
<!-- Row 2: Chips -->
<div class="chip-row">
{_chip("Market Price", f"${close_val:.2f}" if close_val else "—")}
{_chip("RSI", f"{rsi_val:.1f}" if rsi_val else "—")}
{_chip("Fleet Size", f"{total_ticker_leaps} LEAPS")}
{_chip("Target Δ", f"{delta_tgt:.2f}" if delta_tgt else "—")}
</div>
<!-- Row 3: LEAPS & Short Calls Fleet -->
<div style="margin-top:1rem;">{pairs_html}</div>
<!-- Row 4: Reason + Action -->
<div class="sig-reason" style="margin-top:0.8rem;">
<div style="color:#f8fafc; font-size:0.85rem; font-weight:500;">💡 איתות מערכת:</div>
<div style="color:#94a3b8; font-size:0.78rem;">{reason_str}</div>
<div class="sig-action-text {meta['action_css']}" style="margin-top:0.4rem;">
{meta['icon']} {meta['action']}
</div>
</div>
</div>""", unsafe_allow_html=True)

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


def _pos_mini(role: str, pos: Optional[dict], underlying_price: float = 0.0, hv30: float = 0.0) -> str:
    if not pos:
        return (
            '<div style="background:rgba(255,255,255,0.03);border:1px dashed rgba(255,255,255,0.15);'
            'border-radius:12px;padding:1.2rem;flex:1;min-width:200px;text-align:center;display:flex;align-items:center;justify-content:center;">'
            '<div style="color:#475569;font-size:0.85rem;">📭 החוזה פנוי<br><span style="font-size:0.75rem;color:#334155;">ניתן למכור שורט קול</span></div>'
            '</div>'
        )

    strike      = float(pos.get("strike") or 0)
    expiry      = pos.get("expiry", "—") or "—"
    price       = float(pos.get("current_price") or pos.get("price") or 0)
    avg_cost    = float(pos.get("cost_basis") or pos.get("avgCost") or pos.get("averageCost") or 0)
    qty_total   = int(pos.get("qty") or 1)
    right       = str(pos.get("right") or "C").upper()

    # ── 1. Expiry & DTE ──────────────────────────────────────────
    dte = int(pos.get("dte") or 0)
    if dte == 0 and type(expiry) == str and len(expiry) >= 8:
        try:
            fmt = "%Y%m%d" if len(expiry) == 8 else "%Y-%m-%d"
            dte = max(0, (datetime.strptime(expiry.replace("-",""), "%Y%m%d") - datetime.utcnow()).days)
        except Exception:
            dte = 0

    clean_expiry = expiry
    if type(expiry) == str and len(expiry) == 8:
        try: clean_expiry = datetime.strptime(expiry, "%Y%m%d").strftime("%d/%m/%Y")
        except: pass

    dte_color = "#ef4444" if dte < 21 else ("#f59e0b" if dte < 45 else ("#38bdf8" if dte > 270 else "#10b981"))
    dte_label = "🚨 גלגל עכשיו!" if dte < 21 else ("⚠️ מיד" if dte < 45 else "✅ בטוח")

    # ── 2. Delta & Greeks ────────────────────────────────────────
    delta = float(pos.get("delta") or 0.0)
    iv    = 0.0
    theta = 0.0

    _up  = float(underlying_price or 0)
    _str = float(strike or 0)
    _prc = float(price or 0)
    _dte = int(dte or 0)

    if _up > 0 and _str > 0 and _prc > 0 and _dte > 0:
        T = _dte / 365.0
        iv = _calc_iv(_prc, _up, _str, T, 0.04, right)
        if iv > 0:
            if delta == 0.0:
                _, delta = _bs_calc(_up, _str, T, 0.04, iv, right)
            # Theta approx: dC/dt ≈ -BS_price / (2*T)  (rough but visual)
            theta = -_prc / max(_dte, 1) * 0.1

    delta_abs = abs(delta)
    delta_pct = min(100, delta_abs * 100 * (1 if right == "C" else 1))
    if role == "Covering Short":
        delta_bar_color = "#ef4444" if delta_abs >= 0.40 else ("#f59e0b" if delta_abs >= 0.25 else "#10b981")
    else:
        delta_bar_color = "#38bdf8" if delta_abs >= 0.70 else ("#10b981" if delta_abs >= 0.50 else "#f59e0b")

    # ── 3. Cost vs Current Value ─────────────────────────────────
    pnl = float(pos.get("unrealizedPNL") or pos.get("unrealized_pnl") or 0)
    if pnl == 0 and price and avg_cost:
        # For short calls, profit = we sold high and it's worth less now
        if role == "Covering Short":
            pnl = (avg_cost - price) * 100
        else:
            pnl = (price - avg_cost) * 100
    pnl_color = "#10b981" if pnl >= 0 else "#ef4444"
    pnl_sign  = "+" if pnl >= 0 else ""

    # Value bars
    contract_value_now  = abs(price) * 100
    contract_cost_basis = abs(avg_cost) * 100

    # ── 4. IV vs HV comparison ───────────────────────────────────
    _hv = float(hv30 or 0)
    iv_pct  = min(100, iv  * 200) if iv > 0 else 0
    hv_pct  = min(100, _hv * 200) if _hv > 0 else 0
    iv_state = "—"
    iv_state_color = "#94a3b8"

    if iv > 0 and _hv > 0:
        if iv > _hv + 0.05:
            iv_state = "גבוהה — פרמיה יקרה 🟢"
            iv_state_color = "#10b981"
        elif iv < _hv - 0.05:
            iv_state = "נמוכה — פרמיה זולה 🔴"
            iv_state_color = "#ef4444"
        else:
            iv_state = "הוגנת ⚪"
            iv_state_color = "#94a3b8"
    
    # In Sandbox/Demo mode with no internet, provide a descriptive message
    no_data_msg = ""
    if iv <= 0 or _hv <= 0:
        no_data_msg = '<div style="font-size:0.65rem;color:#475569;font-style:italic;margin-bottom:4px;">(מחשב תנודתיות מ-YFinance...)</div>'

    iv_bar_html = f"""
<div style="margin-top:8px;padding-top:6px;border-top:1px solid rgba(255,255,255,0.06);">
<div style="font-size:0.68rem;color:#64748b;margin-bottom:3px;">📊 תנודתיות שולס (IV) מול תנודתיות היסטורית (HV30)</div>
{no_data_msg}
<div style="display:flex;gap:4px;align-items:center;margin-bottom:2px; opacity:{0.4 if not iv else 1.0};">
<span style="font-size:0.65rem;color:#94a3b8;width:22px;">IV</span>
<div style="flex:1;background:#1e293b;border-radius:3px;height:7px;overflow:hidden;">
<div style="width:{iv_pct:.0f}%;background:#818cf8;height:100%;border-radius:3px;"></div>
</div>
<span style="font-size:0.68rem;color:#818cf8;width:38px;text-align:right;">{iv*100:.1f}%</span>
</div>
<div style="display:flex;gap:4px;align-items:center; opacity:{0.4 if not _hv else 1.0};">
<span style="font-size:0.65rem;color:#94a3b8;width:22px;">HV</span>
<div style="flex:1;background:#1e293b;border-radius:3px;height:7px;overflow:hidden;">
<div style="width:{hv_pct:.0f}%;background:#f59e0b;height:100%;border-radius:3px;"></div>
</div>
<span style="font-size:0.68rem;color:#f59e0b;width:38px;text-align:right;">{_hv*100:.1f}%</span>
</div>
<div style="font-size:0.68rem;color:{iv_state_color};margin-top:3px;">תנודתיות: {iv_state}</div>
</div>"""

    # ── 5. Card borders based on role & risk ─────────────────────
    if role == "Covering Short":
        if delta_abs >= 0.40:
            border = "2px solid #ef4444"
            bg     = "background:rgba(239,68,68,0.08);"
        else:
            border = "1px solid rgba(129,140,248,0.3)"
            bg     = "background:rgba(129,140,248,0.05);"
        role_color = "#818cf8"
        role_icon  = "📞"
    else:
        border = "1px solid rgba(56,189,248,0.3)"
        bg     = "background:rgba(56,189,248,0.05);"
        role_color = "#38bdf8"
        role_icon  = "🏔️"

    theta_str = f"θ {theta:.4f}/יום" if theta != 0.0 else ""

    return (
        f'<div style="{bg}border:{border};border-radius:12px;padding:0.8rem 1rem;flex:1;min-width:220px;">'

        # Header: Role + Qty
        f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">'
        f'  <span style="font-size:0.72rem;font-weight:700;color:{role_color};text-transform:uppercase;letter-spacing:.05em;">'
        f'    {role_icon} {role}</span>'
        f'  <span style="font-size:0.68rem;background:rgba(255,255,255,0.06);padding:2px 7px;border-radius:20px;color:#94a3b8;">'
        f'    {abs(qty_total)}x חוזה</span>'
        f'</div>'

        # Strike (big)
        f'<div style="font-size:1.3rem;font-weight:900;color:#f1f5f9;letter-spacing:-0.5px;">Strike ${strike:.0f}</div>'

        # ── Section 1 & 4: Dates ──
        f'<div style="display:flex;justify-content:space-between;align-items:center;margin-top:6px;">'
        f'  <div>'
        f'    <div style="font-size:0.65rem;color:#475569;">📅 תאריך פקיעה</div>'
        f'    <div style="font-size:0.78rem;color:#cbd5e1;font-weight:600;">{clean_expiry}</div>'
        f'  </div>'
        f'  <div style="text-align:right;">'
        f'    <div style="font-size:0.65rem;color:#475569;">⏳ ימים לפקיעה (DTE)</div>'
        f'    <div style="font-size:0.78rem;font-weight:700;color:{dte_color};">{dte}d  {dte_label}</div>'
        f'  </div>'
        f'</div>'

        # ── Section 2: Delta bar ──
        f'<div style="margin-top:8px;">'
        f'  <div style="display:flex;justify-content:space-between;margin-bottom:2px;">'
        f'    <span style="font-size:0.68rem;color:#64748b;">Delta (Δ)</span>'
        f'    <span style="font-size:0.72rem;font-weight:700;color:{delta_bar_color};">Δ {delta_abs:.3f}'
        f'      {(" " + theta_str) if theta_str else ""}</span>'
        f'  </div>'
        f'  <div style="background:#1e293b;border-radius:4px;height:8px;overflow:hidden;">'
        f'    <div style="width:{delta_pct:.0f}%;background:{delta_bar_color};height:100%;border-radius:4px;transition:width .5s;"></div>'
        f'  </div>'
        f'</div>'

        # ── Section 3: Cost vs Current ──
        f'<div style="margin-top:8px;padding-top:6px;border-top:1px solid rgba(255,255,255,0.06);">'
        f'  <div style="display:flex;justify-content:space-between;">'
        f'    <div>'
        f'      <div style="font-size:0.65rem;color:#475569;">💰 עלות רכישה</div>'
        f'      <div style="font-size:0.78rem;color:#94a3b8;">${avg_cost:.2f} <span style="font-size:0.65rem;">(${contract_cost_basis:.0f}/חוזה)</span></div>'
        f'    </div>'
        f'    <div style="text-align:right;">'
        f'      <div style="font-size:0.65rem;color:#475569;">📈 שווי שוק כעת</div>'
        f'      <div style="font-size:0.78rem;color:#e2e8f0;font-weight:600;">${price:.2f} <span style="font-size:0.65rem;">(${contract_value_now:.0f}/חוזה)</span></div>'
        f'    </div>'
        f'  </div>'
        f'  <div style="display:flex;justify-content:space-between;align-items:center;margin-top:5px;">'
        f'    <span style="font-size:0.68rem;color:#475569;">רווח / הפסד לא ממומש:</span>'
        f'    <span style="font-size:0.85rem;font-weight:800;color:{pnl_color};">{pnl_sign}${pnl:.0f}</span>'
        f'  </div>'
        f'</div>'

        # ── Section 5: IV vs HV ──
        f'{iv_bar_html}'

        f'</div>'
    )



