"""
ui/earnings_tab.py — Model B: Earnings IV Crush (Iron Condor)
Architecture:
  Phase 1 - Yahoo Finance: option chain scan, ATM straddle, EM calc, 4-strike selection
  Phase 2 - IBKR: qualify 4 legs (get conId), send BAG order
  Exit     - Next morning at 09:30 EST: close all 4 legs
"""
import streamlit as st
import time
from datetime import datetime, timezone, timedelta

import config
import api_ibkr
import api_yahoo

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

def _fetch_structure(ticker: str):
    """
    Phase 1: Fetch spot, nearest expiration, ATM straddle → Expected Move.
    Uses the Yahoo SDK.
    """
    data = api_yahoo.get_expected_move(ticker)
    if not data.get("ok"):
        err = data.get('error', data.get('detail', 'Unknown error'))
        raise ValueError(f"שגיאה משירות Yahoo: {err}")
        
    d = data["data"]
    return {
        "spot": d["spot"],
        "expiry": d["expiry"],
        "dte": d["dte"],
        "call_ask": d["call_ask"],
        "put_ask": d["put_ask"],
        "expected_move": d["expected_move"],
    }

def _build_strikes(spot, em, multiplier, wing_width):
    safe_em = em * multiplier
    sc = _round_strike(spot + safe_em, spot)
    sp = _round_strike(spot - safe_em, spot)
    lc = _round_strike(sc + wing_width, spot)
    lp = _round_strike(sp - wing_width, spot)
    return {"short_call": sc, "long_call": lc, "short_put": sp, "long_put": lp}

# ── Render ─────────────────────────────────────────────────────────────────

def render_earnings_tab(tws=None) -> None:

    st.markdown("""
<div style="padding:0.5rem 0 1rem 0;">
<div style="font-size:1.5rem;font-weight:900;
background:linear-gradient(135deg,#f59e0b,#ef4444);
-webkit-background-clip:text;-webkit-text-fill-color:transparent;">
📈 Model B — Earnings IV Crush
</div>
<div style="font-size:0.75rem;color:#64748b;margin-top:4px;">
Iron Condor לפני דוחות · Yahoo Finance לחישוב · IBKR לאישור conId + ביצוע BAG
</div>
</div>""", unsafe_allow_html=True)

    # ══════════════════════════════════════════════════
    # SECTION A — Setup parameters
    # ══════════════════════════════════════════════════
    st.markdown('<div style="font-size:0.75rem;font-weight:700;color:#f59e0b;'
                'text-transform:uppercase;letter-spacing:0.07em;padding:0.3rem 0 0.6rem;">A — הגדרות אסטרטגיה</div>',
                unsafe_allow_html=True)

    ca1, ca2, ca3, ca4 = st.columns([1.5, 1.2, 1.2, 1.2], gap="small")
    with ca1:
        ticker = st.text_input("טיקר", value=st.session_state.get("earn_ticker","GOOGL"),
                               key="earn_ticker_inp", placeholder="GOOGL").upper().strip()
    with ca2:
        multiplier = st.number_input("EM Safety ×",
                                     min_value=1.0, max_value=1.5, value=1.15, step=0.05,
                                     key="earn_mult",
                                     help="1.15 = Short legs 15% מחוץ ל-EM")
    with ca3:
        wing_width = st.number_input("Wing ($)",
                                     min_value=2.5, max_value=50.0, value=10.0, step=2.5,
                                     key="earn_wing",
                                     help="מרחק Long מ-Short בכל צד")
    with ca4:
        qty = st.number_input("חוזים", 1, 50, 1, key="earn_qty")

    scan_btn = st.button("🔍 סרוק Yahoo Finance", key="earn_scan",
                         type="primary", use_container_width=True)

    # ── Scan ──────────────────────────────────────────
    if scan_btn and ticker:
        st.session_state["earn_ticker"] = ticker
        st.session_state.pop("earn_data", None)
        st.session_state.pop("earn_strikes", None)
        with st.spinner(f"שולף נתונים עבור {ticker}..."):
            try:
                data    = _fetch_structure(ticker)
                strikes = _build_strikes(data["spot"], data["expected_move"],
                                         multiplier, wing_width)
                st.session_state["earn_data"]    = data
                st.session_state["earn_strikes"] = strikes
                st.session_state["saved_earn_mult"]    = multiplier
                st.session_state["saved_earn_wing"]    = wing_width
                st.session_state["saved_earn_qty"]     = qty
            except Exception as e:
                st.error(f"❌ {e}")

    data    = st.session_state.get("earn_data")
    strikes = st.session_state.get("earn_strikes")

    if not (data and strikes):
        st.info("הכנס טיקר ולחץ סרוק כדי לקבל נתונים.")
        return

    # ══════════════════════════════════════════════════
    # SECTION B — Expected Move analysis
    # ══════════════════════════════════════════════════
    st.markdown('<div style="font-size:0.75rem;font-weight:700;color:#f59e0b;'
                'text-transform:uppercase;letter-spacing:0.07em;padding:0.8rem 0 0.5rem;">B — ניתוח Expected Move</div>',
                unsafe_allow_html=True)

    saved_mult = st.session_state.get("saved_earn_mult", 1.15)
    saved_wing = st.session_state.get("saved_earn_wing", 10.0)

    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("מחיר נוכחי", f"${data['spot']:.2f}")
    m2.metric("פקיעה", data['expiry'])
    m3.metric("DTE", f"{data['dte']}d")
    m4.metric("Call Ask", f"${data['call_ask']:.2f}")
    m5.metric("Put Ask",  f"${data['put_ask']:.2f}")
    m6.metric(f"EM ± (×{saved_mult})",
              f"${data['expected_move']:.2f}",
              f"Safe: ${data['expected_move']*saved_mult:.2f}")

    # ══════════════════════════════════════════════════
    # SECTION C — Iron Condor strikes visual
    # ══════════════════════════════════════════════════
    st.markdown('<div style="font-size:0.75rem;font-weight:700;color:#f59e0b;'
                'text-transform:uppercase;letter-spacing:0.07em;padding:0.6rem 0 0.5rem;">C — Iron Condor Strikes</div>',
                unsafe_allow_html=True)

    spot = data["spot"]
    em   = data["expected_move"]
    sc, lc = strikes["short_call"], strikes["long_call"]
    sp, lp = strikes["short_put"],  strikes["long_put"]

    st.markdown(f"""
<div style="background:rgba(15,23,42,0.95);border:1px solid rgba(99,102,241,0.35);border-radius:14px;padding:1.2rem 1rem;margin-bottom:0.8rem;">
<div style="display:grid;grid-template-columns:repeat(5,1fr);gap:0.6rem;text-align:center;align-items:center;">

<div style="background:rgba(52,211,153,0.1);border:1px solid rgba(52,211,153,0.5);border-radius:10px;padding:0.7rem 0.3rem;">
<div style="font-size:0.58rem;color:#64748b;text-transform:uppercase;margin-bottom:2px;">Long Put</div>
<div style="font-size:1.35rem;font-weight:900;color:#34d399;">${lp:.0f}</div>
<div style="font-size:0.6rem;color:#64748b;">BUY</div>
</div>

<div style="background:rgba(248,113,113,0.12);border:1px solid rgba(248,113,113,0.55);border-radius:10px;padding:0.7rem 0.3rem;">
<div style="font-size:0.58rem;color:#64748b;text-transform:uppercase;margin-bottom:2px;">Short Put</div>
<div style="font-size:1.35rem;font-weight:900;color:#f87171;">${sp:.0f}</div>
<div style="font-size:0.6rem;color:#94a3b8;">{((spot-sp)/spot*100):.1f}% OTM</div>
</div>

<div style="background:rgba(99,102,241,0.15);border:2px solid rgba(99,102,241,0.6);border-radius:10px;padding:0.7rem 0.3rem;">
<div style="font-size:0.58rem;color:#94a3b8;text-transform:uppercase;margin-bottom:2px;">SPOT</div>
<div style="font-size:1.4rem;font-weight:900;color:#f1f5f9;">${spot:.0f}</div>
<div style="font-size:0.6rem;color:#6366f1;">EM ±${em:.2f}</div>
</div>

<div style="background:rgba(248,113,113,0.12);border:1px solid rgba(248,113,113,0.55);border-radius:10px;padding:0.7rem 0.3rem;">
<div style="font-size:0.58rem;color:#64748b;text-transform:uppercase;margin-bottom:2px;">Short Call</div>
<div style="font-size:1.35rem;font-weight:900;color:#f87171;">${sc:.0f}</div>
<div style="font-size:0.6rem;color:#94a3b8;">{((sc-spot)/spot*100):.1f}% OTM</div>
</div>

<div style="background:rgba(52,211,153,0.1);border:1px solid rgba(52,211,153,0.5);border-radius:10px;padding:0.7rem 0.3rem;">
<div style="font-size:0.58rem;color:#64748b;text-transform:uppercase;margin-bottom:2px;">Long Call</div>
<div style="font-size:1.35rem;font-weight:900;color:#34d399;">${lc:.0f}</div>
<div style="font-size:0.6rem;color:#64748b;">BUY</div>
</div>

</div>
<div style="text-align:center;margin-top:0.8rem;font-size:0.72rem;color:#64748b;">
Wing: <b style="color:#f59e0b;">${saved_wing:.0f}</b> per side &nbsp;|&nbsp;
Max Profit: <b style="color:#34d399;">קרדיט × {qty} חוזים × 100</b> &nbsp;|&nbsp;
Max Loss: <b style="color:#f87171;">${(saved_wing - 0):.0f} - קרדיט</b>
</div>
</div>""", unsafe_allow_html=True)

    # ══════════════════════════════════════════════════
    # SECTION D — Entry Execution + Scheduling
    # ══════════════════════════════════════════════════
    st.markdown('<div style="font-size:0.75rem;font-weight:700;color:#f59e0b;'
                'text-transform:uppercase;letter-spacing:0.07em;padding:0.6rem 0 0.5rem;">D — כניסה — שליחת Iron Condor</div>',
                unsafe_allow_html=True)

    de1, de2, de3, de4 = st.columns([1.5, 1.5, 1.5, 1], gap="small")
    with de1:
        esc_step = st.number_input("הסלמה (%)", 0.5, 5.0, 1.0, step=0.5, key="earn_esc_step")
    with de2:
        esc_wait = st.number_input("המתנה לפני הסלמה (שניות)", 30, 600, 120, step=30, key="earn_esc_wait")
    with de3:
        # Default to 15:50 EST (entry before earnings)
        sched_time = st.text_input("שעת כניסה (HH:MM EST)",
                                   value="15:50", key="earn_entry_time",
                                   placeholder="15:50",
                                   help="ריק = שלח מיד. 15:50 = לפני סגירת שוק.")
    with de4:
        st.markdown('<div style="height:28px;"></div>', unsafe_allow_html=True)
        immediate = st.checkbox("🚀 שלח מיד", value=False, key="earn_immediate")

    entry_btn = st.button("📤 שלח Iron Condor (4 Legs)",
                          key="earn_exec", type="primary", use_container_width=True)

    if entry_btn:
        saved_ticker = st.session_state.get("earn_ticker", ticker)
        saved_qty    = st.session_state.get("saved_earn_qty", qty)
        expiry       = data["expiry"]
        sched        = None if immediate else (sched_time.strip() or None)

        leg_defs = [
            {"strike": sc, "right": "C", "action": "SELL"},
            {"strike": lc, "right": "C", "action": "BUY"},
            {"strike": sp, "right": "P", "action": "SELL"},
            {"strike": lp, "right": "P", "action": "BUY"},
        ]

        # Phase 2A: Qualify all 4 legs → get conId + live mid
        qual_results = []
        qualify_ok = True
        qual_info = st.empty()

        with st.spinner("🔄 מאמת 4 רגליים ב-IBKR (שולף conId)..."):
            for ld in leg_defs:
                q = _qualify(saved_ticker, ld["strike"], expiry, ld["right"])
                if not q.get("ok"):
                    st.error(f"❌ {ld['action']} {ld['right']} ${ld['strike']:.0f} — "
                             f"{q.get('detail', q.get('error', 'שגיאה'))}")
                    qualify_ok = False
                    break
                qual_results.append({**ld, "conId": q["conId"],
                                     "mid": q.get("mid", 0), "expiry": expiry})

        if qualify_ok and len(qual_results) == 4:
            # Show qualification table
            rows_html = ""
            credit = 0.0
            for ql in qual_results:
                sign = -1 if ql["action"] == "BUY" else 1
                credit += sign * ql["mid"]
                rows_html += f"""<tr>
                  <td style="color:{'#f87171' if ql['action']=='SELL' else '#34d399'}">{ql['action']}</td>
                  <td>{ql['right']}</td>
                  <td style="font-weight:700;">${ql['strike']:.0f}</td>
                  <td style="color:#64748b;">{expiry}</td>
                  <td style="color:#94a3b8;">{ql['conId']}</td>
                  <td style="color:#f1f5f9;">${ql['mid']:.2f}</td>
                </tr>"""

            st.markdown(f"""
<div style="background:rgba(15,23,42,0.9);border:1px solid rgba(52,211,153,0.3);
border-radius:10px;padding:0.8rem;margin:0.5rem 0;">
<table style="width:100%;border-collapse:collapse;font-size:0.8rem;">
<thead><tr style="color:#64748b;font-size:0.68rem;text-transform:uppercase;">
<th>Action</th><th>Right</th><th>Strike</th><th>Expiry</th><th>conId</th><th>Mid</th>
</tr></thead>
<tbody>{rows_html}</tbody>
</table>
<div style="text-align:center;margin-top:0.6rem;font-size:0.9rem;">
קרדיט נטו: <b style="color:#34d399;font-size:1.1rem;">${max(0,credit):.2f}</b>
{'&nbsp;|&nbsp; שמיר 15:50 EST ⏰' if sched else '&nbsp;|&nbsp; ⚡ שולח מיד'}
</div>
</div>""", unsafe_allow_html=True)

            # Phase 2B: Send BAG order
            legs_payload = [
                {"strike": ql["strike"], "expiry": expiry,
                 "right": ql["right"], "action": ql["action"], "qty": saved_qty, "conId": ql.get("conId")}
                for ql in qual_results
            ]
            limit_price = round(max(0.01, credit), 2)

            payload = {
                "ticker": saved_ticker,
                "legs": legs_payload,
                "limit_price": limit_price,
                "use_market": False,
                "escalation_step_pct": float(esc_step),
                "escalation_wait_secs": int(esc_wait),
            }
            if sched:
                payload["scheduled_time"] = sched

            with st.spinner("⏳ שולח Iron Condor BAG..."):
                try:
                    resp = api_ibkr.place_combo(payload["ticker"], payload["legs"], payload["limit_price"], payload["use_market"], payload["escalation_step_pct"], payload["escalation_wait_secs"])
                    rj = resp
                except Exception as e:
                    st.error(f"❌ תקשורת: {e}")
                    rj = {}

            if rj.get("ok"):
                oid = rj.get("result", {}).get("order_id", "—")
                if sched:
                    st.success(f"⏰ Iron Condor מתוזמן ל-{sched} EST | Order ID: {oid}")
                else:
                    st.success(f"✅ Iron Condor נשלח! Order ID: {oid}")
                    st.balloons()
                # Save for exit
                st.session_state["earn_open_order"] = {
                    "ticker": saved_ticker, "expiry": expiry,
                    "legs": legs_payload, "qty": saved_qty,
                    "order_id": oid, "credit": round(max(0,credit), 2)
                }
            else:
                st.error(f"❌ {rj.get('detail', rj.get('error', rj))}")

    # ══════════════════════════════════════════════════
    # SECTION E — Exit: Close position next morning
    # ══════════════════════════════════════════════════
    open_order = st.session_state.get("earn_open_order")
    if open_order:
        st.markdown('<div style="font-size:0.75rem;font-weight:700;color:#ef4444;'
                    'text-transform:uppercase;letter-spacing:0.07em;padding:0.8rem 0 0.5rem;">E — יציאה — סגירת Iron Condor</div>',
                    unsafe_allow_html=True)

        st.markdown(f"""
<div style="background:rgba(239,68,68,0.08);border:1px solid rgba(239,68,68,0.3);
border-radius:10px;padding:0.8rem 1rem;margin-bottom:0.7rem;">
<b style="color:#f87171;">Iron Condor פתוח:</b> &nbsp;
{open_order['ticker']} | {open_order['expiry']} |
<span style="color:#34d399;">קרדיט: ${open_order['credit']:.2f}</span> |
Order ID: {open_order['order_id']}
</div>""", unsafe_allow_html=True)

        ee1, ee2 = st.columns(2)
        with ee1:
            # Default exit time: 09:30 next morning EST
            exit_time = st.text_input("שעת יציאה (HH:MM EST)",
                                      value="09:30", key="earn_exit_time",
                                      help="למחרת בבוקר — לאחר פתיחת השוק")
        with ee2:
            exit_immediate = st.checkbox("⚡ סגור מיד (Market)", value=False, key="earn_exit_imm")

        ec1, ec2 = st.columns(2)
        with ec1:
            if st.button("🔴 שלח פקודת סגירה (BUY to Close)",
                         key="earn_exit_btn", use_container_width=True):
                exit_sched = None if exit_immediate else (exit_time.strip() or None)
                # Reverse all legs: SELL→BUY, BUY→SELL
                close_legs = []
                for l in open_order["legs"]:
                    close_legs.append({
                        **l,
                        "action": "BUY" if l["action"] == "SELL" else "SELL"
                    })

                with st.spinner("🔄 מאמת חוזים לסגירה..."):
                    qual_close = []
                    ok = True
                    for cl in close_legs:
                        q = _qualify(open_order["ticker"], cl["strike"],
                                     open_order["expiry"], cl["right"])
                        if not q.get("ok"):
                            st.error(f"❌ {cl['right']} ${cl['strike']}: {q.get('detail')}")
                            ok = False
                            break
                        qual_close.append(cl)

                if ok:
                    close_payload = {
                        "ticker": open_order["ticker"],
                        "legs": qual_close,
                        "limit_price": 0.01,
                        "use_market": exit_immediate,
                        "escalation_step_pct": 2.0,
                        "escalation_wait_secs": 60,
                    }
                    if exit_sched:
                        close_payload["scheduled_time"] = exit_sched

                    with st.spinner("⏳ שולח פקודת סגירה..."):
                        try:
                            cr = api_ibkr.place_combo(
                                ticker=close_payload["ticker"],
                                legs=close_payload["legs"],
                                limit_price=close_payload["limit_price"],
                                use_market=close_payload["use_market"],
                                escalation_step_pct=close_payload["escalation_step_pct"],
                                escalation_wait_secs=close_payload["escalation_wait_secs"],
                                scheduled_time=close_payload.get("scheduled_time")
                            )
                        except Exception as e:
                            cr = {"ok": False, "error": str(e)}

                    if cr.get("ok"):
                        coid = cr.get("result", {}).get("order_id", "—")
                        if exit_sched:
                            st.success(f"⏰ סגירה מתוזמנת ל-{exit_sched} EST | {coid}")
                        else:
                            st.success(f"✅ פקודת סגירה נשלחה! {coid}")
                        st.session_state.pop("earn_open_order", None)
                    else:
                        st.error(f"❌ {cr.get('detail', cr.get('error', cr))}")

        with ec2:
            if st.button("🗑️ נקה פוזיציה שמורה", key="earn_clear_open"):
                st.session_state.pop("earn_open_order", None)
                st.rerun()

    # ══════════════════════════════════════════════════
    # SECTION F — Live Monitor
    # ══════════════════════════════════════════════════
    st.markdown("---")
    st.markdown('<div style="font-size:0.75rem;font-weight:700;color:#94a3b8;'
                'text-transform:uppercase;letter-spacing:0.07em;padding:0.5rem 0;">F — Live Order Monitor</div>',
                unsafe_allow_html=True)

    col_mon, col_ref = st.columns([4, 1])
    with col_ref:
        if st.button("🔄 רענן", key="earn_mon_ref"):
            st.rerun()

    try:
        r = api_ibkr.get_active_orders()
        orders = r.get("orders", []) if isinstance(r, dict) else []
        if not orders:
            st.info("אין פקודות פעילות.")
        else:
            import pandas as pd
            df = pd.DataFrame(orders)
            # Keep relevant columns if they exist
            cols = [c for c in ["internal_id","ticker","strike","expiry",
                                 "status","current_price","escalation_count","is_combo"]
                    if c in df.columns]
            df = df[cols].rename(columns={
                "internal_id": "ID", "ticker": "Ticker", "strike": "Strike",
                "expiry": "Expiry", "status": "Status", "current_price": "Price",
                "escalation_count": "Escals", "is_combo": "Combo?"
            })
            st.dataframe(df, use_container_width=True, hide_index=True)
    except Exception as e:
        st.warning(f"api_ibkr לא זמין: {e}")
