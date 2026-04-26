"""
ui/roll_tab.py — LEAPS Roll Manager
Phase A: api_yahoo (:8001) search → choose new LEAPS
Phase B: api_ibkr (:8002) qualify + combo BAG order
"""
import streamlit as st
import time
from datetime import datetime, timezone
import requests
import config
import settings_manager


YAHOO = config.YAHOO_API_URL   # http://localhost:8001
IBKR  = config.IBKR_API_URL    # http://localhost:8002
_TIMEOUT = 15

# ── helpers ───────────────────────────────────────────────────────────────

def _dte(exp: str) -> int:
    try:
        return max(0, (datetime.strptime(str(exp).replace("-",""), "%Y%m%d").date()
                       - datetime.now(timezone.utc).date()).days)
    except Exception:
        return 0

def _send_tg(msg: str) -> bool:
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{settings_manager.get_telegram_token()}/sendMessage",
            json={"chat_id": settings_manager.get_telegram_chat_id(),
                  "text": msg, "parse_mode": "HTML"}, timeout=8)
        return r.status_code == 200
    except Exception:
        return False

def _search_yahoo_leaps(ticker: str, min_dte: int, target_delta: float, n: int = 5) -> list:
    """Call api_yahoo to search LEAPS (4-hour cache is on the server)."""
    try:
        r = requests.get(f"{YAHOO}/leaps/search",
                         params={"ticker": ticker, "min_dte": min_dte,
                                 "target_delta": target_delta, "n": n},
                         timeout=_TIMEOUT)
        data = r.json()
        if data.get("ok"):
            return data.get("data", [])
        st.error(f"❌ api_yahoo error: {data}")
        return []
    except requests.exceptions.ConnectionError:
        st.error("❌ api_yahoo לא פועל על פורט 8001. הרץ תחילה את run_pmcc.bat")
        return []
    except Exception as e:
        st.error(f"❌ שגיאה בחיפוש LEAPS: {e}")
        return []

# ── Phase B: qualify on api_ibkr + send combo ────────────────────────────

def _execute_combo(old_lp: dict, new_tgt: dict,
                   esc_mins: int, esc_step: float,
                   bot_mode: int):

    ticker = old_lp["ticker"]
    qty    = abs(old_lp.get("qty", 1))

    # Phase B-1: qualify both contracts on IBKR to get live prices
    with st.spinner("🔄 מאמת חוזים ב-IBKR ושואב מחירים חיים..."):
        try:
            sell_q = requests.post(f"{IBKR}/qualify", json={
                "ticker": ticker, "strike": float(old_lp["strike"]),
                "expiry": str(old_lp["expiry"]), "right": "C"}, timeout=_TIMEOUT).json()
            buy_q  = requests.post(f"{IBKR}/qualify", json={
                "ticker": ticker, "strike": float(new_tgt["strike"]),
                "expiry": str(new_tgt["expiry"]), "right": "C"}, timeout=_TIMEOUT).json()
        except requests.exceptions.ConnectionError:
            st.error("❌ api_ibkr לא פועל על פורט 8002.")
            return
        except Exception as e:
            st.error(f"❌ שגיאת qualification: {e}")
            return

        if not sell_q.get("ok") or not buy_q.get("ok"):
            st.error("❌ לא ניתן לאמת חוזים ב-IBKR.")
            return

        ms = sell_q.get("mid") or float(old_lp.get("current_price", 0))
        mb = buy_q.get("mid")  or float(new_tgt.get("mid", 0))
        combo_mid = round(mb - ms, 2)
        st.info(f"✅ SELL conId={sell_q['conId']} (${ms:.2f}) | "
                f"BUY conId={buy_q['conId']} (${mb:.2f}) | "
                f"קומבו Mid: **${combo_mid:.2f}**")

    # Phase B-2: send combo to api_ibkr
    with st.spinner("⏳ שולח פקודת COMBO (BAG)..."):
        try:
            resp = requests.post(f"{IBKR}/order/combo", json={
                "ticker": ticker, "qty": qty,
                "sell_strike": float(old_lp["strike"]),
                "sell_expiry": str(old_lp["expiry"]),
                "buy_strike":  float(new_tgt["strike"]),
                "buy_expiry":  str(new_tgt["expiry"]),
                "limit_price": combo_mid,
                "use_market": False,
                "escalation_step_pct": float(esc_step),
                "escalation_wait_secs": int(esc_mins) * 60,
            }, timeout=60).json()
        except Exception as e:
            st.error(f"❌ שגיאה בשליחת פקודה: {e}")
            return

    if resp.get("ok"):
        r = resp.get("result", {})
        status = r.get("status", "?")
        if status == "FILLED":
            fill = r.get("fill_price", 0)
            _send_tg(f"🔄 <b>גלגול בוצע!</b>\n{ticker}\n"
                     f"📤 ${float(old_lp['strike']):.0f}C {old_lp['expiry']}\n"
                     f"📥 ${float(new_tgt['strike']):.0f}C {new_tgt['expiry']}\n"
                     f"💰 ${fill:.2f}")
            st.toast(f"✅ גלגול בוצע במחיר ${fill:.2f}", icon="🔄")
        else:
            st.success(f"⏳ פקודה {r.get('order_id','')} נשלחה — עקוב אחר ההתקדמות במוניטור למטה")
    else:
        st.error(f"❌ הפקודה נכשלה: {resp}")

# ── Main render ───────────────────────────────────────────────────────────────

def render_roll_tab(tws=None) -> None:
    st.markdown("""
    <div style="padding:0.4rem 0 1rem 0;">
      <div class="pmcc-title">🔄 גלגול ליפסים — LEAPS Roll Engine</div>
      <div style="font-size:0.72rem;color:#64748b;margin-top:3px;">
        חיפוש ביאהו פיננס · אימות ב-IBKR · פקודת קומבו BAG עם הסלמה חכמה
      </div>
    </div>""", unsafe_allow_html=True)

    bot_mode = settings_manager.get_bot_mode()

    st.markdown('<div class="section-hdr">🔎 שלב א — חפש ליפס חדש ביאהו פיננס</div>',
                unsafe_allow_html=True)

    # Clean row layout with proper vertical alignment
    # Balanced 4-column layout for better alignment
    with st.container():
        c1, c2, c3, c4 = st.columns([1, 1, 2, 1], gap="medium")
        with c1:
            ticker = st.text_input("טיקר:", value=st.session_state.get("roll_ticker","META"),
                                   key="roll_ticker_input", placeholder="META").upper().strip()
        with c2:
            min_dte = st.number_input("מינימום DTE:", 200, 1000, 650, step=30, key="roll_min_dte")
        with c3:
            tgt_delta = st.slider("דלתא יעד:", 0.50, 0.99, 0.80, step=0.01, key="roll_tgt_delta")
        with c4:
            st.markdown('<div style="margin-top:28px;"></div>', unsafe_allow_html=True)
            search_clicked = st.button("🔍 חפש", key="roll_search", type="primary", use_container_width=True)

    if search_clicked and ticker:
        if st.session_state.get("roll_ticker") != ticker:
            for k in ("roll_targets","roll_new_selected"):
                st.session_state.pop(k, None)
        st.session_state["roll_ticker"] = ticker
        with st.spinner(f"מחפש LEAPS עבור {ticker} ביאהו פיננס..."):
            results = _search_yahoo_leaps(ticker, min_dte, tgt_delta)
        if results:
            st.session_state["roll_targets"] = results
            st.toast(f"נמצאו {len(results)} אפשרויות!", icon="🔍")
        else:
            st.session_state.pop("roll_targets", None)

    targets = st.session_state.get("roll_targets", [])
    if targets:
        st.markdown('<div class="section-hdr">📋 תוצאות — בחר ליפס יעד</div>',
                    unsafe_allow_html=True)
        cols = st.columns(len(targets))
        for i, tgt in enumerate(targets):
            with cols[i]:
                dc = "#f87171" if tgt["dte"] < 400 else ("#fbbf24" if tgt["dte"] < 600 else "#34d399")
                st.markdown(f"""
                <div class="pmcc-card" style="border-top:3px solid #6366f1;
                     padding:0.8rem 0.5rem;text-align:center;">
                   <div style="font-size:0.6rem;color:#64748b;">#{i+1}</div>
                   <div style="font-size:1.4rem;font-weight:900;color:#f1f5f9;">
                     ${tgt['strike']:.0f}</div>
                   <div style="font-size:0.68rem;color:#64748b;">{tgt['expiry']}</div>
                   <div style="font-size:0.7rem;color:{dc};font-weight:600;">{tgt['dte']}d</div>
                   <div style="color:#818cf8;font-weight:700;">Δ {tgt['delta']:.2f}</div>
                   <div style="font-size:1.05rem;font-weight:900;color:#34d399;">${tgt['mid']:.2f}</div>
                </div>""", unsafe_allow_html=True)
                if st.button(f"✅ בחר", key=f"pick_{i}", use_container_width=True):
                    st.session_state["roll_new_selected"] = tgt
                    st.rerun()

        if st.button("🗑️ נקה", key="roll_clear_btn"):
            for k in ("roll_targets","roll_new_selected"):
                st.session_state.pop(k, None)
            st.rerun()

    # ── ROW 5: Manual LEAPS Entry ──────────────────────────────────────────
    st.markdown("<br>", unsafe_allow_html=True)
    with st.expander("🛠️ רכישת ליפס חדש (ידני)", expanded=False):
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            man_ticker = st.text_input("טיקר:", key="man_leaps_ticker", placeholder="SPY").upper().strip()
        with c2:
            man_strike = st.number_input("Strike:", 1.0, 10000.0, 400.0, step=5.0, key="man_leaps_strike")
        with c3:
            man_expiry = st.text_input("פקיעה (YYYYMMDD):", key="man_leaps_expiry", placeholder="20260619")
        with c4:
            man_qty = st.number_input("כמות:", 1, 100, 1, key="man_leaps_qty")

        c5, c6, c7 = st.columns(3)
        with c5:
            man_mid = st.number_input("מחיר לימיט (Mid):", 0.01, 1000.0, 10.0, step=0.1, key="man_leaps_mid")
        with c6:
            man_esc_mins = st.number_input("המתנה (דקות):", 1, 30, config.ESCALATION_WAIT_MINUTES, key="man_leaps_esc_mins")
        with c7:
            man_esc_step = st.number_input("הסלמה (%):", 0.1, 5.0, config.ESCALATION_STEP_PCT, step=0.1, key="man_leaps_esc_step")

        if st.button("📤 שלח פקודת רכישה", key="man_leaps_send", type="primary", use_container_width=True):
            if not man_ticker or not man_expiry:
                st.error("יש למלא טיקר ותאריך פקיעה")
            else:
                try:
                    payload = {
                        "ticker": man_ticker, "right": "C", "strike": man_strike,
                        "expiry": man_expiry, "action": "BUY", "qty": man_qty,
                        "limit_price": man_mid, "order_type": "LMT", "tif": "GTC"
                    }
                    r = requests.post(f"{IBKR}/order/place", json=payload, timeout=10)
                    if r.status_code == 200:
                        oid = r.json().get("order_id", "???")
                        st.success(f"✅ פקודה נשלחה בהצלחה! מזהה: {oid}")
                        requests.post(f"{IBKR}/api/notify", json={
                            "message": f"📤 <b>רכישת ליפס ידנית:</b> {man_qty}x {man_ticker} ${man_strike:.0f} {man_expiry} @ ${man_mid:.2f}"
                        })
                    else:
                        st.error(f"שגיאה בשליחת פקודה: {r.text}")
                except Exception as e:
                    st.error(f"שגיאת תקשורת: {e}")

    # ── Live Order Monitor ──────────────────────────────────────────
    st.markdown("---")
    st.markdown("### 📋 🟢 Live Order Monitor")
    refresh = st.checkbox("🔄 רענון אוטומטי (5 שניות)", value=True, key="auto_refresh_check")
    monitor_placeholder = st.empty()
    
    try:
        r = requests.get(f"{IBKR}/api/orders/active", timeout=5)
        if r.status_code == 200:
            orders = r.json().get("orders", [])
            if not orders:
                monitor_placeholder.info("אין פקודות פעילות כעת.")
            else:
                import pandas as pd
                df = pd.DataFrame(orders)
                df.columns = ["ID", "Ticker", "Strike", "Expiry", "System Status", "IBKR Status", "Limit Price", "Last Price", "Escals", "Combo?"]
                # Use dataframe for better theme support and visibility
                monitor_placeholder.dataframe(df, use_container_width=True, hide_index=True)
        else:
            monitor_placeholder.error("שגיאה במשיכת פקודות מה-API")
    except Exception as e:
        monitor_placeholder.warning(f"API לא זמין: {e}")

    new_tgt = st.session_state.get("roll_new_selected")
    if not new_tgt:
        return

    st.markdown("---")
    st.markdown('<div class="section-hdr">📤 שלב ב — בחר ליפס ישן לסגירה ושלח קומבו</div>',
                unsafe_allow_html=True)

    st.markdown(f"""
    <div style="background:rgba(56,189,248,0.08);border:1px solid rgba(56,189,248,0.3);
         border-radius:10px;padding:0.7rem 1rem;margin-bottom:1rem;direction:rtl;">
      <b style="color:#38bdf8;">ליפס חדש (BUY):</b> &nbsp;
      {new_tgt['ticker']} &nbsp;|&nbsp; Strike <b>${new_tgt['strike']:.0f}</b>
      &nbsp;|&nbsp; {new_tgt['expiry']} &nbsp;|&nbsp;
      <span style="color:#34d399">{new_tgt['dte']}d</span> &nbsp;|&nbsp;
      Δ {new_tgt['delta']:.2f} &nbsp;|&nbsp;
      מחיר: <b style="color:#34d399">${new_tgt['mid']:.2f}</b>
    </div>""", unsafe_allow_html=True)

    all_pos = st.session_state.get("positions", [])
    old_leaps = [p for p in all_pos
                 if p.get("type") == "LEAPS" and p.get("qty", 0) > 0
                 and p.get("ticker","") == new_tgt["ticker"]]
    if not old_leaps:
        old_leaps = [p for p in all_pos
                     if p.get("type") == "LEAPS" and p.get("qty", 0) > 0]

    if not old_leaps:
        st.warning("לא נמצאו פוזיציות LEAPS בתיק.")
        return

    def _lbl(p):
        d = p.get("dte", _dte(p.get("expiry","")))
        return f"{p['ticker']} | ${p.get('strike',0):.0f} | {p.get('expiry','')} | {d}d"

    labels  = [_lbl(p) for p in old_leaps]
    old_map = dict(zip(labels, old_leaps))

    col_left, col_right = st.columns([3, 2])
    with col_left:
        old_sel = st.selectbox("ליפס ישן לסגירה (SELL):", labels, key="roll_old_sel")
        old_lp  = old_map[old_sel]
        od      = old_lp.get("dte", _dte(old_lp.get("expiry","")))
        oc      = "#f87171" if od < 360 else "#fbbf24"
        st.markdown(f"""
        <div style="background:rgba(248,113,113,0.06);border:1px solid rgba(248,113,113,0.3);
             border-radius:8px;padding:0.55rem 0.9rem;font-size:0.82rem;direction:rtl;">
          <b style="color:#f87171;">ליפס ישן (SELL):</b> &nbsp;
          {old_lp['ticker']} &nbsp;|&nbsp; Strike <b>${float(old_lp['strike']):.0f}</b>
          &nbsp;|&nbsp; {old_lp.get('expiry','')} &nbsp;|&nbsp; <span style="color:{oc}">{od}d</span>
        </div>""", unsafe_allow_html=True)

        mid_old = float(old_lp.get("current_price", 0))
        net     = round(new_tgt["mid"] - mid_old, 2)
        nc      = "#f87171" if net > 0 else "#34d399"
        nlbl    = f"עלות גלגול: ${net:.2f}" if net > 0 else f"קרדיט: ${abs(net):.2f}"
        st.markdown(f"""
        <div style="text-align:center;padding:0.5rem;font-weight:700;color:{nc};font-size:1rem;">
          {nlbl}
        </div>""", unsafe_allow_html=True)

    with col_right:
        st.markdown('<div class="pmcc-header" style="margin-bottom:6px">⚙️ הגדרות ביצוע</div>',
                    unsafe_allow_html=True)
        esc_mins = st.number_input("המתנה לפני הסלמה (דקות):", 1, 30, config.ESCALATION_WAIT_MINUTES, key="roll_esc_mins")
        esc_step = st.number_input("הסלמה (%):", 0.1, 5.0, config.ESCALATION_STEP_PCT, step=0.1, key="roll_esc_step")

    if st.button("🚀 בצע גלגול קומבו (Combo Roll)", key="exec_combo_main", type="primary", use_container_width=True):
        _execute_combo(old_lp, new_tgt, esc_mins, esc_step, bot_mode)

    if st.button("↩️ ביטול", key="exec_cancel", use_container_width=True):
        st.session_state.pop("roll_new_selected", None)
        st.rerun()

    if refresh:
        time.sleep(5)
        st.rerun()