import sys, re
content = open('ui/earnings_tab.py', 'r', encoding='utf-8').read()

pattern = re.compile(r'def _fetch_structure.*?return \{\s*"spot".*?"expected_move": em,\s*\}', re.DOTALL)

new_func = """def _fetch_structure(ticker: str):
    \"\"\"
    Phase 1: Fetch spot, nearest expiration, ATM straddle → Expected Move.
    Uses the Yahoo SDK.
    \"\"\"
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
    }"""

new_content = pattern.sub(new_func, content)

# Also fix the top imports
import_old = """import ssl
ssl._create_default_https_context = ssl._create_unverified_context

import streamlit as st
import requests
import time
from datetime import datetime, timezone, timedelta

import config

YAHOO = config.YAHOO_API_URL
IBKR  = config.IBKR_API_URL
_TIMEOUT = 30"""

import_new = """import streamlit as st
import time
from datetime import datetime, timezone, timedelta

import config
import api_ibkr
import api_yahoo

_TIMEOUT = 30"""

new_content = new_content.replace(import_old, import_new)

if content != new_content:
    open('ui/earnings_tab.py', 'w', encoding='utf-8').write(new_content)
    print('Success')
else:
    print('Failed to match')
