"""
ui/console_tab.py — Machine Thinking Console: live streaming log of AI reasoning
"""
import streamlit as st
from typing import List, Dict
from datetime import datetime


_LEVEL_CSS = {
    "INFO":   "log-INFO",
    "WARN":   "log-WARN",
    "BLOCK":  "log-BLOCK",
    "ACTION": "log-ACTION",
}

_LEVEL_ICONS = {
    "INFO":   "ℹ",
    "WARN":   "⚠",
    "BLOCK":  "⛔",
    "ACTION": "▶",
}


def _build_log_html(logs: List[Dict]) -> str:
    if not logs:
        return ('<span style="color:#475569;">'
                'Awaiting analysis... Click "Run Quant Analysis" in the Portfolio tab.'
                '</span>')

    lines = []
    for entry in logs:
        ts    = entry.get("ts", "")
        level = entry.get("level", "INFO")
        msg   = entry.get("msg", "")
        css   = _LEVEL_CSS.get(level, "log-INFO")
        icon  = _LEVEL_ICONS.get(level, "·")
        lines.append(
            f'<span class="log-ts">{ts}</span>'
            f'<span class="{css}">{icon} {msg}</span><br>'
        )
    return "".join(lines)


def render_console_tab(quant_engine=None, positions=None) -> None:
    st.markdown("""
    <div class="pmcc-card shimmer">
      <div class="pmcc-header">🤖 Machine Thinking Console</div>
      <div style="font-size:0.8rem;color:#64748b;">
        Real-time log of the Quant Engine reasoning process.
        Color key:
        <span class="badge badge-cyan">INFO</span> &nbsp;
        <span class="badge badge-yellow">WARN</span> &nbsp;
        <span class="badge badge-red">BLOCK</span> &nbsp;
        <span class="badge badge-green">ACTION</span>
      </div>
    </div>
    """, unsafe_allow_html=True)

    col_a, col_b, col_c, col_d = st.columns([2, 1, 1, 1])
    with col_a:
        run_clicked = st.button("🧠 Run Quant Analysis",
                                use_container_width=True,
                                type="primary",
                                key="console_run_btn")
    with col_b:
        if st.button("🗑️ Clear Log", use_container_width=True, key="console_clear"):
            st.session_state["console_logs"] = []
            st.rerun()
    with col_c:
        if st.button("🔄 Clear Cache", use_container_width=True, key="cache_clear",
                     help="Force fresh data from yfinance (clears 30-min cache)"):
            try:
                from data_feed import clear_data_cache
                clear_data_cache()
                _push_log("ACTION", "🔄 Data cache cleared — next analysis fetches fresh prices from yfinance")
            except Exception as e:
                _push_log("WARN", f"Cache clear failed: {e}")
            st.rerun()
    with col_d:
        auto_scroll = st.toggle("Auto-scroll", value=True, key="console_scroll")

    # ── Run analysis ──────────────────────────────────────────────────────────
    if run_clicked and quant_engine and positions:
        logs_before = len(st.session_state.get("console_logs", []))
        _push_log("INFO", "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        _push_log("INFO", f"🧠 Starting analysis of {len(positions)} positions...")

        import settings_manager
        wl = settings_manager.get_watchlist()
        results = quant_engine.analyse_portfolio(positions, watchlist=wl)
        # Flush engine logs to session state
        new_entries = quant_engine.flush_logs()
        existing   = st.session_state.get("console_logs", [])
        st.session_state["console_logs"] = new_entries + existing
        st.session_state["quant_results"] = results
        st.rerun()

    # ── Render log box ────────────────────────────────────────────────────────
    logs: List[Dict] = st.session_state.get("console_logs", [])
    log_html = _build_log_html(logs)

    scroll_js = ""
    if auto_scroll:
        scroll_js = """
        <script>
          var box = document.getElementById('console-box');
          if(box) box.scrollTop = 0;
        </script>"""

    st.markdown(f"""
    <div class="console-box" id="console-box">
      {log_html}
    </div>
    {scroll_js}
    """, unsafe_allow_html=True)

    # ── Stats bar ─────────────────────────────────────────────────────────────
    if logs:
        n_block  = sum(1 for l in logs if l.get("level") == "BLOCK")
        n_action = sum(1 for l in logs if l.get("level") == "ACTION")
        n_warn   = sum(1 for l in logs if l.get("level") == "WARN")

        st.markdown(f"""
        <div style="display:flex;gap:1rem;margin-top:0.5rem;font-size:0.72rem;">
          <span style="color:#64748b;">Total: {len(logs)}</span>
          <span style="color:#ef4444;">⛔ Blocks: {n_block}</span>
          <span style="color:#f59e0b;">⚠ Warns: {n_warn}</span>
          <span style="color:#10b981;">▶ Actions: {n_action}</span>
        </div>
        """, unsafe_allow_html=True)


def _push_log(level: str, msg: str) -> None:
    logs = st.session_state.get("console_logs", [])
    logs.insert(0, {
        "level": level,
        "msg": msg,
        "ts": datetime.utcnow().strftime("%H:%M:%S"),
    })
    st.session_state["console_logs"] = logs[:200]
