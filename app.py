"""
app.py — PMCC NextOffice v3.0 — RTL, Clean
"""
import asyncio, os, time
try:
    loop = asyncio.get_event_loop()
    if loop.is_closed(): raise RuntimeError
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

import streamlit as st

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
from tws_client   import get_client
from quant_engine import get_engine
from ui.portfolio_tab   import render_portfolio_tab
from ui.short_calls_tab import render_short_calls_tab
from ui.roll_tab        import render_roll_tab
from ui.cash_tab        import render_cash_tab
from ui.bot_tab         import render_bot_tab

# ── Session Init (with DTE calculation for Demo) ──
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

_DEFAULTS = {
    "connected": False, 
    "positions": _init_positions(),
    "positions_source": "DEMO", 
    "quant_results": {},
    "console_logs": [], 
    "tws_cash": 0.0,
    "tws_netliq": 0.0, 
    "tws_account_id": "—",
    "last_live_refresh": 0,
    "first_analysis_done": False,
}
for k, v in _DEFAULTS.items():
    st.session_state.setdefault(k, v)

if "tws"    not in st.session_state: st.session_state["tws"]    = get_client()
if "engine" not in st.session_state: st.session_state["engine"] = get_engine()

tws    = st.session_state["tws"]
engine = st.session_state["engine"]

def _log(lvl, msg):
    from datetime import datetime
    logs = st.session_state.get("console_logs", [])
    logs.insert(0, {"level": lvl, "msg": msg, "ts": datetime.utcnow().strftime("%H:%M:%S")})
    st.session_state["console_logs"] = logs[:200]

engine.set_log_callback(_log)
tws.set_log_callback(_log)

# ── Auto Connect Logic ──
if not st.session_state["connected"]:
    # Throttled auto-connect (every 5 mins if failed)
    if time.time() - st.session_state.get("last_auto_conn", 0) > 300:
        st.session_state["last_auto_conn"] = time.time()
        mode = settings_manager.get_connection_profile().get("mode", "DEMO")
        # Try primary mode then fallback
        modes_to_try = [mode, "DEMO" if mode == "LIVE" else "LIVE"]
        for m in modes_to_try:
            try:
                if tws.connect(m):
                    st.session_state["connected"] = True
                    st.session_state["positions_source"] = m
                    _log("INFO", f"✅ חיבור אוטומטי הוקם: {m}")
                    break
            except: pass

# ── Live Data Sync ──
if st.session_state["connected"] and tws.connected:
    now = time.time()
    if now - st.session_state["last_live_refresh"] > 60:
        try:
            tws._refresh_account()
            st.session_state.update({
                "tws_account_id": tws.account_id,
                "tws_cash":       tws.cash_balance,
                "tws_netliq":     tws.net_liquidation,
            })
            live_data = tws.get_positions()
            if live_data:
                st.session_state["positions"] = live_data
                st.session_state["positions_source"] = "LIVE" if tws.mode == "LIVE" else "DEMO"
            st.session_state["last_live_refresh"] = now
        except Exception as e:
            _log("ERROR", f"סנכרון נכשל: {e}")

# ── Initial Analysis ──
if not st.session_state["first_analysis_done"] and st.session_state["positions"]:
    try:
        wl = settings_manager.get_watchlist()
        res = engine.analyse_portfolio(st.session_state["positions"], watchlist=wl)
        st.session_state["quant_results"] = res
        st.session_state["first_analysis_done"] = True
    except: pass

positions  = st.session_state["positions"]
qr         = st.session_state.get("quant_results", {})
bot_mode   = settings_manager.get_bot_mode()
is_conn    = st.session_state.get("connected", False)

# ── UI: Status Bar ──
from datetime import datetime
try:    from zoneinfo import ZoneInfo
except: from backports.zoneinfo import ZoneInfo
ny   = datetime.now(ZoneInfo("America/New_York"))
mkt  = (ny.weekday() < 5) and (ny.replace(hour=9,minute=30,second=0) <= ny <= ny.replace(hour=16,minute=0,second=0))
bm   = {0:"🔴 בוט כבוי", 1:"🟡 בוט מעקב", 2:"🟢 בוט פעיל"}
src  = st.session_state.get("positions_source","DEMO")

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

# ── UI: Header ──
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
            with st.spinner("מתחבר..."):
                if tws.connect("LIVE") or tws.connect("DEMO"):
                    st.session_state["connected"] = True
                    st.rerun()
                else:
                    st.error("חיבור נכשל")
    else:
        st.write("")
with c3:
    if st.button("🔄 רענן", key="refresh", use_container_width=True):
        if is_conn and tws.ib: 
            tws.ib.reqPositions()
            tws.ib.sleep(0.5)
        st.session_state["last_live_refresh"] = 0
        st.rerun()

# ── UI: Tabs ──
t1, t2, t3, t4, t5 = st.tabs(["📊 פרוטפוליו", "📞 שורט קולים", "🔄 גלגול LEAPS", "💰 מזומן", "🤖 בוט"])

with t1:
    col_q, _ = st.columns([1,4])
    with col_q:
        if st.button("⚡ נתח תיק", type="primary", key="run_quant", use_container_width=True):
            with st.spinner("מנתח..."):
                wl = settings_manager.get_watchlist()
                res = engine.analyse_portfolio(positions, watchlist=wl)
                st.session_state["quant_results"] = res
            st.rerun()
    render_portfolio_tab(positions, qr)

with t2: render_short_calls_tab(positions, qr, tws)
with t3: render_roll_tab(tws)
with t4: render_cash_tab(positions, qr, tws)
with t5: render_bot_tab(tws)
