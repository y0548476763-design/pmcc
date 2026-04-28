"""
ui/roll_tab.py — LEAPS Roll Manager + Manual LEAPS Buyer
Phase A: api_yahoo (:8001) option search by delta/DTE
Phase B: api_ibkr (:8002) qualify conId + BAG order
"""
import streamlit as st
import time
from datetime import datetime, timezone
import config
import settings_manager
import api_ibkr
import api_yahoo

_TIMEOUT = 15

# ── helpers ───────────────────────────────────────────────────────────────

def _dte(exp: str) -> int:
    try:
        return max(0, (datetime.strptime(str(exp).replace("-",""), "%Y%m%d").date()
                       - datetime.now(timezone.utc).date()).days)
    except Exception:
        return 0

def _search_leaps(ticker: str, min_dte: int, target_delta: float, n: int = 5) -> list:
    data = api_yahoo.search_leaps(ticker, min_dte, target_delta, n)
    if data.get("ok"):
        return data.get("data", [])
    st.error(f"❌ api_yahoo: {data.get('error', data.get('detail', ''))}")
    return []

def _qualify(ticker, strike, expiry, right="C"):
    """Call IBKR to get conId + live price for a contract."""
    return api_ibkr.qualify_contract(ticker, strike, expiry, right)

def _send_combo(ticker, legs, limit_price, esc_step, esc_wait_secs):
    """
    Send N-leg BAG order to api_ibkr.
    legs: [{"strike","expiry","right","action","qty"}]
    """
    req = {
        "ticker": ticker,
        "legs": legs,
        "limit_price": limit_price,
        "use_market": False,
        "escalation_step_pct": float(esc_step),
        "escalation_wait_secs": int(esc_wait_secs),
    }
    # Notice: we haven't implemented place_combo in api_ibkr module yet, we can do it directly via requests or add it:
    # We'll import requests just for combo if not added, or add it to SDK.
    return api_ibkr.place_combo(ticker, legs, limit_price, False, esc_step, esc_wait_secs)

# ── Option Card component ──────────────────────────────────────────────────

def _option_card(opt, idx, key_prefix, select_label="✅ בחר"):
    dte = opt.get("dte", 0)
    dte_color = "#f87171" if dte < 400 else ("#fbbf24" if dte < 600 else "#34d399")
    st.markdown(f"""
<div style="background:linear-gradient(135deg,rgba(30,41,59,0.9),rgba(15,23,42,0.9));
border:1px solid rgba(99,102,241,0.4);border-top:3px solid #6366f1;
border-radius:12px;padding:1rem 0.8rem;text-align:center;
box-shadow:0 4px 15px rgba(0,0,0,0.3);">
<div style="font-size:0.6rem;color:#64748b;margin-bottom:4px;">#{idx+1}</div>
<div style="font-size:1.6rem;font-weight:900;color:#f1f5f9;line-height:1;">
${opt['strike']:.0f}</div>
<div style="font-size:0.68rem;color:#94a3b8;margin:4px 0;">{opt['expiry']}</div>
<div style="display:flex;justify-content:space-around;margin:8px 0;">
<span style="color:{dte_color};font-weight:700;font-size:0.8rem;">{dte}d</span>
<span style="color:#818cf8;font-weight:700;font-size:0.8rem;">Δ {opt['delta']:.2f}</span>
<span style="color:#34d399;font-weight:900;font-size:1rem;">${opt['mid']:.2f}</span>
</div>
</div>""", unsafe_allow_html=True)
    return st.button(select_label, key=f"{key_prefix}_{idx}", use_container_width=True)

# ── Roll Combo execution ───────────────────────────────────────────────────

def _execute_roll(old_lp, new_tgt, esc_mins, esc_step):
    ticker = old_lp["ticker"]
    qty    = abs(old_lp.get("qty", 1))

    # Phase B-1: qualify both legs on IBKR → get conId + live mid
    with st.spinner("🔄 מאמת חוזים ב-IBKR..."):
        sell_q = _qualify(ticker, old_lp["strike"], old_lp["expiry"], "C")
        buy_q  = _qualify(ticker, new_tgt["strike"], new_tgt["expiry"], "C")

    if not sell_q.get("ok"):
        st.error(f"❌ SELL leg qualification נכשל: {sell_q.get('detail', sell_q.get('error'))}")
        return
    if not buy_q.get("ok"):
        st.error(f"❌ BUY leg qualification נכשל: {buy_q.get('detail', buy_q.get('error'))}")
        return

    ms = sell_q.get("mid") or float(old_lp.get("current_price", 0))
    mb = buy_q.get("mid")  or float(new_tgt.get("mid", 0))
    combo_net = round(mb - ms, 2)

    col1, col2, col3 = st.columns(3)
    col1.metric("SELL Mid", f"${ms:.2f}", f"conId: {sell_q['conId']}")
    col2.metric("BUY Mid",  f"${mb:.2f}", f"conId: {buy_q['conId']}")
    col3.metric("Net Debit" if combo_net > 0 else "Net Credit",
                f"${abs(combo_net):.2f}",
                "📤 עלות" if combo_net > 0 else "💰 קרדיט")

    # Phase B-2: send N-leg BAG to api_ibkr
    legs = [
        {"strike": float(old_lp["strike"]), "expiry": str(old_lp["expiry"]),
         "right": "C", "action": "SELL", "qty": qty},
        {"strike": float(new_tgt["strike"]), "expiry": str(new_tgt["expiry"]),
         "right": "C", "action": "BUY",  "qty": qty},
    ]
    with st.spinner("⏳ שולח פקודת COMBO (BAG)..."):
        resp = _send_combo(ticker, legs, combo_net, esc_step, esc_mins * 60)

    if resp.get("ok"):
        r = resp.get("result", {})
        oid = r.get("order_id", "—")
        st.success(f"✅ פקודה {oid} נשלחה — עקוב במוניטור למטה")
    else:
        st.error(f"❌ {resp.get('detail', resp.get('error', resp))}")

# ── Main render ────────────────────────────────────────────────────────────

def render_roll_tab(tws=None) -> None:

    st.markdown("""
<div style="padding:0.5rem 0 1.2rem 0;">
<div style="font-size:1.5rem;font-weight:900;background:linear-gradient(135deg,#6366f1,#38bdf8);
-webkit-background-clip:text;-webkit-text-fill-color:transparent;">
🔄 LEAPS Roll Engine
</div>
<div style="font-size:0.75rem;color:#64748b;margin-top:4px;">
חיפוש ביאהו פיננס → אימות conId ב-IBKR → פקודת BAG עם הסלמה חכמה
</div>
</div>""", unsafe_allow_html=True)

    bot_mode = settings_manager.get_bot_mode()

    # ══════════════════════════════════════════════════
    # TAB A — Roll Existing LEAPS  |  TAB B — Buy New LEAPS
    # ══════════════════════════════════════════════════
    tab_roll, tab_buy = st.tabs(["🔄 גלגול LEAPS קיים", "➕ רכישת LEAPS חדש"])

    # ──────────────────────────────────────────────────
    # TAB A: Roll existing LEAPS
    # ──────────────────────────────────────────────────
    with tab_roll:
        st.markdown('<div style="font-size:0.85rem;font-weight:700;color:#94a3b8;'
                    'letter-spacing:0.05em;text-transform:uppercase;padding:0.5rem 0;">שלב א — חפש ליפס חדש</div>',
                    unsafe_allow_html=True)

        c1, c2, c3, c4 = st.columns([1.2, 1, 1.5, 0.8], gap="medium")
        with c1:
            ticker = st.text_input("טיקר", value=st.session_state.get("roll_ticker","META"),
                                   key="roll_ticker_input", placeholder="META").upper().strip()
        with c2:
            min_dte = st.number_input("מינ׳ DTE", 200, 1000, 650, step=30, key="roll_min_dte")
        with c3:
            tgt_delta = st.slider("דלתא יעד", 0.50, 0.99, 0.80, step=0.01, key="roll_tgt_delta",
                                  format="%.2f")
        with c4:
            st.markdown('<div style="height:28px;"></div>', unsafe_allow_html=True)
            search_btn = st.button("🔍 חפש", key="roll_search", type="primary", use_container_width=True)

        if search_btn and ticker:
            st.session_state["roll_ticker"] = ticker
            st.session_state.pop("roll_targets", None)
            st.session_state.pop("roll_new_selected", None)
            with st.spinner(f"מחפש LEAPS עבור {ticker}..."):
                res = _search_leaps(ticker, min_dte, tgt_delta)
            if res:
                st.session_state["roll_targets"] = res
            else:
                st.warning("לא נמצאו תוצאות")

        targets = st.session_state.get("roll_targets", [])
        if targets:
            st.markdown('<div style="font-size:0.85rem;font-weight:700;color:#94a3b8;'
                        'letter-spacing:0.05em;text-transform:uppercase;padding:0.8rem 0 0.4rem;">שלב ב — בחר יעד</div>',
                        unsafe_allow_html=True)
            cols = st.columns(min(len(targets), 5))
            for i, tgt in enumerate(targets[:5]):
                with cols[i]:
                    if _option_card(tgt, i, "roll_pick"):
                        st.session_state["roll_new_selected"] = tgt
                        st.rerun()
            if st.button("🗑️ נקה תוצאות", key="roll_clear"):
                st.session_state.pop("roll_targets", None)
                st.session_state.pop("roll_new_selected", None)
                st.rerun()

        new_tgt = st.session_state.get("roll_new_selected")
        if new_tgt:
            st.markdown("---")
            st.markdown(f"""
<div style="background:rgba(56,189,248,0.08);border:1px solid rgba(56,189,248,0.35);
border-radius:10px;padding:0.8rem 1rem;margin-bottom:1rem;">
<span style="color:#38bdf8;font-weight:700;">ליפס שנבחר (BUY):</span> &nbsp;
{new_tgt['ticker']} &nbsp;|&nbsp; Strike <b>${new_tgt['strike']:.0f}</b>
&nbsp;|&nbsp; {new_tgt['expiry']}
&nbsp;|&nbsp; <span style="color:#34d399;">{new_tgt['dte']}d</span>
&nbsp;|&nbsp; Δ {new_tgt['delta']:.2f}
&nbsp;|&nbsp; <b style="color:#34d399;">${new_tgt['mid']:.2f}</b>
</div>""", unsafe_allow_html=True)

            all_pos = st.session_state.get("positions", [])
            old_leaps = [p for p in all_pos
                         if p.get("type") == "LEAPS" and p.get("qty", 0) > 0
                         and p.get("ticker","") == new_tgt["ticker"]]
            if not old_leaps:
                old_leaps = [p for p in all_pos if p.get("type") == "LEAPS" and p.get("qty", 0) > 0]

            if not old_leaps:
                st.warning("לא נמצאו פוזיציות LEAPS בתיק לגלגול.")
            else:
                def _lbl(p):
                    d = p.get("dte", _dte(p.get("expiry","")))
                    return f"{p['ticker']} | ${p.get('strike',0):.0f}C | {p.get('expiry','')} | {d}d"

                labels  = [_lbl(p) for p in old_leaps]
                old_map = dict(zip(labels, old_leaps))

                col_l, col_r = st.columns([3, 2])
                with col_l:
                    old_sel = st.selectbox("ליפס ישן לגלגול (SELL):", labels, key="roll_old_sel")
                    old_lp  = old_map[old_sel]
                    od      = old_lp.get("dte", _dte(old_lp.get("expiry","")))
                    oc      = "#f87171" if od < 360 else "#fbbf24"
                    net     = round(new_tgt["mid"] - float(old_lp.get("current_price", 0)), 2)
                    nc      = "#f87171" if net > 0 else "#34d399"
                    st.markdown(f"""
<div style="background:rgba(248,113,113,0.07);border:1px solid rgba(248,113,113,0.3);
border-radius:8px;padding:0.6rem 1rem;font-size:0.82rem;margin-top:0.5rem;">
<b style="color:#f87171;">SELL:</b> {old_lp['ticker']} ${float(old_lp['strike']):.0f}C
{old_lp.get('expiry','')} <span style="color:{oc};">({od}d)</span>
&nbsp;&nbsp;
<b style="color:{nc};">{'עלות' if net>0 else 'קרדיט'}: ${abs(net):.2f}</b>
</div>""", unsafe_allow_html=True)

                with col_r:
                    esc_mins = st.number_input("המתנה לפני הסלמה (דק׳)", 1, 30,
                                               config.ESCALATION_WAIT_MINUTES, key="roll_esc_mins")
                    esc_step = st.number_input("הסלמה (%)", 0.1, 5.0,
                                               config.ESCALATION_STEP_PCT, step=0.1, key="roll_esc_step")

                col_exec, col_cancel = st.columns(2)
                with col_exec:
                    if st.button("🚀 בצע גלגול", key="exec_roll", type="primary", use_container_width=True):
                        _execute_roll(old_lp, new_tgt, esc_mins, esc_step)
                with col_cancel:
                    if st.button("↩️ ביטול", key="cancel_roll", use_container_width=True):
                        st.session_state.pop("roll_new_selected", None)
                        st.rerun()

    # ──────────────────────────────────────────────────
    # TAB B: Buy New LEAPS manually (with search)
    # ──────────────────────────────────────────────────
    with tab_buy:
        st.markdown('<div style="font-size:0.85rem;font-weight:700;color:#94a3b8;'
                    'letter-spacing:0.05em;text-transform:uppercase;padding:0.5rem 0 0.8rem;">חיפוש אופציה לפי דלתא ו-DTE</div>',
                    unsafe_allow_html=True)

        bc1, bc2, bc3, bc4, bc5 = st.columns([1.2, 1, 1, 1.5, 0.8], gap="small")
        with bc1:
            buy_ticker = st.text_input("טיקר", key="buy_ticker", placeholder="NVDA").upper().strip()
        with bc2:
            buy_min_dte = st.number_input("מינ׳ DTE", 30, 1200, 550, step=30, key="buy_min_dte")
        with bc3:
            buy_max_dte = st.number_input("מקס׳ DTE", 30, 1200, 800, step=30, key="buy_max_dte")
        with bc4:
            buy_delta = st.slider("דלתא יעד", 0.50, 0.99, 0.80, step=0.01, key="buy_delta",
                                  format="%.2f")
        with bc5:
            st.markdown('<div style="height:28px;"></div>', unsafe_allow_html=True)
            buy_search = st.button("🔍 חפש", key="buy_search_btn", type="primary", use_container_width=True)

        if buy_search and buy_ticker:
            with st.spinner(f"מחפש LEAPS עבור {buy_ticker}..."):
                res2 = _search_leaps(buy_ticker, buy_min_dte, buy_delta, n=8)
            # Filter by max_dte
            res2 = [o for o in res2 if o.get("dte", 0) <= buy_max_dte]
            if res2:
                st.session_state["buy_options"] = res2
            else:
                st.warning("לא נמצאו אופציות בטווח שנבחר")

        buy_opts = st.session_state.get("buy_options", [])
        if buy_opts:
            st.markdown('<div style="font-size:0.85rem;font-weight:700;color:#94a3b8;'
                        'letter-spacing:0.05em;text-transform:uppercase;padding:0.8rem 0 0.4rem;">בחר אופציה</div>',
                        unsafe_allow_html=True)
            cols2 = st.columns(min(len(buy_opts), 4))
            for i, opt in enumerate(buy_opts[:4]):
                with cols2[i % 4]:
                    if _option_card(opt, i, "buy_pick", "📋 בחר"):
                        st.session_state["buy_selected"] = opt
                        st.rerun()

        buy_sel = st.session_state.get("buy_selected")
        if buy_sel:
            st.markdown("---")
            st.markdown(f"""
<div style="background:rgba(52,211,153,0.08);border:1px solid rgba(52,211,153,0.35);
border-radius:10px;padding:0.8rem 1rem;margin-bottom:1rem;">
<span style="color:#34d399;font-weight:700;">נבחר:</span> &nbsp;
{buy_sel['ticker']} ${buy_sel['strike']:.0f}C &nbsp;|&nbsp;
{buy_sel['expiry']} ({buy_sel['dte']}d) &nbsp;|&nbsp;
Δ {buy_sel['delta']:.2f} &nbsp;|&nbsp;
<b style="color:#34d399;">Mid ${buy_sel['mid']:.2f}</b>
</div>""", unsafe_allow_html=True)

            fc1, fc2, fc3 = st.columns(3)
            with fc1:
                buy_qty = st.number_input("כמות חוזים", 1, 100, 1, key="buy_qty_final")
            with fc2:
                buy_limit = st.number_input("מחיר לימיט ($)",
                                            min_value=0.01, value=float(buy_sel.get("ask", buy_sel["mid"])),
                                            step=0.05, key="buy_limit_final")
            with fc3:
                buy_tif = st.selectbox("TIF", ["GTC", "DAY"], key="buy_tif")

            col_send, col_clr = st.columns(2)
            with col_send:
                if st.button("📤 שלח פקודת רכישה", key="buy_send_order", type="primary", use_container_width=True):
                    # Step 1: qualify via IBKR to get conId
                    with st.spinner("🔄 מאמת חוזה ב-IBKR..."):
                        q = _qualify(buy_sel["ticker"], buy_sel["strike"], buy_sel["expiry"], "C")

                    if not q.get("ok"):
                        st.error(f"❌ Qualification נכשל: {q.get('detail', q.get('error'))}")
                    else:
                        st.info(f"✅ conId={q['conId']} | Mid=${q.get('mid', 0):.2f}")
                        # Step 2: send single-leg BUY order
                        try:
                            resp = requests.post(f"{IBKR}/order/place", json={
                                "ticker": buy_sel["ticker"],
                                "strike": float(buy_sel["strike"]),
                                "expiry": str(buy_sel["expiry"]),
                                "right": "C",
                                "action": "BUY",
                                "qty": buy_qty,
                                "limit_price": buy_limit,
                                "order_type": "LMT",
                                "tif": buy_tif,
                            }, timeout=15)
                            rj = resp
                            if rj.get("ok"):
                                st.success(f"✅ פקודה נשלחה! Order ID: {rj.get('order_id','—')}")
                                st.session_state.pop("buy_selected", None)
                                st.session_state.pop("buy_options", None)
                            else:
                                st.error(f"❌ {rj.get('detail', rj)}")
                        except Exception as e:
                            st.error(f"❌ שגיאת תקשורת: {e}")

            with col_clr:
                if st.button("↩️ ביטול", key="buy_cancel", use_container_width=True):
                    st.session_state.pop("buy_selected", None)
                    st.rerun()

    # ══════════════════════════════════════════════════
    # Live Order Monitor (shared)
    # ══════════════════════════════════════════════════
    st.markdown("---")
    st.markdown("""
<div style="font-size:0.85rem;font-weight:700;color:#94a3b8;
letter-spacing:0.05em;text-transform:uppercase;padding:0.5rem 0;">
📋 Live Order Monitor
</div>""", unsafe_allow_html=True)

    try:
        r = requests.get(f"{IBKR}/api/orders/active", timeout=5)
        if r.status_code == 200:
            orders = r.get("orders", []) if isinstance(r, dict) else []
            if not orders:
                st.info("אין פקודות פעילות.")
            else:
                import pandas as pd
                df = pd.DataFrame(orders)
                df = df.rename(columns={
                    "internal_id": "ID", "ticker": "Ticker", "strike": "Strike",
                    "expiry": "Expiry", "status": "Status", "ibkr_status": "IBKR",
                    "current_price": "Price", "escalation_count": "Escals", "is_combo": "Combo?"
                })
                st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.error("שגיאה במשיכת פקודות מה-API")
    except Exception as e:
        st.warning(f"api_ibkr לא זמין: {e}")

    auto_ref = st.checkbox("🔄 רענון אוטומטי (5 שניות)", value=False, key="roll_auto_ref")
    if auto_ref:
        time.sleep(5)
        st.rerun()