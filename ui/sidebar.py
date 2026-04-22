"""
ui/sidebar.py — Connection panel, account summary, Panic button
"""
import streamlit as st
import config


def render_sidebar(tws_client) -> None:
    with st.sidebar:
        # ── Logo / Title ─────────────────────────────────────────────────────
        st.markdown("""
        <div style="text-align:center; padding: 1rem 0 0.5rem 0;">
          <div style="font-size:1.45rem; font-weight:900;
               background:linear-gradient(135deg,#38bdf8,#818cf8);
               -webkit-background-clip:text; -webkit-text-fill-color:transparent;
               background-clip:text; letter-spacing:-0.01em; line-height:1.2">
            מערכת ניהול PMCC
          </div>
          <div style="font-size:0.78rem; font-weight:700; color:#38bdf8;
               letter-spacing:0.08em; margin-top:2px;">
            NextOffice
          </div>
          <div style="font-size:0.58rem; color:#64748b; letter-spacing:0.18em;
               text-transform:uppercase; margin-top:4px;">
            Quant-Dashboard · PMCC Engine
          </div>
        </div>
        <hr style="border-color:#1a2540; margin:0.5rem 0 1rem 0;">
        """, unsafe_allow_html=True)

        # ── Connection Controls ───────────────────────────────────────────────
        st.markdown('<div class="pmcc-header">🔌 Connection</div>',
                    unsafe_allow_html=True)

        mode = st.radio("Profile", ["DEMO", "LIVE"],
                        index=0 if st.session_state.get("mode", "DEMO") == "DEMO" else 1,
                        horizontal=True, key="mode_radio")
        st.session_state["mode"] = mode

        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("🔗 Connect", width='stretch'):
                with st.spinner("Connecting..."):
                    ok = tws_client.connect(mode)
                    st.session_state["connected"] = ok
                    if ok:
                        # Snapshot account data into session_state immediately
                        st.session_state["tws_account_id"]  = tws_client.account_id
                        st.session_state["tws_cash"]        = tws_client.cash_balance
                        st.session_state["tws_netliq"]      = tws_client.net_liquidation
                        # Force full page reload to pull live positions
                        st.rerun()
                    # If not ok: stays in demo, no rerun needed
        with col_b:
            if st.button("⏏ Disconnect", width='stretch'):
                tws_client.disconnect()
                st.session_state["connected"] = False
                st.session_state.pop("tws_account_id", None)
                st.session_state.pop("tws_cash", None)
                st.session_state.pop("tws_netliq", None)
                st.session_state["positions"] = list(config.DEMO_POSITIONS)
                st.rerun()

        is_socket_connected = getattr(tws_client, "ib", None) is not None and tws_client.ib.isConnected()
        connected = st.session_state.get("connected", False) and is_socket_connected
        status_html = (
            '<span class="badge badge-green">● LIVE</span>'
            if connected else
            '<span class="badge badge-yellow">● DEMO</span>'
        )

        st.markdown(f'<div style="margin-bottom:1rem;">{status_html}</div>', unsafe_allow_html=True)

        # ── Remote Management (GCP Bridge) ───────────────────────────────────
        if config.REMOTE_TWS_HOST:
            st.markdown('<div class="pmcc-header">🌐 Remote IB Gateway</div>', unsafe_allow_html=True)
            
            # Restart/Initialize Button
            if st.button("🔄 Restart & Login", width='stretch', help="אתחול השרת המרוחק כדי להתחיל תהליך התחברות חדש"):
                with st.spinner("Mailing restart request to GCP..."):
                    if tws_client.restart_remote_gateway():
                        st.success("שרת אותחל. המתן לקוד 2FA בטלפון.")
                    else:
                        st.error("כשל באיתחול השרת.")

            # 2FA Entry
            code_2fa = st.text_input("GCP 2FA Code", placeholder="הזן קוד (למשל 123456)", help="הזן את הקוד שקיבלת ב-SMS/Push")
            if st.button("💉 Inject Code", width='stretch', type="primary"):
                if code_2fa:
                    with st.spinner("Injecting code to GCP via Secure Tunnel..."):
                        if tws_client.inject_remote_2fa(code_2fa):
                            st.success("הקוד הופקד בשרת. נסה להתחבר כעת.")
                            # Optionally wait and try to auto-connect
                            st.toast("מזרים פקודת חיבור...")
                        else:
                            st.error("הזרקת קוד נכשלה.")
                else:
                    st.warning("נא להזין קוד לפני ההזרקה.")
            
            st.markdown('<hr style="border-color:#1a2540; margin:1rem 0;">', unsafe_allow_html=True)

        # ── Account Summary ───────────────────────────────────────────────────
        st.markdown('<div class="pmcc-header">💼 Account</div>',
                    unsafe_allow_html=True)

        if connected and st.session_state.get("tws_account_id"):
            acct_id = st.session_state["tws_account_id"]
            cash    = st.session_state.get("tws_cash", 0.0)
            netliq  = st.session_state.get("tws_netliq", 0.0)
        else:
            # Demo placeholder values
            acct_id = "—"
            cash    = 0.0
            netliq  = 0.0

        st.markdown(f"""
        <div class="pmcc-card" style="padding:0.8rem 1rem;">
          <div style="font-size:0.65rem;color:#64748b;letter-spacing:0.1em;
               text-transform:uppercase;">Account</div>
          <div style="font-size:0.9rem;font-weight:600;color:#e2e8f0;">{acct_id}</div>
          <div style="display:flex;justify-content:space-between;margin-top:0.6rem;">
            <div>
              <div style="font-size:0.6rem;color:#64748b;">CASH</div>
              <div style="font-size:1rem;font-weight:700;color:#10b981;">
                ${cash:,.0f}
              </div>
            </div>
            <div style="text-align:right;">
              <div style="font-size:0.6rem;color:#64748b;">NET LIQ</div>
              <div style="font-size:1rem;font-weight:700;color:#00d4ff;">
                ${netliq:,.0f}
              </div>
            </div>
          </div>
        </div>
        """, unsafe_allow_html=True)

        # ── Settings ──────────────────────────────────────────────────────────
        with st.expander("⚙️ Settings", expanded=False):
            st.session_state["delta_target"] = st.slider(
                "Default delta target (Short Calls)", 0.05, 0.50,
                st.session_state.get("delta_target", 0.30), step=0.05
            )
            st.caption("הגדרות אסלמה לגלגול ליפסים — בטאב 🔄 Roll")

        st.markdown('<hr style="border-color:#1e293b;">', unsafe_allow_html=True)

        # ── PANIC BUTTON ─────────────────────────────────────────────────────
        st.markdown('<div class="pmcc-header">🚨 Emergency</div>',
                    unsafe_allow_html=True)
        st.markdown('<div class="panic-btn">', unsafe_allow_html=True)

        if st.button("💀  PANIC — CLOSE ALL", width='stretch',
                     type="primary"):
            st.session_state["show_panic_confirm"] = True

        st.markdown("</div>", unsafe_allow_html=True)

        if st.session_state.get("show_panic_confirm"):
            st.warning("⚠️ This will close ALL option positions at market price!")
            col1, col2 = st.columns(2)
            with col1:
                if st.button("✅ CONFIRM", width='stretch'):
                    n = tws_client.panic_close_all()
                    if n == 0:
                        st.error("BLOCKED — Demo mode (no real orders sent)")
                        _append_console_log("BLOCK",
                            "🚨 PANIC button triggered — BLOCKED in Demo mode. "
                            "Connect to TWS Live to enable.")
                    else:
                        st.success(f"Closed {n} position(s)!")
                        _append_console_log("ACTION",
                            f"🚨 PANIC: Closed {n} position(s) at market.")
                    st.session_state["show_panic_confirm"] = False
            with col2:
                if st.button("❌ Cancel", width='stretch'):
                    st.session_state["show_panic_confirm"] = False

        # ── App version ───────────────────────────────────────────────────────
        st.markdown("""
        <div style="text-align:center;margin-top:1rem;
             font-size:0.6rem;color:#1e293b;letter-spacing:0.05em;">
          PMCC NextOffice v1.0 · 2025
        </div>
        """, unsafe_allow_html=True)


def _append_console_log(level: str, msg: str) -> None:
    """Helper to push to session_state console log from sidebar."""
    import datetime
    logs = st.session_state.get("console_logs", [])
    logs.insert(0, {
        "level": level, "msg": msg,
        "ts": datetime.datetime.utcnow().strftime("%H:%M:%S"),
    })
    st.session_state["console_logs"] = logs[:200]
