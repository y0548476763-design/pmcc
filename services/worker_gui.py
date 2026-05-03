import streamlit as st
import requests
import pandas as pd

st.set_page_config(page_title="IBKR Worker Sandbox", layout="wide")
st.markdown("<h1 style='text-align:right;'>🎮 דשבורד בדיקות - IBKR Worker</h1>", unsafe_allow_html=True)

WORKER_URL = "http://127.0.0.1:8001"

# --- טאבים ---
tabs = st.tabs(["🚀 ביצוע פקודות", "📊 ניטור והסלמות", "📁 תיק ומידע"])

with tabs[0]:
    with st.form("order_creator"):
        st.subheader("יצירת פקודה (בודדת או קומבו)")
        c1, c2, c3 = st.columns(3)
        action = c1.selectbox("פעולה כללית", ["BUY", "SELL"])
        qty = c2.number_input("כמות", value=1, min_value=1)
        price = c3.number_input("מחיר לימיט התחלתי", value=0.0, format="%.2f")
        
        st.write("---")
        legs = []
        for i in range(4):
            with st.expander(f"רגל {i+1}"):
                l1, l2, l3 = st.columns(3)
                sym = l1.text_input("סימול", key=f"sym{i}")
                stype = l2.selectbox("סוג", ["OPT", "STK"], key=f"st{i}")
                l_act = l3.selectbox("פעולה", ["BUY", "SELL"], key=f"la{i}")
                
                if stype == "OPT" and sym:
                    l4, l5, l6 = st.columns(3)
                    exp = l4.text_input("פקיעה (YYYYMMDD)", key=f"ex{i}")
                    strk = l5.number_input("סטרייק", key=f"sk{i}")
                    rgh = l6.selectbox("סוג", ["C", "P"], key=f"rg{i}")
                    legs.append({"symbol": sym, "secType": "OPT", "action": l_act, "ratio": 1, "expiry": exp, "strike": strk, "right": rgh})
                elif sym:
                    legs.append({"symbol": sym, "secType": "STK", "action": l_act, "ratio": 1})

        st.write("---")
        st.subheader("הגדרות הסלמה")
        e1, e2, e3 = st.columns(3)
        esc_p = e1.slider("אחוז שיפור מחיר", 0.0, 0.05, 0.01)
        esc_t = e2.number_input("שניות בין שלבים", value=30)
        esc_m = e3.number_input("מקסימום שלבים", value=5)
        
        if st.form_submit_button("שגר פקודה לוורקר"):
            try:
                payload = {"action": action, "total_qty": qty, "lmt_price": price, "legs": legs, "esc_pct": esc_p, "esc_interval": esc_t, "max_steps": esc_m}
                res = requests.post(f"{WORKER_URL}/submit", json=payload).json()
                st.success(f"הפקודה נשלחה! מזהה: {res['order_id']}")
            except Exception as e:
                st.error(f"שגיאה בשליחה: {e}")

with tabs[1]:
    if st.button("רענן מוניטור הסלמות"):
        try:
            monitor = requests.get(f"{WORKER_URL}/monitor").json()
            if monitor:
                for oid, info in monitor.items():
                    st.info(f"פקודה {oid} | סטטוס: {info['status']}")
                    for step in info.get('steps', []):
                        st.text(f"  • {step}")
                    if info.get('final_fill'): st.write(f"**מחיר ביצוע סופי:** {info['final_fill']}")
                    st.divider()
            else:
                st.info("אין הסלמות פעילות")
        except Exception as e:
            st.error(f"שגיאה במוניטור: {e}")

with tabs[2]:
    if st.button("טען תיק נוכחי"):
        try:
            port = requests.get(f"{WORKER_URL}/portfolio").json()
            if port:
                st.table(pd.DataFrame(port))
            else:
                st.info("התיק ריק או לא מחובר")
        except Exception as e:
            st.error(f"שגיאה בתיק: {e}")
    
    st.write("---")
    t_sym = st.text_input("הכנס סימול למידע יווניות ומחיר")
    if t_sym and st.button("קבל מידע Ticker"):
        try:
            t_data = requests.get(f"{WORKER_URL}/ticker/{t_sym}").json()
            st.json(t_data)
        except Exception as e:
            st.error(f"שגיאה בשליפת מידע: {e}")
