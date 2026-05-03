import streamlit as st
import requests
import pandas as pd

st.set_page_config(page_title="IBKR Worker Sandbox", layout="wide")
st.markdown("<h1 style='text-align:right;'>🎮 דשבורד ביצוע - IBKR Worker</h1>", unsafe_allow_html=True)

WORKER_URL = "http://127.0.0.1:8001"

# --- סטטוס חיבור בראש הדף ---
with st.sidebar:
    st.subheader("🌐 סטטוס חיבור")
    try:
        status = requests.get(f"{WORKER_URL}/status", timeout=5).json()
        if status.get("connected"):
            st.success(f"מחובר ל-IBKR (Port: {status.get('port')})")
        else:
            st.error("לא מחובר ל-IBKR")
            if st.button("חבר עכשיו"):
                requests.get(f"{WORKER_URL}/status") # זה יריץ ensure_connection
                st.rerun()
    except Exception:
        st.warning("לא ניתן לתקשר עם ה-Worker (פורט 8001)")

tabs = st.tabs(["🚀 בניית פקודות וביצוע", "🔍 חילוץ ConID", "📊 מוניטור IBKR", "📁 תיק ומידע"])

with tabs[1]:
    st.subheader("מנוע איתור ConID (חובה לקומבו)")
    with st.form("qualify_form"):
        q_sym = st.text_input("סימול")
        q_type = st.selectbox("סוג", ["OPT", "STK"])
        q_exp = st.text_input("פקיעה (YYYYMMDD) לאופציות")
        q_str = st.number_input("סטרייק", value=0.0)
        q_rgh = st.selectbox("Right", ["C", "P"])
        if st.form_submit_button("חלץ ConID משרתי אינטראקטיב"):
            try:
                payload = {"symbol": q_sym, "secType": q_type, "action": "BUY", "ratio": 1, "expiry": q_exp, "strike": q_str, "right": q_rgh}
                res = requests.post(f"{WORKER_URL}/qualify", json=payload).json()
                if res.get("ok"):
                    st.success(f"ConID: **{res['con_id']}** | Symbol: {res['localSymbol']}")
                else:
                    st.error(res.get("error"))
            except Exception as e:
                st.error(f"שגיאה בתקשורת: {e}")

with tabs[0]:
    st.info("💡 המערכת מחלצת ConID אוטומטית אם תזין את פרטי האופציה (סימול, פקיעה, סטרייק וסוג). אין חובה להזין ConID ידני.")
    with st.form("order_creator"):
        st.subheader("יצירת פקודה (בודדת או קומבו)")
        c1, c2, c3 = st.columns(3)
        action = c1.selectbox("פעולה כללית", ["BUY", "SELL"])
        qty = c2.number_input("כמות", value=1, min_value=1)
        price = c3.number_input("מחיר לימיט התחלתי", value=0.0, format="%.2f")
        
        st.write("---")
        legs = []
        for i in range(4):
            with st.expander(f"רגל {i+1} (אם יש לך ConID, מלא רק אותו ואת הפעולה)"):
                l1, l2, l3, l4 = st.columns(4)
                con = l1.number_input("ConID (אופציונלי)", value=0, key=f"con{i}")
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
                    if stype == "OPT" and sym:
                        leg_data.update({"expiry": exp, "strike": strk, "right": rgh})
                    legs.append(leg_data)

        st.write("---")
        st.subheader("הגדרות הסלמה (Price Improvement)")
        e1, e2, e3 = st.columns(3)
        esc_p = e1.slider("אחוז שיפור בכל שלב", 0.0, 0.05, 0.01)
        esc_t = e2.number_input("שניות המתנה בין שלבים", value=10)
        esc_m = e3.number_input("מקסימום שלבים", value=3)
        
        if st.form_submit_button("שגר פקודה לשרת"):
            try:
                payload = {"action": action, "total_qty": qty, "lmt_price": price, "legs": legs, "esc_pct": esc_p, "esc_interval": esc_t, "max_steps": esc_m}
                res = requests.post(f"{WORKER_URL}/submit", json=payload).json()
                st.success(f"הפקודה נשלחה! מזהה: {res['order_id']}")
            except Exception as e:
                st.error(f"שגיאה בשליחה: {e}")

with tabs[2]:
    st.subheader("🖥️ מצב פקודות מול שרתי IBKR (Live Status)")
    if st.button("רענן מצב פקודות"):
        try:
            monitor = requests.get(f"{WORKER_URL}/monitor").json()
            if not monitor: st.info("אין פקודות פעילות.")
            for oid, info in monitor.items():
                st.markdown(f"### מזהה: {oid}")
                st.markdown(f"**סטטוס פנימי (לולאה):** {info['internal_status']}")
                
                # צבע לפי סטטוס מאינטראקטיב
                ib_stat = info.get('ib_status', 'N/A')
                stat_color = "green" if ib_stat in ['Submitted', 'Filled'] else ("red" if ib_stat == 'Cancelled' else "orange")
                st.markdown(f"**סטטוס משרתי IBKR:** <span style='color:{stat_color};font-weight:bold;'>{ib_stat}</span>", unsafe_allow_html=True)
                
                for step in info.get('steps', []): st.text(f"  • {step}")
                
                if info.get('errors'):
                    st.error("הודעות משרתי אינטראקטיב / דחיות:")
                    for e in info['errors']: st.write(f"- {e}")
                st.divider()
        except Exception as e:
            st.error(f"שגיאה במוניטור: {e}")

with tabs[3]:
    if st.button("טען תיק נוכחי"):
        try:
            res = requests.get(f"{WORKER_URL}/portfolio", timeout=10)
            if res.status_code == 200:
                port = res.json()
                if port:
                    st.table(pd.DataFrame(port))
                else:
                    st.info("תיק ריק או לא מחובר")
            else:
                st.error(f"שגיאת שרת: {res.status_code}")
        except Exception as e:
            st.error(f"שגיאת תקשורת עם הוורקר: {e}")
    
    st.write("---")
    t_sym = st.text_input("הכנס סימול למידע יווניות ומחיר")
    if t_sym and st.button("קבל מידע Ticker"):
        try:
            res = requests.get(f"{WORKER_URL}/ticker/{t_sym}", timeout=10)
            if res.status_code == 200:
                st.json(res.json())
            else:
                st.error(f"שגיאת שרת: {res.status_code}")
        except Exception as e:
            st.error(f"שגיאה בשליפת מידע: {e}")
