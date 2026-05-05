"""
ui/earnings_tab.py — Model B: Earnings IV Crush (Iron Condor)
Architecture:
  Phase 1 - Yahoo Finance: option chain scan, ATM straddle, EM calc, 4-strike selection
  Phase 2 - IBKR: qualify 4 legs (get conId), send BAG order
  Exit     - Next morning at 09:30 EST: close all 4 legs
"""
import streamlit as st
import time
import pandas as pd
from datetime import datetime, timezone, timedelta
from streamlit.runtime.scriptrunner import get_script_run_ctx

# בולם זעזועים: אם אנחנו בתהליך רקע (תזמון), נדפיס לטרמינל. אם אנחנו במסך, נדפיס למסך כרגיל.
orig_write = st.write; orig_success = st.success; orig_error = st.error
st.write = lambda *a, **k: orig_write(*a, **k) if get_script_run_ctx() else print("[Background]", *a)
st.success = lambda *a, **k: orig_success(*a, **k) if get_script_run_ctx() else print("[Background SUCCESS]", *a)
st.error = lambda *a, **k: orig_error(*a, **k) if get_script_run_ctx() else print("[Background ERROR]", *a)

import config
import api_ibkr
import api_yahoo
import settings_manager

_TIMEOUT = 30

# ── Strike rounding ────────────────────────────────────────────────────────

def _round_strike(price: float, spot: float) -> float:
    if spot < 25:    inc = 0.5
    elif spot < 50:  inc = 1.0
    elif spot < 100: inc = 1.0
    elif spot < 200: inc = 2.5
    elif spot < 500: inc = 5.0
    else:            inc = 10.0
    return round(round(price / inc) * inc, 2)

# ── IBKR helpers ──────────────────────────────────────────────────────────

def _qualify(ticker, strike, expiry, right):
    return api_ibkr.qualify_contract(ticker, strike, expiry, right)

# ── Yahoo Finance data fetch ───────────────────────────────────────────────

def _fetch_structure(ticker: str, multiplier=1.15, wing_width=10.0):
    """Fetches expected move and identifies IC strikes via Yahoo."""
    r = api_yahoo.get_expected_move(ticker)
    if not r.get("ok"):
        return None
    
    data = r["data"]
    spot = data["spot"]
    em   = data["expected_move"]
    exp  = data["expiry"]
    
    # Strikes logic from existing code
    safe_em = em * multiplier
    sc = _round_strike(spot + safe_em, spot)
    sp = _round_strike(spot - safe_em, spot)
    lc = _round_strike(sc + wing_width, spot)
    lp = _round_strike(sp - wing_width, spot)
    
    return {
        "ticker": ticker,
        "expiry": exp,
        "spot": spot,
        "em": em,
        "dte": data.get("dte"),
        "call_ask": data.get("call_ask"),
        "put_ask": data.get("put_ask"),
        "strikes": {
            "long_put": lp,
            "short_put": sp,
            "short_call": sc,
            "long_call": lc
        }
    }

# ── Execution Logic ────────────────────────────────────────────────────────

def _execute_earnings_sequence(ticker: str, bot_mode: int, multiplier=1.15, wing_width=10.0, qty=1, scheduled_time=None, custom_esc=None):
    """
    Standard sequence: Fetch -> Qualify -> Place.
    custom_esc: dict with step_pct and wait_secs
    """
    st.write(f"🔍 מתחיל תהליך עבור {ticker}...")
    struct = _fetch_structure(ticker, multiplier, wing_width)
    if not struct:
        st.error(f"לא ניתן היה להוציא נתונים עבור {ticker}")
        return False

    strikes = struct["strikes"]
    expiry = struct["expiry"]
    
    # 1. Qualify all 4 legs
    legs_to_qual = [
        (strikes["short_call"], "C", "SELL"),
        (strikes["long_call"], "C", "BUY"),
        (strikes["short_put"], "P", "SELL"),
        (strikes["long_put"], "P", "BUY")
    ]
    
    qualified_legs = []
    mid_total = 0.0
    for strike, right, action in legs_to_qual:
        res = _qualify(ticker, strike, expiry, right)
        if not res.get("ok"):
            st.error(f"כשל בזיהוי רגל {strike}{right} עבור {ticker}")
            return False
        
        qualified_legs.append({
            "conId": res["conId"],
            "strike": strike,
            "expiry": expiry,
            "right": right,
            "action": action,
            "qty": qty
        })
        # Calculate credit: SELL is positive, BUY is negative
        sign = 1 if action == "SELL" else -1
        mid_total += sign * res.get("mid", 0)
    
    # 2. Final limit price
    limit_price = round(max(0.01, mid_total), 2)
    
    # 3. Place Order
    esc_step = custom_esc["step_pct"] if custom_esc else 1.0
    esc_wait = custom_esc["wait_secs"] if custom_esc else 180
    
    r = api_ibkr.place_combo(
        ticker=ticker,
        legs=qualified_legs,
        limit_price=-abs(limit_price), # PROVEN FIX: IBKR requires negative for Credit
        use_market=False,
        escalation_step_pct=float(esc_step),
        escalation_wait_secs=int(esc_wait),
        scheduled_time=scheduled_time
    )
    
    if r.get("ok"):
        oid = r.get("result", {}).get("order_id", "—")
        st.success(f"✅ פקודה נשלחה עבור {ticker}! ID: {oid}")
        # Save ID to session for closing
        if "active_ic_orders" not in st.session_state:
            st.session_state.active_ic_orders = {}
        st.session_state.active_ic_orders[ticker] = {
            "order_id": oid,
            "expiry": expiry,
            "strikes": strikes,
            "qty": qty,
            "credit": limit_price
        }
        return True
    else:
        st.error(f"כשל בשליחת קומבו ל-{ticker}: {r.get('error', r.get('detail', r))}")
        return False

def _execute_ic_close_direct(ticker, legs_data, bot_mode, scheduled_time=None):
    """
    Closes an IC by sending the exact inverse of current positions using conId.
    legs_data: list of dicts from positions
    """
    st.write(f"🔄 סגירת פוזיציית {ticker} (מבוסס conId)...")
    
    qualified_legs = []
    total_mid = 0.0
    
    with st.spinner("מחשב מחיר אמצע לסגירה..."):
        for l in legs_data:
            current_qty = l.get("qty", 0)
            if current_qty == 0: continue
            
            action = "BUY" if current_qty < 0 else "SELL"
            qty = abs(int(current_qty))
            
            # Fetch real-time mid for this leg
            res = _qualify(ticker, l.get("strike"), l.get("expiry"), l.get("right"))
            leg_mid = res.get("mid", 0.0) if res.get("ok") else 0.0
            
            # Calculate combo mid: we PAY for BUY actions, RECEIVE for SELL actions
            # Closing a spread usually costs a debit (Total BUY mids - Total SELL mids)
            sign = 1 if action == "BUY" else -1
            total_mid += sign * leg_mid

            qualified_legs.append({
                "conId": l.get("conId"),
                "ticker": ticker,
                "strike": l.get("strike"),
                "expiry": l.get("expiry"),
                "right": l.get("right"),
                "action": action,
                "qty": qty
            })
    
    if not qualified_legs:
        st.error(f"לא נמצאו רגליים תקפות לסגירה עבור {ticker}")
        return False

    # Normalize quantities for IBKR Combo (find GCD)
    import math
    from functools import reduce
    
    raw_qtys = [l["qty"] for l in qualified_legs]
    common_factor = reduce(math.gcd, raw_qtys) if raw_qtys else 1
    
    for l in qualified_legs:
        l["qty"] = int(l["qty"] / common_factor) # Ratio
    
    # Price should be PER COMBO UNIT
    start_price = round(max(0.01, total_mid), 2)
    st.write(f"🚀 מתחיל סגירה במחיר אמצע: ${start_price} (כמות: {common_factor})")

    r = api_ibkr.place_combo(
        ticker=ticker,
        legs=qualified_legs,
        limit_price=start_price, 
        use_market=False,
        escalation_step_pct=5.0, 
        escalation_wait_secs=40,
        scheduled_time=scheduled_time,
        total_qty=common_factor
    )
    
    if r.get("ok"):
        oid = r.get("result", {}).get("order_id")
        st.success(f"✅ פקודת סגירה נשלחה ל-{ticker} (ID: {oid})")
        return True
    else:
        st.error(f"כשל בסגירת {ticker}: {r.get('error')}")
        return False

# ── UI Rendering ───────────────────────────────────────────────────────────

def render_earnings_tab(positions: list = None):
    # Standard positions fetch if not provided
    if positions is None:
        try:
            resp = api_ibkr.get_positions()
            positions = resp.get("positions", []) if resp.get("ok") else []
        except:
            positions = []

    st.markdown("""
<div style="padding:0.5rem 0 1rem 0;">
<div style="font-size:1.5rem;font-weight:900;
background:linear-gradient(135deg,#f59e0b,#ef4444);
-webkit-background-clip:text;-webkit-text-fill-color:transparent;">
📈 Model B — Earnings IV Crush (Iron Condor)
</div>
<div style="font-size:0.75rem;color:#64748b;margin-top:4px;">
הפצה סיטונאית, סגירות מתוזמנות וניהול פוזיציות IC
</div>
</div>""", unsafe_allow_html=True)
    
    bot_mode = settings_manager.get_bot_mode()
    
    # 1. Single Ticker Opening (Restored Premium UI)
    with st.expander("🎯 פתיחת פוזיציה בודדת", expanded=True):
        ca1, ca2, ca3, ca4 = st.columns([1.5, 1.2, 1.2, 1.2], gap="small")
        with ca1:
            ticker = st.text_input("טיקר", value=st.session_state.get("earn_ticker","GOOGL"),
                                   key="earn_ticker_inp", placeholder="GOOGL").upper().strip()
        with ca2:
            multiplier = st.number_input("EM Safety ×",
                                         min_value=1.0, max_value=1.5, value=1.15, step=0.05,
                                         key="earn_mult")
        with ca3:
            wing_width = st.number_input("Wing ($)",
                                         min_value=2.5, max_value=50.0, value=10.0, step=2.5,
                                         key="earn_wing")
        with ca4:
            qty = st.number_input("חוזים", 1, 50, 1, key="earn_qty")

        if st.button("🔍 סריקת Yahoo Finance", use_container_width=True, type="primary"):
            if ticker:
                with st.spinner(f"סורק {ticker}..."):
                    st.session_state.earn_struct = _fetch_structure(ticker, multiplier, wing_width)
        
        if st.session_state.get("earn_struct"):
            s = st.session_state.earn_struct
            st.markdown(f"""
            <div style="background:rgba(30,41,59,0.5); border-radius:10px; padding:15px; border:1px solid #334155; margin-bottom:15px;">
                <div style="display:grid; grid-template-columns: repeat(3, 1fr); gap:10px; text-align:center;">
                    <div><span style="color:#94a3b8; font-size:0.8rem;">Spot</span><br/><b style="font-size:1.2rem;">${s['spot']:.2f}</b></div>
                    <div><span style="color:#94a3b8; font-size:0.8rem;">Expected Move</span><br/><b style="font-size:1.2rem; color:#f59e0b;">±${s['em']:.2f}</b></div>
                    <div><span style="color:#94a3b8; font-size:0.8rem;">Expiry</span><br/><b style="font-size:1.2rem;">{s['expiry']}</b></div>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            # Strikes Visualizer
            st.markdown(f"""
            <div style="display:flex; justify-content:space-between; align-items:center; background:#0f172a; padding:15px; border-radius:10px; border:1px solid #1e293b;">
                <div style="text-align:center;"><span style="color:#34d399; font-size:0.7rem;">LONG PUT</span><br/><b>${s['strikes']['long_put']}</b></div>
                <div style="text-align:center;"><span style="color:#f87171; font-size:0.7rem;">SHORT PUT</span><br/><b>${s['strikes']['short_put']}</b></div>
                <div style="text-align:center; border:1px solid #334155; padding:5px 10px; border-radius:5px;"><span style="color:#94a3b8; font-size:0.7rem;">SPOT</span><br/><b>${s['spot']:.0f}</b></div>
                <div style="text-align:center;"><span style="color:#f87171; font-size:0.7rem;">SHORT CALL</span><br/><b>${s['strikes']['short_call']}</b></div>
                <div style="text-align:center;"><span style="color:#34d399; font-size:0.7rem;">LONG CALL</span><br/><b>${s['strikes']['long_call']}</b></div>
            </div>
            """, unsafe_allow_html=True)
            
            st.write("")
            
            # Execution Settings
            de1, de2, de3, de4 = st.columns([1, 1, 1, 1])
            with de1:
                esc_step = st.number_input("הסלמה (%)", 0.5, 5.0, 1.0, step=0.5, key="single_esc_step")
            with de2:
                esc_wait = st.number_input("המתנה (ש')", 30, 600, 180, step=30, key="single_esc_wait")
            with de3:
                sched_time = st.text_input("שעת כניסה (EST)", value="15:50", key="single_sched")
            with de4:
                st.write("") # Spacer
                immediate = st.checkbox("🚀 מיד", value=True, key="single_immediate", help="בטל כדי לתזמן לשעה הנקובה")
            
            if st.button(f"📤 פתח Iron Condor ל-{ticker}", type="primary", use_container_width=True):
                custom_esc = {"step_pct": esc_step, "wait_secs": esc_wait}
                if immediate:
                    _execute_earnings_sequence(ticker, bot_mode, multiplier, wing_width, qty, scheduled_time=None, custom_esc=custom_esc)
                else:
                    api_ibkr.schedule_internal_task(sched_time, _execute_earnings_sequence, ticker, bot_mode, multiplier, wing_width, qty, scheduled_time=None, custom_esc=custom_esc)
                    st.success(f"המערכת תמתין ותריץ את הניתוח המלא מול יאהו והוורקר בשעה {sched_time}")

    # 2. Wholesale Wholesale Mode (NEW)
    with st.expander("📦 Wholesale Iron Condor (Bulk & Timer)", expanded=False):
        st.write("מצב סיטונאי: הרץ מספר רב של מניות לפי שעה מוגדרת.")
        bulk_tks = st.text_area("רשימת מניות (מופרדות בפסיק)", placeholder="AAPL, MSFT, GOOGL", key="wholesale_tickers")
        
        wb1, wb2, wb3 = st.columns([1, 1, 1])
        with wb1:
            exec_time = st.time_input("שעת ביצוע (שעון מחשב)", value=datetime.now().time(), key="wholesale_time")
        with wb2:
            w_qty = st.number_input("חוזים לכל מניה", 1, 10, 1, key="wholesale_qty")
        with wb3:
            st.write("") # Spacer
            w_immediate = st.checkbox("🚀 שלח מיד", value=False, key="wholesale_immediate")
            
        if st.button("🎬 התחל תהליך סיטונאי", use_container_width=True):
            tickers = [t.strip().upper() for t in bulk_tks.split(",") if t.strip()]
            time_str = None if w_immediate else exec_time.strftime("%H:%M")
            esc_settings = {"step_pct": 5.0, "wait_secs": 40}
            
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            for i, tk in enumerate(tickers):
                status_text.write(f"מעבד {tk} ({i+1}/{len(tickers)})...")
                _execute_earnings_sequence(tk, bot_mode, qty=w_qty, scheduled_time=time_str, custom_esc=esc_settings)
                progress_bar.progress((i + 1) / len(tickers))
            
            status_text.write("✅ תהליך סיטונאי הושלם!")
            st.success(f"בוצעו {len(tickers)} פקודות {'באופן מיידי' if time_str is None else 'לשעה ' + time_str}")

    # 3. Active Positions & Closing
    st.markdown("---")
    st.markdown('<div id="ic_positions" style="font-size:1.1rem; font-weight:700; color:#f87171; margin-bottom:15px;">📋 ניהול פוזיציות וסגירות (פירוט רגליים)</div>', unsafe_allow_html=True)
    
    # Group positions by ticker
    ic_candidates = {}
    for p in positions:
        # Note: worker only sends ticker and position. We need to find the rest.
        if p.get("secType") == "OPT" or "position" in p:
            t = p.get("ticker", "UNKNOWN")
            if t not in ic_candidates: ic_candidates[t] = []
            
            # If data is missing (None in your screenshot), it means the worker 
            # is only sending 'position' and 'ticker'. 
            # We will use the 'position' as 'qty' and show what we have.
            if "qty" not in p and "position" in p:
                p["qty"] = p["position"]
            
            ic_candidates[t].append(p)

    if not ic_candidates:
        st.info("לא נמצאו אופציות פעילות בתיק.")
    else:
        for t, legs in ic_candidates.items():
            with st.expander(f"🔍 ניהול פוזיציית {t} ({len(legs)} רגליים)", expanded=True):
                st.write("בחר רגליים לסגירה:")
                selected_legs_indices = []
                
                # Table-like header
                h_cols = st.columns([0.5, 1, 1, 1, 1, 1.5])
                h_cols[0].write("בחר")
                h_cols[1].write("Strike")
                h_cols[2].write("Right")
                h_cols[3].write("Qty")
                h_cols[4].write("Expiry")
                h_cols[5].write("conId")
                
                for i, l in enumerate(legs):
                    cols = st.columns([0.5, 1, 1, 1, 1, 1.5])
                    # Checkbox to select this leg
                    is_selected = cols[0].checkbox("", key=f"final_sel_{t}_{i}", value=True)
                    if is_selected:
                        selected_legs_indices.append(i)
                    
                    cols[1].write(l.get("strike", "—"))
                    cols[2].write(l.get("right", "—"))
                    cols[3].write(l.get("qty", "—"))
                    cols[4].write(l.get("expiry", "—"))
                    cols[5].code(l.get("conId", "—"))
                
                close_time = st.text_input(f"שעת סגירה ל-{t}", value="09:30", key=f"close_time_{t}")
                if st.button(f"🛑 סגור/תזמן סגירה ל-{t}", key=f"final_close_btn_{t}", type="primary", use_container_width=True):
                    selected_data = [legs[idx] for idx in selected_legs_indices]
                    if not selected_data:
                        st.warning("נא לבחור לפחות רגל אחת לסגירה.")
                    else:
                        api_ibkr.schedule_internal_task(close_time, _execute_ic_close_direct, t, selected_data, bot_mode)
                        st.success(f"סגירת הפוזיציה במחירי זמן-אמת תוזמנה לשעה {close_time}")
    # 4. Escalation Monitor (Premium Redesign)

    # 4. Escalation Monitor (Premium Redesign)
    st.markdown("---")
    m_col1, m_col2 = st.columns([3, 1])
    with m_col1:
        st.markdown('<div style="font-size:1.2rem; font-weight:800; color:#38bdf8;">📊 מוניטור הסלמות וביצועים (LIVE)</div>', unsafe_allow_html=True)
    with m_col2:
        auto_refresh = st.toggle("רענון אוטומטי", value=True, key="monitor_auto_ref")

    if not auto_refresh:
        if st.button("🔄 רענן עכשיו", use_container_width=True):
            st.rerun()

    try:
        esc_data = api_ibkr.get_escalations_status()
        escalations = esc_data.get("escalations", [])
        
        if not escalations:
            st.info("אין הסלמות פעילות כרגע. כל הפקודות בוצעו או בוטלו.")
        else:
            # Layout as cards
            for i in range(0, len(escalations), 2):
                cols = st.columns(2)
                for j in range(2):
                    if i + j < len(escalations):
                        e = escalations[i+j]
                        with cols[j]:
                            status = e.get("status", "ACTIVE")
                            color = "#34d399" if status == "ACTIVE" else ("#fbbf24" if status == "PENDING" else "#94a3b8")
                            
                            st.markdown(f"""
                            <div style="background:rgba(15,23,42,0.6); border-left:4px solid {color}; border-radius:8px; padding:15px; margin-bottom:10px; border:1px solid rgba(255,255,255,0.05);">
                                <div style="display:flex; justify-content:space-between; align-items:center;">
                                    <span style="font-size:1.1rem; font-weight:800; color:#f1f5f9;">{e.get('ticker')}</span>
                                    <span style="font-size:0.7rem; padding:2px 8px; border-radius:12px; background:{color}33; color:{color}; font-weight:700;">{status}</span>
                                </div>
                                <div style="display:grid; grid-template-columns: repeat(2, 1fr); gap:10px; margin-top:10px;">
                                    <div><span style="color:#64748b; font-size:0.7rem;">ID</span><br/><span style="font-family:monospace;">#{e.get('order_id')}</span></div>
                                    <div><span style="color:#64748b; font-size:0.7rem;">מחיר נוכחי</span><br/><b style="color:#38bdf8;">${abs(e.get('current_price', 0)):.2f}</b></div>
                                    <div><span style="color:#64748b; font-size:0.7rem;">שלב</span><br/><b>{e.get('escalation_count', 0)}</b></div>
                                    <div><span style="color:#64748b; font-size:0.7rem;">התחלה</span><br/><span style="font-size:0.8rem;">{e.get('started_at','')[11:16]}</span></div>
                                </div>
                            </div>
                            """, unsafe_allow_html=True)
                            if st.button(f"🛑 בטל #{e.get('order_id')}", key=f"cancel_{e.get('order_id')}", use_container_width=True):
                                api_ibkr.cancel_escalation(e.get('order_id'))
                                st.success(f"ביטול נשלח ל-{e.get('order_id')}")
                                time.sleep(1)
                                st.rerun()
            
            if auto_refresh:
                time.sleep(5)
                st.rerun()

    except Exception as e:
        st.error(f"שגיאה בטעינת המוניטור: {e}")

if __name__ == "__main__":
    render_earnings_tab()
