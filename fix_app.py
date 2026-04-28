import re

def fix_app():
    with open('app.py', 'r', encoding='utf-8') as f:
        content = f.read()

    # 1. Imports
    content = content.replace("import requests", "import api_ibkr\nimport api_yahoo")

    # 2. Portfolio refresh
    old_portfolio = """    try:
        r = requests.get(f"{IBKR}/portfolio", timeout=_TIMEOUT)
        if r.status_code == 200:
            data = r.json()
            src  = data.get("source", "DEMO")
            is_c = data.get("tws_connected", False)
            st.session_state["connected"]        = is_c
            st.session_state["positions_source"] = src
            st.session_state["tws_account_id"]   = data.get("account_id", "—")
            st.session_state["tws_cash"]         = float(data.get("cash", 0))
            st.session_state["tws_netliq"]       = float(data.get("net_liq", 0))
            live = data.get("positions", [])
            if live:
                st.session_state["positions"] = live
            _log("INFO", f"✅ פורטפוליו עודכן מ-api_ibkr ({src})")
    except Exception:
        pass   # api_ibkr offline → stay on DEMO"""

    new_portfolio = """    try:
        data = api_ibkr.get_positions()
        if data.get("ok"):
            src  = data.get("source", "LIVE")
            is_c = True
            st.session_state["connected"]        = is_c
            st.session_state["positions_source"] = src
            st.session_state["tws_account_id"]   = data.get("account_id", "—")
            st.session_state["tws_cash"]         = float(data.get("cash", 0))
            st.session_state["tws_netliq"]       = float(data.get("net_liq", 0))
            live = data.get("positions", [])
            if live:
                st.session_state["positions"] = live
            _log("INFO", f"✅ פורטפוליו עודכן מ-api_ibkr ({src})")
    except Exception:
        pass   # api_ibkr offline → stay on DEMO"""
    
    content = content.replace(old_portfolio, new_portfolio)

    # 3. Connection logic
    old_connect = """                try:
                    # /connect/LIVE in our api_ibkr tries LIVE then DEMO then 7497
                    r = requests.get(f"{IBKR}/connect/LIVE", timeout=12)
                    data = r.json()
                    if r.status_code == 200 and data.get("ok"):
                        st.session_state["connected"] = True
                        st.session_state["positions_source"] = data.get("mode")
                        st.session_state["last_live_refresh"] = 0
                        st.success(f"מחובר! חשבון: {data.get('account_id')}")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error("לא נמצא Gateway פעיל בפורטים המוגדרים.")
                except Exception as e:
                    st.error(f"שגיאת תקשורת עם ה-API: {e}")
                    st.error(f"api_ibkr לא זמין: {e}")"""

    new_connect = """                try:
                    data = api_ibkr.connect("LIVE")
                    if data.get("ok"):
                        st.session_state["connected"] = True
                        st.session_state["positions_source"] = data.get("mode")
                        st.session_state["last_live_refresh"] = 0
                        st.success(f"מחובר בהצלחה!")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error("לא נמצא Gateway פעיל בפורטים המוגדרים.")
                except Exception as e:
                    st.error(f"שגיאת תקשורת: {e}")"""
    
    content = content.replace(old_connect, new_connect)
    
    # 4. Quant logic
    old_quant = """                    r = requests.post(
                        f"{YAHOO}/analyse",
                        json={"positions": positions, "watchlist": wl},
                        timeout=120,   # analysis can take ~60s for multiple tickers
                    )
                    if r.status_code == 200:
                        data = r.json()
                        if data.get("ok"):"""
                        
    new_quant = """                    import requests
                    r = requests.post(
                        f"{YAHOO}/analyse",
                        json={"positions": positions, "watchlist": wl},
                        timeout=120,   # analysis can take ~60s for multiple tickers
                    )
                    if r.status_code == 200:
                        data = r.json()
                        if data.get("ok"):"""
    content = content.replace(old_quant, new_quant)

    with open('app.py', 'w', encoding='utf-8') as f:
        f.write(content)

fix_app()
print('Fixed app.py')
