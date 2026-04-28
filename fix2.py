import sys
content = open('ui/short_calls_tab.py', 'r', encoding='utf-8').read()

import_old = """import streamlit as st
from datetime import datetime
from typing import Optional
import requests
import config
import settings_manager

YAHOO = config.YAHOO_API_URL
IBKR  = config.IBKR_API_URL"""

import_new = """import streamlit as st
from datetime import datetime
from typing import Optional
import config
import settings_manager
import api_ibkr
import api_yahoo"""

content = content.replace(import_old, import_new)

tg_old = """def _send_telegram(msg: str) -> bool:
    \"\"\"Send a Telegram message. Returns True on success.\"\"\"
    # Always notify internal hub first
    try:
        requests.post(f"{IBKR}/api/notify", json={"message": msg}, timeout=2)
    except Exception:
        pass"""

tg_new = """def _send_telegram(msg: str) -> bool:
    \"\"\"Send a Telegram message. Returns True on success.\"\"\"
    # Always notify internal hub first
    api_ibkr.notify(msg)"""

content = content.replace(tg_old, tg_new)

search_old = """                    with st.spinner(f"מחפש שורט קול ל-{ticker} ב-api_yahoo..."):
                        try:
                            r = requests.get(f"{YAHOO}/options/search", params={
                                "ticker": ticker, "min_dte": min_dte, "max_dte": max_dte,
                                "target_delta": tgt_delta, "right": "C", "n": 3
                            }, timeout=15)
                            data = r.json()
                            if data.get("ok"):
                                candidates = data.get("data", [])
                            else:
                                st.error(f"שגיאה מ-api_yahoo: {data.get('detail', data)}")
                                candidates = []
                        except requests.exceptions.ConnectionError:
                            st.error("❌ api_yahoo לא פועל על פורט 8001")
                            candidates = []"""

search_new = """                    with st.spinner(f"מחפש שורט קול ל-{ticker}..."):
                        data = api_yahoo.search_options(ticker, min_dte, max_dte, tgt_delta, "C", 3)
                        if data.get("ok"):
                            candidates = data.get("data", [])
                        else:
                            st.error(f"שגיאה: {data.get('error', data.get('detail', ''))}")
                            candidates = []"""

content = content.replace(search_old, search_new)

open('ui/short_calls_tab.py', 'w', encoding='utf-8').write(content)
print('Fixed short_calls_tab')
