import streamlit as st
import requests
import pandas as pd

st.set_page_config(page_title="IBKR Worker Sandbox", layout="wide")
st.markdown("<h1 style='text-align:right;'>🎮 דשבורד ביצוע - IBKR Worker</h1>", unsafe_allow_html=True)

WORKER_URL = "http://127.0.0.1:8001"

# --- Sidebar ---
with st.sidebar:
    st.subheader("🌐 סטטוס חיבור")
    try:
        status = requests.get(f"{WORKER_URL}/status", timeout=5).json()
        if status.get("connected"):
            st.success(f"מחובר (Port: {status.get('port')})")
        else:
            st.error("לא מחובר")
            if st.button("רענן חיבור"): st.rerun()
    except: st.warning("אין תקשורת עם הוורקר")

    st.write("---")
    if st.button("🛑 ביטול חירום (Cancel All)", type="primary"):
        try:
            res = requests.post(f"{WORKER_URL}/cancel_all").json()
            st.error(res.get("status", "בוצע ביטול"))
        except Exception as e: st.error(f"שגיאה: {e}")

# --- Initialize Session State ---
if "quote_result" not in st.session_state:
    st.session_state["quote_result"] = None

tabs = st.tabs(["🚀 ביצוע פקודות", "🔍 ConID", "📈 ציטוט נכס (Greeks)", "📊 מוניטור IBKR", "💼 תיק ומזומן"])

# --- TAB 2: Greeks ---
with tabs[2]:
    st.subheader("📊 נתוני שוק ויווניות בזמן אמת")
    with st.form("quote_form"):
        c1, c2, c3, c4 = st.columns(4)
        q_sym = c1.text_input("סימול", value="AAPL")
        q_exp = c2.text_input("פקיעה (YYYYMMDD) - אופציונלי")
        q_str = c3.number_input("סטרייק", value=0.0)
        q_rgh = c4.selectbox("Right", ["None", "C", "P"])
        
        submit_quote = st.form_submit_button("שלח בקשת ציטוט")
        
    if submit_quote:
        params = {}
        if q_exp: params["expiry"] = q_exp
        if q_str > 0: params["strike"] = q_str
        if q_rgh != "None": params["right"] = q_rgh
        
        try:
            res = requests.get(f"{WORKER_URL}/ticker/{q_sym}", params=params).json()
            if "error" in res:
                st.error(res["error"])
                st.session_state["quote_result"] = None
            else:
                st.session_state["quote_result"] = res
        except Exception as e:
            st.error(f"שגיאת תקשורת: {e}")

    # Display results from session state (persists across reruns)
    if st.session_state["quote_result"]:
        res = st.session_state["quote_result"]
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("מחיר שוק", f"${res.get('price', 0) if res.get('price') else 'N/A'}")
        m2.metric("Bid", f"${res.get('bid', 0) if res.get('bid') else 'N/A'}")
        m3.metric("Ask", f"${res.get('ask', 0) if res.get('ask') else 'N/A'}")
        m4.metric("IV", f"{res.get('iv', 0):.2%}" if res.get('iv') else "N/A")
        
        st.write("---")
        st.subheader("🧬 יווניות (Greeks)")
        g1, g2, g3, g4 = st.columns(4)
        def fmt_g(v, p=".3f"):
            if v is None: return "N/A"
            return f"{v:{p}}"
        
        g1.metric("Delta", fmt_g(res.get('delta')))
        g2.metric("Gamma", fmt_g(res.get('gamma'), ".4f"))
        g3.metric("Theta", fmt_g(res.get('theta')))
        g4.metric("Vega", fmt_g(res.get('vega')))
        
        mp = res.get('modelPrice')
        st.info(f"מחיר מודל: " + (f"${mp:.2f}" if mp is not None else "N/A"))

# --- TAB 1: ConID ---
with tabs[1]:
    st.subheader("חילוץ ConID")
    with st.form("qualify_form"):
        q_sym_c = st.text_input("סימול")
        q_type_c = st.selectbox("סוג", ["OPT", "STK"])
        q_exp_c = st.text_input("פקיעה (YYYYMMDD)")
        q_str_c = st.number_input("סטרייק", value=0.0)
        q_rgh_c = st.selectbox("Right", ["C", "P"])
        if st.form_submit_button("חלץ ConID"):
            res = requests.post(f"{WORKER_URL}/qualify", json={"symbol": q_sym_c, "secType": q_type_c, "action": "BUY", "ratio": 1, "expiry": q_exp_c, "strike": q_str_c, "right": q_rgh_c}).json()
            if res.get("ok"): st.success(f"ConID: {res['con_id']} | {res['localSymbol']}")
            else: st.error(res.get("error"))

# --- TAB 0: ביצוע פקודות ---
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
        st.write("הסלמה (רלוונטי ל-LMT בלבד):")
        e1, e2, e3 = st.columns(3)
        esc_p = e1.slider("אחוז שיפור", 0.0, 0.05, 0.01)
        esc_t = e2.number_input("שניות המתנה", value=10)
        esc_m = e3.number_input("מקסימום שלבים", value=3)
        
        if st.form_submit_button("שגר פקודה"):
            payload = {"action": action, "order_type": order_type, "total_qty": qty, "lmt_price": price, "legs": legs, "esc_pct": esc_p, "esc_interval": esc_t, "max_steps": esc_m}
            res = requests.post(f"{WORKER_URL}/submit", json=payload).json()
            st.success(res['message'])

# --- TAB 3: מוניטור IBKR ---
with tabs[3]:
    if st.button("רענן מוניטור"):
        monitor = requests.get(f"{WORKER_URL}/monitor").json()
        if not monitor:
            st.info("אין פקודות במוניטור כרגע")
        for oid, info in monitor.items():
            st.markdown(f"### מזהה: {oid} | פנימי: {info['internal_status']} | IBKR: {info.get('ib_status', 'N/A')}")
            for step in info.get('steps', []): st.text(f"  • {step}")
            if info.get('final_fill'): st.success(f"מחיר סופי: {info['final_fill']}")
            for e in info.get('errors', []): st.error(e)
            st.divider()

# --- TAB 4: תיק ומזומן ---
with tabs[4]:
    if st.button("טען יתרות ומזומן"):
        acc = requests.get(f"{WORKER_URL}/account").json()
        if "error" not in acc:
            c1, c2, c3 = st.columns(3)
            c1.metric("שווי התיק", f"${acc.get('NetLiquidation', 0):,.2f}")
            c2.metric("מזומן פנוי", f"${acc.get('AvailableFunds', 0):,.2f}")
            c3.metric("סך המזומן", f"${acc.get('TotalCashValue', 0):,.2f}")
    
    st.write("---")
    if st.button("טען פוזיציות בתיק"):
        port = requests.get(f"{WORKER_URL}/portfolio").json()
        if port:
            df = pd.DataFrame(port)
            df.columns = ["סימול", "כמות", "עלות ממוצעת", "מחיר שוק", "רווח לא ממומש"]
            st.dataframe(df.style.format({"עלות ממוצעת": "${:.2f}", "מחיר שוק": "${:.2f}", "רווח לא ממומש": "${:.2f}"}), use_container_width=True)
        else:
            st.info("אין פוזיציות פתוחות בתיק")
