import streamlit as st
import requests
import pandas as pd

st.set_page_config(page_title="IBKR Worker Sandbox", layout="wide")
st.markdown("<h1 style='text-align:right;'>🎮 דשבורד ביצוע - IBKR Worker</h1>", unsafe_allow_html=True)

WORKER_URL = "http://127.0.0.1:8001"

# --- לוח בקרה צדדי (חיבורים וניתוקים) ---
with st.sidebar:
    st.subheader("🌐 שליטה בחיבור ל-Gateway")
    try:
        status = requests.get(f"{WORKER_URL}/status", timeout=5).json()
        if status.get("connected"):
            st.success(f"מחובר בהצלחה (Port: {status.get('port')})")
            if st.button("🔌 נתק מאינטראקטיב"):
                requests.post(f"{WORKER_URL}/disconnect")
                st.rerun()
        else:
            st.error("לא מחובר כעת")
            if st.button("🟢 התחבר ל-Gateway (4002)", type="primary"):
                with st.spinner("מתחבר..."):
                    res = requests.post(f"{WORKER_URL}/connect").json()
                    if "Error" in res.get("status", ""):
                        st.error(res["status"])
                    else:
                        st.rerun()
    except Exception as e: 
        st.warning("אין תקשורת עם שרת הוורקר (האם הוא רץ בפורט 8001?)")

    st.write("---")
    st.subheader("פעולות חירום")
    if st.button("🛑 ביטול כל הפקודות (Cancel All)"):
        try:
            res = requests.post(f"{WORKER_URL}/cancel_all").json()
            st.error(res.get("status", "בוצע ביטול"))
        except Exception as e: st.error(f"שגיאה: {e}")

tabs = st.tabs(["🚀 ביצוע פקודות", "🔍 ציטוט ו-ConID", "📊 מוניטור פקודות", "💼 תיק ומזומן"])

with tabs[1]:
    st.subheader("איתור ConID ונתוני שוק (יווניות)")
    with st.form("ticker_form"):
        t1, t2, t3 = st.columns(3)
        t_con = t1.number_input("ConID (מומלץ לאופציות)", value=0)
        t_sym = t2.text_input("סימול (למשל AAPL)")
        t_type = t3.selectbox("סוג נכס", ["OPT", "STK"])
        
        t4, t5, t6 = st.columns(3)
        t_exp = t4.text_input("פקיעה (YYYYMMDD)")
        t_str = t5.number_input("סטרייק", value=0.0)
        t_rgh = t6.selectbox("סוג אופציה", ["C", "P"])
        
        if st.form_submit_button("קבל נתונים"):
            payload = {"symbol": t_sym or "N/A", "secType": t_type, "action": "BUY", "ratio": 1, "con_id": t_con}
            if t_type == "OPT": payload.update({"expiry": t_exp, "strike": t_str, "right": t_rgh})
            res = requests.post(f"{WORKER_URL}/ticker", json=payload).json()
            if "error" in res:
                st.error(res["error"])
            else:
                st.success(f"נתונים עבור: {res.get('symbol')} (ConID: {res.get('con_id')})")
                c_price, c_bid, c_ask, c_iv = st.columns(4)
                c_price.metric("מחיר שוק", f"${res.get('price', 0)}")
                c_bid.metric("Bid", f"${res.get('bid', 0)}")
                c_ask.metric("Ask", f"${res.get('ask', 0)}")
                c_iv.metric("IV", f"{res.get('iv', 0)}")
                if res.get("delta") is not None:
                    st.write("**יווניות (Greeks):**")
                    g1, g2, g3, g4 = st.columns(4)
                    g1.metric("Delta", round(res.get('delta', 0), 4))
                    g2.metric("Gamma", round(res.get('gamma', 0), 4))
                    g3.metric("Theta", round(res.get('theta', 0), 4))
                    g4.metric("Vega", round(res.get('vega', 0), 4))
                
                if res.get("avg_iv") is not None or res.get("iv_rank") is not None:
                    st.write("**תנודתיות נכס הבסיס (Underlying Volatility):**")
                    v1, v2, v3, v4 = st.columns(4)
                    
                    def fmt_v(val, p=".2%"):
                        if val is None: return "N/A"
                        try: return f"{val:{p}}"
                        except: return "N/A"
                    
                    v1.metric("Avg IV (Index)", fmt_v(res.get('avg_iv')))
                    v2.metric("Hist Vol (30d)", fmt_v(res.get('hist_vol')))
                    v3.metric("IV Rank", fmt_v(res.get('iv_rank'), ".1%"))
                    v4.metric("IV Range (1Y)", f"{fmt_v(res.get('iv_low'), '.1%')} - {fmt_v(res.get('iv_high'), '.1%')}")

with tabs[0]:
    with st.form("order_creator"):
        c1, c2, c3, c4 = st.columns(4)
        action = c1.selectbox("פעולה", ["BUY", "SELL"])
        order_type = c2.selectbox("סוג פקודה", ["LMT", "MKT"])
        qty = c3.number_input("כמות", value=1, min_value=1)
        price = c4.number_input("מחיר LMT", value=0.0, format="%.2f")
        
        st.write("---")
        legs = []
        for i in range(4):
            with st.expander(f"רגל {i+1}"):
                l1, l2, l3, l4 = st.columns(4)
                con = l1.number_input("ConID", value=0, key=f"con{i}")
                sym = l2.text_input("סימול", key=f"sym{i}")
                stype = l3.selectbox("סוג", ["OPT", "STK"], key=f"st{i}")
                l_act = l4.selectbox("פעולה ברגל", ["BUY", "SELL"], key=f"la{i}")
                if stype == "OPT":
                    c_exp, c_strk, c_rgh = st.columns(3)
                    exp = c_exp.text_input("פקיעה", key=f"ex{i}")
                    strk = c_strk.number_input("סטרייק", key=f"sk{i}")
                    rgh = c_rgh.selectbox("סוג", ["C", "P"], key=f"rg{i}")
                if con > 0 or sym:
                    leg_data = {"action": l_act, "ratio": 1, "secType": stype}
                    if con > 0: leg_data["con_id"] = con
                    if sym: leg_data["symbol"] = sym
                    if stype == "OPT" and sym: leg_data.update({"expiry": exp, "strike": strk, "right": rgh})
                    legs.append(leg_data)

        st.write("---")
        e1, e2, e3 = st.columns(3)
        esc_p = e1.slider("אחוז שיפור מחיר (להסלמה)", 0.0, 0.05, 0.01)
        esc_t = e2.number_input("שניות המתנה בין הסלמות", value=10)
        esc_m = e3.number_input("מקסימום שלבים", value=3)
        
        if st.form_submit_button("שגר פקודה"):
            payload = {"action": action, "order_type": order_type, "total_qty": qty, "lmt_price": price, "legs": legs, "esc_pct": esc_p, "esc_interval": esc_t, "max_steps": esc_m}
            res = requests.post(f"{WORKER_URL}/submit", json=payload).json()
            st.success(res.get('message', 'הפקודה נשלחה'))

with tabs[2]:
    if st.button("רענן מוניטור"):
        monitor = requests.get(f"{WORKER_URL}/monitor").json()
        for oid, info in monitor.items():
            st.markdown(f"### מזהה: {oid} | פנימי: {info['internal_status']} | IBKR: {info.get('ib_status', 'N/A')}")
            for step in info.get('steps', []): st.text(f"  • {step}")
            if info.get('final_fill'): st.success(f"מחיר סופי: {info['final_fill']}")
            for e in info.get('errors', []): st.error(e)
            st.divider()

with tabs[3]:
    if st.button("טען יתרות ומזומן"):
        try:
            acc = requests.get(f"{WORKER_URL}/account").json()
            if "error" not in acc:
                col1, col2, col3 = st.columns(3)
                col1.metric("Net Liquidation (שווי התיק)", f"${float(acc.get('NetLiquidation', 0)):,.2f}")
                col2.metric("Available Funds (מזומן פנוי)", f"${float(acc.get('AvailableFunds', 0)):,.2f}")
                col3.metric("Margin (ביטחונות בשימוש)", f"${float(acc.get('FullInitMarginReq', 0)):,.2f}")
                
                with st.expander("לפרטים נוספים"):
                    st.json(acc)
            else:
                st.error(acc["error"])
        except Exception as e:
            st.error(f"שגיאה במשיכת נתוני חשבון: {e}")

    st.write("---")
    
    if st.button("רענן תיק"):
        try:
            data = requests.get(f"{WORKER_URL}/portfolio").json()
            if data and isinstance(data, list):
                df = pd.DataFrame(data)
                
                # סידור עמודות בצורה הגיונית: נכס, כמות, מחיר, רווח, ופרטי האופציה
                ordered_cols = ["symbol", "qty", "marketPrice", "unrealizedPNL", "strike", "expiry", "right", "avg_cost", "con_id"]
                actual_cols = [c for c in ordered_cols if c in df.columns]
                remaining_cols = [c for c in df.columns if c not in actual_cols]
                df = df[actual_cols + remaining_cols]
                
                st.dataframe(df, use_container_width=True, hide_index=True)
            else:
                st.info("התיק ריק כעת")
        except Exception as e:
            st.error(f"שגיאה במשיכת התיק: {e}")
