"""
ui/bot_tab.py — Tab 5: Bot Control Center
Manages the 3-state bot, Telegram config, connection settings, Hebrew logs.
"""
import streamlit as st
from datetime import datetime
import config
import settings_manager


def _send_telegram(msg: str, token: str = None, chat_id: str = None) -> bool:
    try:
        import requests
        token   = token   or settings_manager.get_telegram_token()
        chat_id = chat_id or settings_manager.get_telegram_chat_id()
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"},
            timeout=8,
        )
        return r.status_code == 200
    except Exception:
        return False


def render_bot_tab(tws) -> None:

    st.markdown("""
    <div style="padding:0.2rem 0 1rem 0;">
      <div class="pmcc-title">🤖 מרכז שליטה בבוט</div>
      <div style="font-size:0.72rem;color:#64748b;margin-top:3px;">
        הגדרת מצב הבוט · טלגרם · חיבור IBKR · לוגים בעברית
      </div>
    </div>
    """, unsafe_allow_html=True)

    bot_mode = settings_manager.get_bot_mode()

    # ── ROW 1: 3-State Mode Selector ───────────────────────────────────────
    st.markdown('<div class="section-hdr">🎛️ מצב הבוט</div>', unsafe_allow_html=True)

    mode_labels = {
        0: ("🔴", "כבוי",       "הבוט לא פועל — אין בדיקות ואין הודעות.",      "active-off"),
        1: ("🟡", "מעקב בלבד", "הבוט בודק ושולח הודעות — ללא יכולת ביצוע.",   "active-monitor"),
        2: ("🟢", "פעיל מלא",  "הבוט שולח הודעות עם לינק אישור לביצוע פעולות.", "active-execute"),
    }

    cols = st.columns(3)
    for mode_val, (icon, label, desc, css_active) in mode_labels.items():
        is_active = (bot_mode == mode_val)
        with cols[mode_val]:
            border_css = css_active if is_active else ""
            st.markdown(f"""
            <div class="bot-mode-card {border_css if is_active else ''}"
                 style="{'border:2px solid rgba(255,255,255,0.05);' if not is_active else ''}">
              <div style="font-size:2.4rem;">{icon}</div>
              <div style="font-size:1rem;font-weight:800;color:#e2e8f0;margin:6px 0 4px 0;">
                {label}
              </div>
              <div style="font-size:0.7rem;color:#94a3b8;line-height:1.5;">
                {desc}
              </div>
              {'<div style="margin-top:8px;font-size:0.65rem;background:rgba(255,255,255,0.06);'
               'padding:3px 10px;border-radius:20px;color:#f1f5f9;">✓ פעיל כעת</div>' if is_active else ''}
            </div>""", unsafe_allow_html=True)

            if not is_active:
                if st.button(f"הפעל {label}", key=f"set_mode_{mode_val}",
                             use_container_width=True):
                    settings_manager.set_bot_mode(mode_val)
                    _append_log("INFO", f"מצב הבוט שונה ל: {label}")
                    st.rerun()

    mode_badge_txt = {0: "🔴 כבוי", 1: "🟡 מעקב", 2: "🟢 פעיל"}
    st.markdown(f"""
    <div style="margin-top:0.8rem;text-align:center;font-size:0.8rem;color:#64748b;">
      ⚙️ מצב ברירת מחדל בהפעלה: <b>מעקב בלבד</b> — הבוט שולח הודעות ללא ביצוע אוטומטי.
      &nbsp;|&nbsp; מצב נוכחי: <b>{mode_badge_txt.get(bot_mode, '—')}</b>
    </div>""", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── ROW 2: Connection Settings ──────────────────────────────────────────
    st.markdown('<div class="section-hdr">🔌 הגדרות חיבור IBKR</div>', unsafe_allow_html=True)

    profile = settings_manager.get_connection_profile()

    col_conn1, col_conn2, col_conn3, col_conn4 = st.columns(4)

    with col_conn1:
        st.markdown('<div class="pmcc-header">מצב חשבון</div>', unsafe_allow_html=True)
        acct_mode = st.radio("חשבון:", ["DEMO (Paper)", "LIVE (Real $)"],
                             index=0 if profile.get("mode","DEMO") == "DEMO" else 1,
                             key="bot_acct_mode")
        mode_val = "DEMO" if "DEMO" in acct_mode else "LIVE"
        port_val = config.TWS_PORT_DEMO if mode_val == "DEMO" else config.TWS_PORT_LIVE

    with col_conn2:
        st.markdown('<div class="pmcc-header">שרת IBKR</div>', unsafe_allow_html=True)
        host_type = st.radio("Host:",
                             ["מקומי (127.0.0.1)", "שרת מרוחק GCP"],
                             index=0 if profile.get("host","local") == "local" else 1,
                             key="bot_host_type")
        host_val = "127.0.0.1" if "מקומי" in host_type else config.REMOTE_TWS_HOST
        st.markdown(f'<div style="font-size:0.7rem;color:#64748b;">{host_val}:{port_val}</div>',
                    unsafe_allow_html=True)

    with col_conn3:
        st.markdown('<div class="pmcc-header">מרווח סריקה</div>', unsafe_allow_html=True)
        interval = st.number_input("שניות בין סריקות:", 30, 600,
                                   profile.get("interval_sec", 60), step=30,
                                   key="bot_interval")

    with col_conn4:
        st.markdown('<div class="pmcc-header">פעולה</div>', unsafe_allow_html=True)
        st.write("")
        if st.button("💾 שמור הגדרות", use_container_width=True, key="save_conn"):
            settings_manager.set_connection_profile(mode_val, "local" if "מקומי" in host_type else "remote", interval)
            st.success("נשמר!")

        col_cn, col_dc = st.columns(2)
        with col_cn:
            if st.button("🔗 חבר", key="bot_connect", use_container_width=True):
                with st.spinner("מתחבר..."):
                    ok = tws.connect(mode_val, host=host_val)
                    st.session_state["connected"] = ok
                    if ok:
                        st.session_state["tws_account_id"] = tws.account_id
                        st.session_state["tws_cash"]       = tws.cash_balance
                        st.session_state["tws_netliq"]     = tws.net_liquidation
                        _append_log("ACTION", f"🔗 חיבור הצליח — {mode_val} @ {host_val}")
                        st.success("מחובר!")
                        st.rerun()
                    else:
                        _append_log("WARN", f"חיבור נכשל — {mode_val} @ {host_val}:{port_val}")
                        st.error("חיבור נכשל")
        with col_dc:
            if st.button("⏏ נתק", key="bot_disconnect", use_container_width=True):
                tws.disconnect()
                st.session_state["connected"] = False
                _append_log("WARN", "❌ נותק מ-IBKR")
                st.rerun()

    # Connection status
    is_conn = st.session_state.get("connected", False)
    conn_color = "#34d399" if is_conn else "#f87171"
    conn_label = f"LIVE — {st.session_state.get('tws_account_id','—')}" if is_conn else "לא מחובר"
    st.markdown(f"""
    <div style="text-align:center;margin:0.8rem 0;">
      <span class="badge" style="background:rgba(52,211,153,0.1);color:{conn_color};
            border:1px solid {conn_color};font-size:0.8rem;padding:5px 16px;">
        <span class="pulse-dot {'pulse-green' if is_conn else 'pulse-red'}"></span>
        &nbsp; {conn_label}
      </span>
      {f'<span style="color:#64748b;font-size:0.72rem;">&nbsp;&nbsp;Cash: ${float(st.session_state.get("tws_cash",0)):,.0f} | NetLiq: ${float(st.session_state.get("tws_netliq",0)):,.0f}</span>' if is_conn else ''}
    </div>""", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── ROW 3: Telegram Settings ────────────────────────────────────────────
    st.markdown('<div class="section-hdr">📱 הגדרות טלגרם</div>', unsafe_allow_html=True)

    col_tg1, col_tg2, col_tg3 = st.columns([2, 2, 1])
    with col_tg1:
        saved_token = settings_manager.get_telegram_token()
        new_token = st.text_input("Bot Token:", value=saved_token,
                                  key="tg_token_input", type="password")
        if st.button("💾 שמור Token", key="save_tg_token"):
            settings_manager.set_telegram_token(new_token)
            st.success("Token נשמר!")

    with col_tg2:
        saved_cid = settings_manager.get_telegram_chat_id()
        new_cid = st.text_input("Chat ID:", value=saved_cid, key="tg_cid_input")
        if st.button("💾 שמור Chat ID", key="save_tg_cid"):
            settings_manager.set_telegram_chat_id(new_cid)
            st.success("Chat ID נשמר!")

    with col_tg3:
        st.write("")
        st.write("")
        if st.button("📤 שלח הודעת בדיקה", key="tg_test",
                     use_container_width=True, type="primary"):
            ok = _send_telegram(
                "✅ <b>PMCC בדיקת חיבור</b>\n"
                "מערכת PMCC NextOffice מחוברת ופעילה!\n"
                f"🕐 {datetime.now().strftime('%H:%M:%S')}"
            )
            if ok:
                st.success("✅ הודעה נשלחה בהצלחה!")
                _append_log("ACTION", "📱 הודעת בדיקה נשלחה לטלגרם")
            else:
                st.error("❌ שליחה נכשלה — בדוק Token/Chat ID")

    st.markdown("<br>", unsafe_allow_html=True)

    # ── ROW 4: Manual Bot Actions ───────────────────────────────────────────
    st.markdown('<div class="section-hdr">🔧 פעולות בוט ידניות</div>', unsafe_allow_html=True)

    col_a1, col_a2, col_a3, col_a4 = st.columns(4)
    with col_a1:
        if st.button("🔄 סריקת תיק מלאה", use_container_width=True, key="bot_scan_full"):
            _append_log("INFO", "🔄 סריקת תיק ידנית הופעלה...")
            st.info("סריקה מלאה מתבצעת — ראה לוגים למטה")

    with col_a2:
        if st.button("📊 עדכן פרטי חשבון", use_container_width=True, key="bot_refresh_acct"):
            if is_conn:
                tws._refresh_account()
                st.session_state["tws_cash"]   = tws.cash_balance
                st.session_state["tws_netliq"] = tws.net_liquidation
                _append_log("INFO", f"💼 חשבון עודכן — Cash: ${tws.cash_balance:,.0f}")
                st.success("עודכן!")
                st.rerun()
            else:
                st.warning("לא מחובר לIBKR")

    with col_a3:
        if st.button("🚨 PANIC — סגור הכל", use_container_width=True,
                     type="primary", key="panic_bot_tab"):
            st.session_state["show_panic_bot"] = True

    with col_a4:
        if st.button("🗑️ נקה לוגים", use_container_width=True, key="clear_logs_bot"):
            st.session_state["console_logs"] = []
            st.success("לוגים נוקו")
            st.rerun()

    if st.session_state.get("show_panic_bot"):
        st.error("⚠️ אתה עומד לסגור את כל הפוזיציות במחיר שוק!")
        col_y, col_n = st.columns(2)
        with col_y:
            if st.button("✅ אשר סגירה", key="panic_confirm_bot"):
                n = tws.panic_close_all() if is_conn else 0
                if n == 0:
                    _append_log("BLOCK", "🚨 PANIC — BLOCKED (DEMO / לא מחובר)")
                else:
                    _append_log("ACTION", f"🚨 PANIC: נסגרו {n} פוזיציות!")
                    _send_telegram(f"🚨 <b>PANIC CLOSE</b>\nנסגרו {n} פוזיציות במחיר שוק!")
                st.session_state["show_panic_bot"] = False
                st.rerun()
        with col_n:
            if st.button("❌ ביטול", key="panic_cancel_bot"):
                st.session_state["show_panic_bot"] = False
                st.rerun()

    st.markdown("<br>", unsafe_allow_html=True)

    # ── ROW 5: Log Console ─────────────────────────────────────────────────
    st.markdown('<div class="section-hdr">📋 לוגים — היסטוריית פעולות הבוט</div>',
                unsafe_allow_html=True)

    logs = st.session_state.get("console_logs", [])

    if not logs:
        st.markdown("""
        <div class="console-box" style="text-align:center;color:#1e3a5f;padding:2rem;">
          — אין לוגים עדיין —<br>
          <span style="font-size:0.7rem;">הלוגים יופיעו כאן כאשר הבוט יבצע פעולות</span>
        </div>""", unsafe_allow_html=True)
    else:
        level_color = {
            "INFO":   "var(--accent)",
            "WARN":   "var(--yellow)",
            "BLOCK":  "var(--red)",
            "ACTION": "var(--green)",
        }

        html_lines = []
        for entry in logs[:100]:
            lvl   = entry.get("level", "INFO")
            ts    = entry.get("ts", "")
            msg   = entry.get("msg", "")
            color = level_color.get(lvl, "var(--text-md)")
            html_lines.append(
                f'<div><span class="log-ts">{ts}</span>'
                f'<span style="color:{color};font-weight:600;">[{lvl}]</span>'
                f'&nbsp;<span style="color:var(--text-md);">{msg}</span></div>'
            )

        st.markdown(
            f'<div class="console-box">{"".join(html_lines)}</div>',
            unsafe_allow_html=True,
        )

    # ── ROW 6: Bot Status Summary ──────────────────────────────────────────
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown('<div class="section-hdr">📊 סיכום מצב המערכת</div>', unsafe_allow_html=True)

    mode_desc = {
        0: ("🔴", "כבוי — הבוט לא מבצע בדיקות"),
        1: ("🟡", "מעקב — שולח התראות בלבד, ללא ביצוע"),
        2: ("🟢", "פעיל — שולח הודעות עם אפשרות אישור לביצוע"),
    }
    icon_m, desc_m = mode_desc.get(bot_mode, ("—", "—"))

    st.markdown(f"""
    <div class="pmcc-card" style="direction:rtl;">
      <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:1rem;">
        <div style="text-align:center;">
          <div class="kpi-label">מצב בוט</div>
          <div style="font-size:1.4rem;font-weight:800;">{icon_m} {desc_m.split('—')[0]}</div>
          <div style="font-size:0.7rem;color:#64748b;">{desc_m.split('—')[1] if '—' in desc_m else ''}</div>
        </div>
        <div style="text-align:center;">
          <div class="kpi-label">חיבור IBKR</div>
          <div style="font-size:1.4rem;font-weight:800;color:{'#34d399' if is_conn else '#f87171'};">
            {'✅ מחובר' if is_conn else '❌ לא מחובר'}
          </div>
          <div style="font-size:0.7rem;color:#64748b;">
            {mode_val} @ {host_val}:{port_val}
          </div>
        </div>
        <div style="text-align:center;">
          <div class="kpi-label">לוגים</div>
          <div style="font-size:1.4rem;font-weight:800;">{len(logs)}</div>
          <div style="font-size:0.7rem;color:#64748b;">רשומות</div>
        </div>
      </div>
    </div>""", unsafe_allow_html=True)


def _append_log(level: str, msg: str) -> None:
    """Helper: push to session_state console log."""
    logs = st.session_state.get("console_logs", [])
    logs.insert(0, {
        "level": level,
        "msg":   msg,
        "ts":    datetime.utcnow().strftime("%H:%M:%S"),
    })
    st.session_state["console_logs"] = logs[:200]
