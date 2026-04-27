"""
app.py — PMCC NextOffice v3.1 — Display Only (Refreshed)
All heavy work delegated to:
  api_ibkr (:8002) → portfolio positions + cash
  api_yahoo (:8001) → technicals, LEAPS search, quant analysis
"""
import os, time
import streamlit as st
import requests

st.set_page_config(
    page_title="PMCC NextOffice — נדל\"ן דיגיטלי",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── CSS ──
CSS = os.path.join(os.path.dirname(__file__), "ui", "styles.css")
with open(CSS, encoding="utf-8") as f:
    st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

import config, settings_manager
from ui.portfolio_tab   import render_portfolio_tab
from ui.short_calls_tab import render_short_calls_tab
from ui.roll_tab        import render_roll_tab
from ui.cash_tab        import render_cash_tab
from ui.bot_tab         import render_bot_tab
from ui.earnings_tab    import render_earnings_tab

YAHOO = config.YAHOO_API_URL   # http://localhost:8001
IBKR  = config.IBKR_API_URL    # http://localhost:8002
_TIMEOUT = 5

# ── Session defaults ───────────────────────────────────────────────────────
def _init_positions():
    from datetime import datetime
    raw = list(config.DEMO_POSITIONS)
    for p in raw:
        if "expiry" in p and p["expiry"] != "—":
            try:
                exp = datetime.strptime(p["expiry"].replace("-",""), "%Y%m%d")
                p["dte"] = (exp.date() - datetime.utcnow().date()).days
            except: p["dte"] = 0
        else: p["dte"] = 9999
    return raw

for k, v in {
    "positions":          _init_positions(),
    "positions_source":   "DEMO",
    "connected":          False,
    "tws_cash":           0.0,
    "tws_netliq":         0.0,
    "tws_account_id":     "—",
    "quant_results":      {},
    "console_logs":       [],
    "last_live_refresh":  0,
}.items():
    st.session_state.setdefault(k, v)

def _log(lvl, msg):
    from datetime import datetime
    logs = st.session_state.get("console_logs", [])
    logs.insert(0, {"level": lvl, "msg": msg, "ts": datetime.utcnow().strftime("%H:%M:%S")})
    st.session_state["console_logs"] = logs[:200]

# ── Portfolio refresh from api_ibkr (every 60s) ───────────────────────────
now = time.time()
if now - st.session_state["last_live_refresh"] > 60:
    try:
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
        pass   # api_ibkr offline → stay on DEMO
    st.session_state["last_live_refresh"] = now

positions = st.session_state["positions"]
qr        = st.session_state.get("quant_results", {})
bot_mode  = settings_manager.get_bot_mode()
is_conn   = st.session_state.get("connected", False)

# ── Status Bar ────────────────────────────────────────────────────────────
from datetime import datetime
try:    from zoneinfo import ZoneInfo
except: from backports.zoneinfo import ZoneInfo
ny  = datetime.now(ZoneInfo("America/New_York"))
mkt = (ny.weekday() < 5) and (ny.replace(hour=9,minute=30,second=0) <= ny <= ny.replace(hour=16,minute=0,second=0))
bm  = {0:"🔴 בוט כבוי", 1:"🟡 בוט מעקב", 2:"🟢 בוט פעיל"}
src = st.session_state.get("positions_source","DEMO")

st.markdown(f"""
<div class="status-bar">
  <span class="brand">PMCC NextOffice</span>
  <span class="status-chip {'online' if mkt else 'offline'}">
    {'🟢 שוק פתוח' if mkt else '🔴 שוק סגור'} &nbsp;{ny.strftime('%H:%M')} NY
  </span>
  <span class="status-chip {'online' if is_conn else 'offline'}">
    {'🟢 ' + st.session_state.get('tws_account_id','—') if is_conn else '🔴 לא מחובר'}
  </span>
  <span class="status-chip">📡 {src}</span>
  <span class="status-chip {'online' if bot_mode==2 else ('warning' if bot_mode==1 else 'offline')}">
    {bm.get(bot_mode)}
  </span>
  <span class="status-chip" style="margin-right:auto;color:var(--text-sm)">
    {len(positions)} פוזיציות · {ny.strftime('%H:%M:%S')}
  </span>
</div>
""", unsafe_allow_html=True)

# ── Header ────────────────────────────────────────────────────────────────
bBadge = '<span class="badge badge-green">● LIVE</span>' if is_conn else '<span class="badge badge-amber">● DEMO</span>'
c1, c2, c3 = st.columns([5, 1, 1])
with c1:
    st.markdown(f"""
    <div class="page-header">
      <div class="page-title">מערכת ניהול PMCC | נדל"ן דיגיטלי {bBadge}</div>
    </div>""", unsafe_allow_html=True)
with c2:
    if not is_conn:
        if st.button("🔗 חבר", key="header_connect", use_container_width=True):
            with st.spinner("מחפש Gateway פעיל (7496/4002)..."):
                try:
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
                    st.error(f"api_ibkr לא זמין: {e}")
with c3:
    if st.button("🔄 רענן", key="refresh", use_container_width=True):
        st.session_state["last_live_refresh"] = 0
        st.rerun()

# ── Tabs ──────────────────────────────────────────────────────────────────
t1, t2, t3, t4, t5, t6 = st.tabs(["📊 פרוטפוליו", "📞 שורט קולים", "🔄 גלגול LEAPS", "💰 מזומן", "🤖 בוט", "📈 Model B — Earnings"])

with t1:
    col_q, _ = st.columns([1, 4])
    with col_q:
        if st.button("⚡ נתח תיק", type="primary", key="run_quant", use_container_width=True):
            with st.spinner("מנתח ב-api_yahoo... (עשוי לקחת כדקה)"):
                try:
                    wl = settings_manager.get_watchlist()
                    r = requests.post(
                        f"{YAHOO}/analyse",
                        json={"positions": positions, "watchlist": wl},
                        timeout=120,   # analysis can take ~60s for multiple tickers
                    )
                    if r.status_code == 200:
                        data = r.json()
                        if data.get("ok"):
                            # Reconstruct QuantResult objects from dicts
                            from quant_engine import QuantResult
                            qr_raw = data.get("results", {})
                            st.session_state["quant_results"] = {
                                t: QuantResult(**v) for t, v in qr_raw.items()
                            }
                            _log("INFO", f"✅ ניתוח הושלם — {len(qr_raw)} מניות")
                        else:
                            st.error(f"שגיאת ניתוח: {data}")
                    else:
                        st.error(f"api_yahoo החזיר {r.status_code}")
                except requests.exceptions.ConnectionError:
                    st.error("❌ api_yahoo לא פועל על פורט 8001. הרץ את run_pmcc.bat")
                except Exception as e:
                    st.error(f"שגיאת ניתוח: {e}")
            st.rerun()
    render_portfolio_tab(positions, st.session_state.get("quant_results", {}))

with t2: render_short_calls_tab(positions, st.session_state.get("quant_results", {}), None)
with t3: render_roll_tab()
with t4: render_cash_tab(positions, st.session_state.get("quant_results", {}), None)
with t5: render_bot_tab(None)
with t6: render_earnings_tab(None)
