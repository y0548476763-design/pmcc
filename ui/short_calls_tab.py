"""
ui/short_calls_tab.py — Tab 2: Short Calls Engine
All IBKR actions go through api_ibkr (:8002).
Option chain search uses api_yahoo (:8001).
"""
import requests
import streamlit as st
from datetime import datetime
from typing import Optional
import config
import settings_manager
import api_ibkr
import api_yahoo


# ── Signal meta ────────────────────────────────────────────────────────────
_SIG_META = {
    "NO_TRADE":   {"icon": "⛔", "label": "NO TRADE",   "color": "#f87171", "delta": 0.00},
    "DEFENSIVE":  {"icon": "🛡️", "label": "DEFENSIVE",  "color": "#fbbf24", "delta": 0.05},
    "NORMAL":     {"icon": "✅", "label": "NORMAL",      "color": "#34d399", "delta": 0.10},
    "AGGRESSIVE": {"icon": "🚀", "label": "AGGRESSIVE",  "color": "#38bdf8", "delta": 0.20},
}


def _get_dte(expiry_str: str) -> int:
    try:
        fmt = "%Y%m%d" if len(str(expiry_str).replace("-", "")) == 8 else "%Y-%m-%d"
        exp = datetime.strptime(str(expiry_str).replace("-", ""), "%Y%m%d")
        return max(0, (exp.date() - datetime.utcnow().date()).days)
    except Exception:
        return 999


def _send_telegram(msg: str) -> bool:
    """Send a Telegram message. Returns True on success."""
    # Always notify internal hub first
    api_ibkr.notify(msg)

    try:
        import requests
        token   = settings_manager.get_telegram_token()
        chat_id = settings_manager.get_telegram_chat_id()
        url     = f"https://api.telegram.org/bot{token}/sendMessage"
        r = requests.post(url, json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"},
                          timeout=8)
        return r.status_code == 200
    except Exception:
        return False


def render_short_calls_tab(positions: list, quant_results: dict, tws=None) -> None:

    # ── Header ────────────────────────────────────────────────────────────
    st.markdown("""
<div style="padding:0.2rem 0 1rem 0;">
<div class="pmcc-title">📞 מנוע השורט קולים</div>
<div style="font-size:0.72rem;color:#64748b;margin-top:3px;">
ניהול מכירת, גלגול, ורווח שורט קולים — כל הפעולות לפי כללי PMCC המוגדרים
</div>
</div>
""", unsafe_allow_html=True)

    bot_mode = settings_manager.get_bot_mode()

    # ── Rules Panel ────────────────────────────────────────────────────────
    with st.expander("⚙️ כללי מכירה וגלגול (לחץ לעריכה)", expanded=False):
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            tp_pct = st.number_input("Take Profit %", 10, 80,
                                     int(settings_manager.get_rule("take_profit_pct", 30)),
                                     step=5, help="סגירת שורט לאחר X% רווח")
            if st.button("💾 שמור TP", key="save_tp_short"):
                settings_manager.set_rule("take_profit_pct", tp_pct)
                st.success("נשמר!")
        with c2:
            time_stop = st.number_input("Time Stop (ימים)", 7, 60,
                                        int(settings_manager.get_rule("time_stop_days", 21)),
                                        help="סגירה חובה X ימים לפני פקיעה")
            if st.button("💾 שמור TS", key="save_ts_short"):
                settings_manager.set_rule("time_stop_days", time_stop)
                st.success("נשמר!")
        with c3:
            delta_roll = st.slider("גלגול דלתא", 0.20, 0.60,
                                   float(settings_manager.get_rule("delta_roll_threshold", 0.40)),
                                   step=0.01, help="גלגול מיידי אם דלתא עוברת ערך זה")
            if st.button("💾 שמור Δ", key="save_dr_short"):
                settings_manager.set_rule("delta_roll_threshold", delta_roll)
                st.success("נשמר!")
        with c4:
            short_dte = st.number_input("יעד DTE שורט", 20, 90,
                                        int(settings_manager.get_rule("short_dte_target", 45)),
                                        help="מכירה ל-X ימים לפניה")
            if st.button("💾 שמור DTE", key="save_dte_short"):
                settings_manager.set_rule("short_dte_target", short_dte)
                st.success("נשמר!")

        st.markdown("""
<div style="font-size:0.72rem;color:#64748b;margin-top:0.5rem;direction:rtl;">
📝 <b>זכור:</b> פקודות המכירה נשלחות כ-Limit חכם עם הסלמה לכיוון הביד — 
מחיר אמצע → ביד בכל X דקות. פקודות Take Profit נשלחות מיד לאחר מכירה (GTC Limit).
</div>
""", unsafe_allow_html=True)

    tp_pct    = settings_manager.get_rule("take_profit_pct", 30) / 100.0
    time_stop = settings_manager.get_rule("time_stop_days", 21)
    delta_roll= settings_manager.get_rule("delta_roll_threshold", 0.40)
    short_dte = settings_manager.get_rule("short_dte_target", 45)

    leaps  = [p for p in positions if p.get("type") == "LEAPS"]
    shorts = [p for p in positions if p.get("type") in ("SHORT_CALL", "SHORT")]

    covered_tickers = {s.get("ticker") for s in shorts}

    # ── ROW 1: Status Overview ─────────────────────────────────────────────
    n_leaps    = len(leaps)
    n_shorts   = len(shorts)
    n_uncovered = sum(1 for l in leaps if l.get("ticker") not in covered_tickers)
    n_roll_due  = sum(1 for s in shorts
                      if _get_dte(s.get("expiry","")) <= time_stop
                      or abs(float(s.get("delta",0))) >= delta_roll)
    total_prem  = sum(abs(float(s.get("current_price",0)))*100*abs(s.get("qty",1)) for s in shorts)

    c1, c2, c3, c4, c5 = st.columns(5)
    def _kpi(col, label, val, color, sub=""):
        with col:
            st.markdown(f"""
<div class="kpi-card">
<div class="kpi-label">{label}</div>
<div class="kpi-val" style="color:{color};">{val}</div>
<div class="kpi-sub">{sub}</div>
</div>""", unsafe_allow_html=True)

    _kpi(c1, "LEAPS בצי",        str(n_leaps),                 "#38bdf8", "חוזי Long Call")
    _kpi(c2, "שורטים פעילים",    str(n_shorts),                "#818cf8", "Short Calls")
    _kpi(c3, "לא מכוסים ⚠️",     str(n_uncovered),             "#f87171" if n_uncovered else "#34d399", "LEAPS ללא שורט")
    _kpi(c4, "דורשים גלגול 🔄",   str(n_roll_due),              "#fbbf24" if n_roll_due else "#34d399", "DTE<21 או Δ≥0.4")
    _kpi(c5, "פרמיה כוללת",      f"${total_prem:,.0f}",        "#34d399", "ערך שורטים כעת")

    st.markdown("<br>", unsafe_allow_html=True)

    # ── ROW 2: Uncovered LEAPS — Recommendations ───────────────────────────
    uncovered = [l for l in leaps if l.get("ticker") not in covered_tickers]
    if uncovered:
        st.markdown('<div class="section-hdr">🔍 LEAPS ללא כיסוי — מומלץ למכור שורט קול</div>',
                    unsafe_allow_html=True)
        for lp in uncovered:
            ticker = lp.get("ticker", "")
            qr     = quant_results.get(ticker)
            sig    = getattr(qr, "signal", "DEFENSIVE") if qr else "DEFENSIVE"
            meta   = _SIG_META.get(sig, _SIG_META["DEFENSIVE"])

            if sig == "NO_TRADE":
                st.markdown(f"""
<div class="alert-box alert-high" style="direction:rtl;">
⛔ <b>{ticker}</b> — האיתות הוא NO_TRADE. אל תמכור שורט קול עכשיו.
המנוע חוסם מסחר: RSI נמוך / מתחת BB תחתון / ירידה עמוקה.
</div>""", unsafe_allow_html=True)
                continue

            tgt_delta = meta["delta"]

            col_info, col_btn = st.columns([3, 1])
            with col_info:
                underlying = float(lp.get("underlying_price", 0))
                strike_lp  = float(lp.get("strike", 0))
                cost_basis = float(lp.get("cost_basis", 0))
                breakeven  = strike_lp + cost_basis
                st.markdown(f"""
<div class="alert-box alert-info" style="direction:rtl;">
{meta['icon']} <b>{ticker}</b> —
<span class="badge" style="background:rgba(56,189,248,0.12);color:{meta['color']};
border:1px solid {meta['color']};">{meta['label']}</span>
&nbsp; מכור שורט קול ב-<b style="color:{meta['color']};">Δ {tgt_delta:.2f}</b>
&nbsp;|&nbsp; יעד DTE: <b>{short_dte}</b> ימים
&nbsp;|&nbsp; מחיר מניה: <b>${underlying:.1f}</b>
&nbsp;|&nbsp; Breakeven: <b>${breakeven:.1f}</b>
</div>""", unsafe_allow_html=True)

            with col_btn:
                st.write("")
                if st.button(f"🔍 סרוק {ticker}", key=f"scan_{ticker}", use_container_width=True):
                    with st.spinner(f"מחפש שורט קול ל-{ticker} ב-api_yahoo..."):
                        try:
                            r = requests.get(f"{config.YAHOO_API_URL}/options/search",
                                             params={"ticker": ticker,
                                                     "min_dte": max(14, short_dte - 15),
                                                     "max_dte": short_dte + 20,
                                                     "target_delta": tgt_delta,
                                                     "right": "C",
                                                     "n": 3},
                                             timeout=20)
                            data = r.json()
                            chain = data.get("data", []) if data.get("ok") else []
                            if chain:
                                st.session_state[f"short_chain_{ticker}"] = chain
                            else:
                                st.error(f"לא נמצאו אופציות מתאימות ל-{ticker} (DTE {max(14,short_dte-15)}-{short_dte+20})")
                        except requests.exceptions.ConnectionError:
                            st.error("❌ api_yahoo לא פועל")
                        except Exception as e:
                            st.error(f"שגיאה: {e}")

            # Show chain results if available
            chain_res = st.session_state.get(f"short_chain_{ticker}", [])
            if chain_res:
                cols = st.columns(len(chain_res))
                for i, opt in enumerate(chain_res):
                    strike = float(opt.get("strike", 0))
                    expiry = opt.get("expiry", "")
                    mid    = float(opt.get("mid", 0))
                    delta  = float(opt.get("delta", 0))
                    dte_o  = _get_dte(expiry)
                    tp_price = round(mid * (1.0 - tp_pct), 2)

                    with cols[i]:
                        st.markdown(f"""
<div class="pmcc-card" style="border-top:3px solid {meta['color']};
padding:0.9rem;text-align:center;min-height:200px;">
<div style="font-size:0.62rem;color:#64748b;">אופציה {i+1}</div>
<div style="font-size:1.6rem;font-weight:900;color:#f1f5f9;">${strike:.0f}</div>
<div style="font-size:0.72rem;color:#64748b;">{expiry} · {dte_o}d</div>
<div style="margin:0.5rem 0;">
<span style="color:{meta['color']};font-weight:700;">Δ {delta:.3f}</span>
</div>
<div style="font-size:1.2rem;font-weight:800;color:#34d399;">Mid ${mid:.2f}</div>
<div style="font-size:0.7rem;color:#64748b;">TP Target: ${tp_price:.2f}</div>
</div>""", unsafe_allow_html=True)

                        if st.button("🚀 פתח שורט קול (SELL)", key=f"sell_{ticker}_{i}",
                                     use_container_width=True, type="primary"):
                            _execute_short_sell(tws, lp, opt, tp_pct, bot_mode)

    # ── ROW 3: Active Short Calls Management ───────────────────────────────
    if shorts:
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown('<div class="section-hdr">📋 שורט קולים פעילים — ניהול ובדיקת כללים</div>',
                    unsafe_allow_html=True)

        for sc in shorts:
            ticker  = sc.get("ticker", "")
            strike  = float(sc.get("strike", 0))
            expiry  = sc.get("expiry", "")
            delta   = abs(float(sc.get("delta", 0)))
            dte     = _get_dte(expiry)
            cur_px  = float(sc.get("current_price", 0.01))
            entry_px_raw = float(sc.get("cost_basis", 0) or sc.get("premium_received", cur_px))
            entry_px = entry_px_raw / 100.0 if entry_px_raw > 5 else (entry_px_raw if entry_px_raw > 0 else cur_px)
            profit_pct = (entry_px - cur_px) / entry_px if entry_px > 0 else 0

            # Status
            needs_tp   = profit_pct >= tp_pct
            needs_time = dte <= time_stop
            needs_roll = delta >= delta_roll
            is_ok      = not (needs_tp or needs_time or needs_roll)

            border = "#34d399" if is_ok else ("#f87171" if (needs_roll or dte <= 3) else "#fbbf24")
            status_badge = ""
            action_btn_label = ""
            if needs_tp:
                status_badge = f'<span class="badge badge-green">💰 TAKE PROFIT ({profit_pct:.0%})</span>'
                action_btn_label = "✅ בצע סגירת רווח (TP)"
            elif needs_time:
                status_badge = f'<span class="badge badge-yellow">⏰ TIME STOP ({dte}d)</span>'
                action_btn_label = "🔄 בצע גלגול שורט (Roll)"
            elif needs_roll:
                status_badge = f'<span class="badge badge-red">🚨 DELTA ROLL (Δ{delta:.2f})</span>'
                action_btn_label = "🔄 בצע גלגול שורט (Roll)"
            else:
                status_badge = f'<span class="badge badge-cyan">✅ תקין ({dte}d · Δ{delta:.2f})</span>'

            dte_color = "#f87171" if dte < 21 else ("#fbbf24" if dte < 35 else "#34d399")

            col_info, col_actions = st.columns([4, 1])
            with col_info:
                st.markdown(f"""
<div style="background:rgba(10,22,40,0.7);border:1px solid {border};
border-radius:14px;padding:0.9rem 1.2rem;margin-bottom:0.6rem;">
<div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;">
<span style="font-size:1.2rem;font-weight:900;color:#f1f5f9;">{ticker}</span>
<span style="font-size:0.85rem;color:#94a3b8;">Strike ${strike:.0f}</span>
<span style="font-size:0.75rem;color:{dte_color};">DTE {dte}d</span>
<span style="font-size:0.78rem;font-weight:700;color:{('#10b981' if profit_pct>0 else '#f87171')};">
{'+' if profit_pct>=0 else ''}{profit_pct:.1%} PnL
</span>
{status_badge}
</div>
<div style="display:flex;gap:16px;margin-top:8px;font-size:0.72rem;color:#64748b;">
<span>פקיעה: {expiry}</span>
<span>מחיר כניסה: ${entry_px:.2f}</span>
<span>מחיר כעת: ${cur_px:.2f}</span>
<span>Δ {delta:.3f}</span>
</div>
</div>""", unsafe_allow_html=True)

            with col_actions:
                if not is_ok and action_btn_label:
                    st.write("")
                    if st.button(action_btn_label, key=f"action_{ticker}_{strike}_{expiry}",
                                 use_container_width=True):
                        _handle_short_action(tws, sc, needs_tp, needs_time or needs_roll,
                                             positions, quant_results, bot_mode, short_dte)

    # ── ROW 4: Manual Order Entry ──────────────────────────────────────────
    st.markdown("<br>", unsafe_allow_html=True)
    with st.expander("🛠️ כניסה ידנית לפקודה", expanded=False):
        c1, c2, c3, c4, c5, c6 = st.columns(6)
        with c1:
            man_ticker = st.selectbox("מניה", config.WATCHLIST_TICKERS, key="man_sc_ticker")
        with c2:
            man_action = st.selectbox("פעולה", ["SELL", "BUY"], key="man_sc_action")
        with c3:
            man_strike = st.number_input("Strike", 1.0, 10000.0, 400.0, step=5.0, key="man_sc_strike")
        with c4:
            man_expiry = st.text_input("פקיעה (YYYY-MM-DD)", key="man_sc_expiry",
                                       placeholder="2026-06-20")
        with c5:
            man_mid = st.number_input("Mid Price", 0.01, 500.0, 5.0, step=0.05, key="man_sc_mid")
        with c6:
            man_qty = st.number_input("כמות", 1, 50, 1, key="man_sc_qty")

        esc_col1, esc_col2, esc_col3 = st.columns(3)
        with esc_col1:
            esc_mins = st.number_input("המתנה (דקות)", 1, 30, config.ESCALATION_WAIT_MINUTES, key="man_esc_mins_sc")
        with esc_col2:
            esc_step = st.number_input("הסלמה %", 0.1, 5.0, config.ESCALATION_STEP_PCT, step=0.1, key="man_esc_step_sc")

        if st.button("📤 שלח פקודה ידנית", key="man_send_sc", type="primary", use_container_width=True):
            if not man_expiry:
                st.error("יש להזין תאריך פקיעה")
            else:
                try:
                    payload = {
                        "ticker": man_ticker, "right": "C", "strike": man_strike,
                        "expiry": man_expiry, "action": man_action, "qty": man_qty,
                        "limit_price": man_mid, "order_type": "LMT", "tif": "DAY"
                    }
                    r = api_ibkr.place_order(payload["ticker"], payload["strike"], payload["expiry"], payload["right"], payload["action"], payload["qty"], payload.get("limit_price"))
                    if r.get("ok"):
                        st.success(f"✅ פקודה נשלחה: {r.get('order_id','')}")
                        if bot_mode >= 1:
                            _send_telegram(
                                f"📤 פקודה ידנית: {man_action} {man_qty}x {man_ticker} "
                                f"${man_strike:.0f} {man_expiry} @ ${man_mid:.2f}"
                            )
                    else:
                        st.error(f"שגיאה בשליחת פקודה: {r.get('error', r)}")
                except Exception as e:
                    st.error(f"שגיאת תקשורת: {e}")


# ── Helpers ────────────────────────────────────────────────────────────────

def _execute_short_sell(tws, leaps_pos: dict, opt: dict, tp_pct: float,
                        bot_mode: int) -> None:
    """Execute a short call sell order and immediately place Take Profit.
    bot_mode=0 (OFF):    Manual always executes. 'Bot' button blocks with warning.
    bot_mode=1 (YELLOW): 'Bot' sends Telegram confirmation, waits for YES.
    bot_mode=2 (GREEN):  'Bot' executes immediately, notifies after.
    """
    import order_manager
    ticker = leaps_pos.get("ticker", "")
    strike = float(opt.get("strike", 0))
    expiry = opt.get("expiry", "")
    mid    = float(opt.get("mid", 0))
    qty    = abs(leaps_pos.get("qty", 1))
    tp_price = max(0.01, round(mid * (1.0 - tp_pct), 2))

    om = order_manager.get_manager()
    om.set_tws(tws)

    # Notify if bot mode >= 1
    if bot_mode == 1:
        # Telegram confirmation
        msg = (f"❓ <b>האם לבצע מכירת שורט קול?</b>\n"
               f"📞 SELL {qty}x {ticker} ${strike:.0f}C {expiry}\n"
               f"💰 Mid: ${mid:.2f} | TP Target: ${tp_price:.2f}\n"
               f"⚡ ענה YES לאישור")
        if _send_telegram(msg):
            st.info("📱 הודעת אישור נשלחה לטלגרם")
        else:
            st.error("❌ שליחת טלגרם נכשלה")
        return

    # EXECUTE (manual always, or bot_mode>=2)
    if not st.session_state.get("connected"):
        st.error("❌ אין חיבור ל-IBKR — בדוק שה-Gateway פועל.")
        return

    try:
        # 1. Place Sell Order
        sell_payload = {
            "ticker": ticker, "strike": strike, "expiry": expiry, "right": "C",
            "action": "SELL", "qty": qty, "limit_price": mid,
            "order_type": "LMT", "tif": "DAY"
        }
        r_sell = api_ibkr.place_order(sell_payload["ticker"], sell_payload["strike"], sell_payload["expiry"], sell_payload["right"], sell_payload["action"], sell_payload["qty"], sell_payload.get("limit_price"))
        if not r_sell.get("ok"):
            st.error(f"כשל במכירה: {r_sell.get('error', r_sell)}")
            return
        oid = r_sell.get("order_id", "???")
        
        # 2. Place TP Order (GTC)
        if tp_price > 0:
            tp_payload = {
                "ticker": ticker, "strike": strike, "expiry": expiry, "right": "C",
                "action": "BUY", "qty": qty, "limit_price": tp_price,
                "order_type": "LMT", "tif": "GTC"
            }
            api_ibkr.place_order(tp_payload["ticker"], tp_payload["strike"], tp_payload["expiry"], tp_payload["right"], tp_payload["action"], tp_payload["qty"], tp_payload.get("limit_price"), tp_payload.get("order_type", "LMT"))

        msg = (f"🚀 <b>שורט קול נמכר!</b>\n"
               f"📞 SELL {qty}x {ticker} ${strike:.0f}C {expiry} @ ${mid:.2f}\n"
               f"🎯 פקודת TP נשלחה: ${tp_price:.2f}")
        if bot_mode >= 1:
            _send_telegram(msg)
        st.success(f"✅ פקודה נשלחה: {oid}")
    except Exception as e:
        st.error(f"שגיאת ביצוע: {e}")


def _handle_short_action(tws, sc: dict, is_tp: bool, is_roll: bool,
                         positions: list, quant_results: dict,
                         bot_mode: int, short_dte: int) -> None:
    """Handle TP close or Roll for an active short call."""
    ticker = sc.get("ticker", "")
    strike = float(sc.get("strike", 0))
    expiry = sc.get("expiry", "")
    cur_px = float(sc.get("current_price", 0.01))
    qty    = abs(sc.get("qty", 1))

    import order_manager
    om = order_manager.get_manager()
    om.set_tws(tws)

    action_word = "Take Profit" if is_tp else "גלגול שורט"

    if bot_mode == 1:
        # Send Telegram first
        msg = (f"{'💰' if is_tp else '🔄'} <b>{action_word} — {ticker}</b>\n"
               f"📞 BUY {qty}x {ticker} ${strike:.0f}C {expiry}\n"
               f"{'✅ רווח הושג!' if is_tp else '⚠️ DTE/Delta הצריכו גלגול'}\n"
               f"⚡ ענה YES לאישור")
        ok = _send_telegram(msg)
        st.info("📱 אישור נשלח לטלגרם!" if ok else "❌ שליחה נכשלה")
        return

    if bot_mode == 0 and not is_tp:
        # Manual override note
        pass  # Allow manual regardless

    # Notify if bot active
    if bot_mode >= 2:
        msg = (f"{'💰' if is_tp else '🔄'} <b>{action_word} — {ticker}</b>\n"
               f"📞 BUY {qty}x {ticker} ${strike:.0f}C {expiry}\n"
               f"{'✅ רווח הושג!' if is_tp else '⚠️ DTE/Delta הצריכו גלגול'}")
        _send_telegram(msg)

    # Close or Roll logic
    try:
        if is_tp:
            # Simple Close (BUY back)
            payload = {
                "ticker": ticker, "strike": strike, "expiry": expiry, "right": "C",
                "action": "BUY", "qty": qty, "limit_price": cur_px * 1.02,
                "order_type": "LMT", "tif": "DAY"
            }
            r = api_ibkr.place_order(payload["ticker"], payload["strike"], payload["expiry"], payload["right"], payload["action"], payload["qty"], payload.get("limit_price"))
            if r.get("ok"):
                st.success(f"✅ פקודת סגירה (TP) נשלחה עבור {ticker}")
            else:
                st.error(f"כשל בסגירה: {r.get('error', r)}")
        
        elif is_roll:
            # 1. Search for new target short call
            qr   = quant_results.get(ticker)
            sig  = getattr(qr, "signal", "NORMAL") if qr else "NORMAL"
            meta = _SIG_META.get(sig, _SIG_META["NORMAL"])
            tgt_delta = meta["delta"]
            
            with st.spinner(f"מחפש יעד לגלגול עבור {ticker}..."):
                r_search = requests.get(f"{YAHOO}/options/search", params={
                    "ticker": ticker, "min_dte": short_dte - 10, "max_dte": short_dte + 20,
                    "target_delta": tgt_delta, "right": "C", "n": 1
                }, timeout=15)
                search_data = r_search
                targets = search_data.get("data", [])
            
            if not targets:
                st.error("לא נמצא יעד מתאים לגלגול. בצע פעולה ידנית.")
                return
            
            new_opt = targets[0]
            new_strike = new_opt["strike"]
            new_expiry = new_opt["expiry"]
            new_mid    = new_opt["mid"]
            
            # 2. Construct Combo (BUY old, SELL new)
            # Limit Price for credit roll: (BUY_mid - SELL_mid). Usually negative (credit).
            combo_mid = round(cur_px - new_mid, 2)
            
            combo_legs = [
                {"strike": strike, "expiry": expiry, "right": "C", "action": "BUY", "qty": qty},
                {"strike": new_strike, "expiry": new_expiry, "right": "C", "action": "SELL", "qty": qty}
            ]
            
            r_combo = api_ibkr.place_combo(ticker, combo_legs, limit_price=combo_mid, escalation_step_pct=1.0)
            if r_combo.get("ok"):
                st.success(f"✅ פקודת גלגול קומבו נשלחה עבור {ticker}!")
                st.info(f"🔄 גלגול: {strike}@{expiry} -> {new_strike}@{new_expiry} | Net Mid: ${combo_mid:.2f}")
            else:
                st.error(f"כשל בגלגול: {r_combo.get('error', r_combo)}")

    except Exception as e:
        st.error(f"שגיאת ביצוע פעולה: {e}")

