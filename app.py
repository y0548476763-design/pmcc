"""
app.py — GRAVITI PMCC Quant-Dashboard
Main Streamlit entry point.
Run with: streamlit run app.py
"""
import asyncio
import os
import sys

# ── AsyncIO patch for Streamlit's non-main thread ────────────────────────────
# ib_insync/eventkit tries to get the running event loop at import time.
# Streamlit runs scripts in a worker thread with no event loop → RuntimeError.
# Fix: create and set a new event loop for this thread before importing ib_insync.
try:
    loop = asyncio.get_event_loop()
    if loop.is_closed():
        raise RuntimeError("closed")
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

import streamlit as st

# ── Page config (must be first Streamlit call) ────────────────────────────────
st.set_page_config(
    page_title="מערכת ניהול PMCC · NextOffice (v1.0)",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Load Custom CSS ───────────────────────────────────────────────────────────
CSS_PATH = os.path.join(os.path.dirname(__file__), "ui", "styles.css")
with open(CSS_PATH, encoding="utf-8") as f:
    st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

# ── Backend imports ────────────────────────────────────────────────────────────
import config
from tws_client  import get_client
from quant_engine import get_engine

# ── UI imports ────────────────────────────────────────────────────────────────
from ui.sidebar        import render_sidebar
from ui.portfolio_tab  import render_portfolio_tab
from ui.matrix_tab     import render_matrix_tab
from ui.payoff_tab     import render_payoff_tab
from ui.theta_tab      import render_theta_tab
from ui.console_tab    import render_console_tab
from ui.order_tab      import render_order_tab
from ui.reports_tab    import render_reports_tab


# ── Session State Defaults ────────────────────────────────────────────────────
def _init_session() -> None:
    defaults = {
        "mode":               "DEMO",
        "connected":          False,
        "positions":          list(config.DEMO_POSITIONS),
        "quant_results":      {},
        "console_logs":       [],
        "show_panic_confirm": False,
        "matrix_chain":       [],
        "matrix_selected_idx": -1,
        "escalation_mins":    config.ESCALATION_WAIT_MINUTES,
        "delta_target":       0.30,
        "order_ticker":       "AAPL",
        "order_strike":       220.0,
        "order_expiry":       "2026-04-17",
        "order_mid":          5.00,
        "order_ask":          5.30,
        "order_delta":        0.30,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


_init_session()

# ── Singletons ────────────────────────────────────────────────────────────────
if "tws_client_instance" not in st.session_state:
    st.session_state["tws_client_instance"] = get_client()
if "quant_engine_instance" not in st.session_state:
    st.session_state["quant_engine_instance"] = get_engine()

tws    = st.session_state["tws_client_instance"]
engine = st.session_state["quant_engine_instance"]

def _engine_log_cb(level: str, msg: str):
    import datetime
    if "console_logs" not in st.session_state:
        st.session_state["console_logs"] = []
        
    ts = datetime.datetime.utcnow().strftime("%H:%M:%S")
    entry = {"level": level, "msg": msg, "ts": ts}
    
    # Prepend to the top of the list so newest is first, matching original behavior
    st.session_state["console_logs"].insert(0, entry)
    st.session_state["console_logs"] = st.session_state["console_logs"][:200]
    try:
        import json
        with open("C:/Users/User/Desktop/pmcc1/debug_logs.json", "w", encoding="utf-8") as f:
            json.dump(st.session_state["console_logs"][-30:], f, ensure_ascii=False, indent=2)
    except Exception:
        pass

engine.set_log_callback(_engine_log_cb)
tws.set_log_callback(_engine_log_cb)

# ── Positions & account: pull from TWS every render when connected ─────────────
if st.session_state["connected"] and tws.connected:
    # Refresh account numbers on every render
    tws._refresh_account()
    st.session_state["tws_account_id"] = tws.account_id
    st.session_state["tws_cash"]       = tws.cash_balance
    st.session_state["tws_netliq"]     = tws.net_liquidation

    live_positions = tws.get_positions()
    # Use live data if available; keep demo only if account is genuinely empty
    if live_positions:
        st.session_state["positions"] = live_positions
    # If no positions returned (empty paper account), keep whatever is in session


positions     = st.session_state["positions"]
quant_results = st.session_state.get("quant_results", {})

# ── Sidebar ────────────────────────────────────────────────────────────────────
render_sidebar(tws)

# ── Main Header ───────────────────────────────────────────────────────────────
col_title, col_status = st.columns([6, 1])
with col_title:
    mode_badge = (
        '<span class="badge badge-green" style="font-size:0.75rem;">● LIVE</span>'
        if st.session_state["connected"]
        else '<span class="badge badge-yellow" style="font-size:0.75rem;">● DEMO</span>'
    )
    n_pos = len(positions)
    st.markdown(f"""
    <div style="display:flex;align-items:center;gap:1rem;padding:0.2rem 0 1rem 0;">
      <div>
        <div class="page-title">מערכת ניהול PMCC — NextOffice</div>
        <div style="font-size:0.72rem;color:#64748b;letter-spacing:0.1em;
             text-transform:uppercase;margin-top:3px;">
          PMCC Quant-Dashboard &nbsp; {mode_badge}
          &nbsp; <span style="color:#475569;">{n_pos} positions loaded</span>
        </div>
      </div>
    </div>
    """, unsafe_allow_html=True)

with col_status:
    if st.button("🔄 Refresh", use_container_width=True, key="global_refresh"):
        st.rerun()

# ── Tabs ───────────────────────────────────────────────────────────────────────
tab_portfolio, tab_matrix, tab_payoff, tab_theta, tab_console, tab_orders, tab_reports = \
    st.tabs([
        "📊 Portfolio",
        "🎯 Matrix",
        "📈 Payoff",
        "⏳ Theta",
        "🤖 Console",
        "📤 Orders",
        "📑 Reports",
    ])

with tab_portfolio:
    render_portfolio_tab(positions, quant_results)

with tab_matrix:
    render_matrix_tab()

with tab_payoff:
    render_payoff_tab(positions)

with tab_theta:
    render_theta_tab(positions)

with tab_console:
    render_console_tab(quant_engine=engine, positions=positions)

with tab_orders:
    render_order_tab(positions, tws_client=tws)

with tab_reports:
    render_reports_tab()
