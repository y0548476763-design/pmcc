"""
ui/cash_tab.py — Tab 4: Cash & Fleet Management
Manages the Cash Tank, LEAPS expansion rules, survival protocols, and VIX triggers.
All rules are configurable within this tab.
"""
import streamlit as st
from datetime import datetime
from typing import List, Dict
import config
import settings_manager


def _get_dte(expiry_str: str) -> int:
    try:
        exp = datetime.strptime(str(expiry_str).replace("-", ""), "%Y%m%d")
        return max(0, (exp.date() - datetime.utcnow().date()).days)
    except Exception:
        return 999


def _fetch_vix() -> float:
    """Fetch current VIX index from Yahoo Finance."""
    try:
        import yfinance as yf
        t = yf.Ticker("^VIX")
        return float(t.fast_info.last_price or t.fast_info.previous_close or 0)
    except Exception:
        return 0.0


def _send_telegram(msg: str) -> bool:
    try:
        import requests
        token   = settings_manager.get_telegram_token()
        chat_id = settings_manager.get_telegram_chat_id()
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"}, timeout=8)
        return r.status_code == 200
    except Exception:
        return False


def render_cash_tab(positions: list, quant_results: dict, tws) -> None:

    st.markdown("""
    <div style="padding:0.2rem 0 1rem 0;">
      <div class="pmcc-title">💰 ניהול מזומן ושרידות הצי</div>
      <div style="font-size:0.72rem;color:#64748b;margin-top:3px;">
        מכל המזומן · כללי כניסה · VIX טריגרים · חיסול חירום
      </div>
    </div>
    """, unsafe_allow_html=True)

    bot_mode = settings_manager.get_bot_mode()

    # ── Data ────────────────────────────────────────────────────────────────
    try:
        # Support both DEMO positions (type='LEAPS') and LIVE-converted positions
        leaps  = [p for p in positions if p.get("type") == "LEAPS"
                  or (p.get("secType") == "OPT" and p.get("right") == "C"
                      and p.get("position", 0) > 0)]
        ib_cash = float(st.session_state.get("tws_cash", 0.0))
        ext_cash = settings_manager.get_external_cash()
        total_cash = ib_cash + ext_cash

        # Cost basis total
        total_leaps_cost = sum(
            abs(float(p.get("cost_basis") or 0)) * abs(p.get("qty", p.get("position", 1)))
            for p in leaps
        )
        if total_leaps_cost == 0:
            total_leaps_cost = sum(
                float(p.get("current_price") or 50) * abs(p.get("qty", p.get("position", 1))) * 100
                for p in leaps
            ) or 1

        # Tank lines
        blue_line   = total_leaps_cost * config.TANK_TARGET_PCT
        yellow_line = total_leaps_cost * config.TANK_WARNING_PCT
        red_line    = total_leaps_cost * config.TANK_FLOOR_PCT
    except Exception as e:
        import traceback
        st.error(f"⚠️ שגיאה בחישוב נתוני מזומן: {e}")
        leaps = []
        total_cash = 0
        total_leaps_cost = 1
        blue_line = yellow_line = red_line = 0

    if total_cash >= blue_line:
        tank_status, tank_color, tank_msg = "SURPLUS 🚀", "#3b82f6", "מעל יעד 30% — ניתן לרכוש ליפסים חדשים"
    elif total_cash >= yellow_line:
        tank_status, tank_color, tank_msg = "GREEN 🛡️", "#34d399", "מוגן — מאחסן לגלגולים עתידיים"
    elif total_cash >= red_line:
        tank_status, tank_color, tank_msg = "YELLOW ⚠️", "#fbbf24", "אזהרה — צבר פרמיות לטנק"
    else:
        tank_status, tank_color, tank_msg = "RED 🚨", "#f87171", "סכנה! מתחת לרצפה — שקול חיסול ליפס"

    pct_raw = (total_cash / blue_line * 100) if blue_line > 0 else 0
    pct_bar = min(pct_raw, 100)

    # ── ROW 1: KPIs ─────────────────────────────────────────────────────────
    c1, c2, c3, c4 = st.columns(4)
    def _kpi(col, label, val, color, sub=""):
        with col:
            st.markdown(f"""
            <div class="kpi-card">
              <div class="kpi-label">{label}</div>
              <div class="kpi-val" style="color:{color};">{val}</div>
              <div class="kpi-sub">{sub}</div>
            </div>""", unsafe_allow_html=True)

    _kpi(c1, "מזומן כולל",        f"${total_cash:,.0f}", "#38bdf8", f"IB ${ib_cash:,.0f} + חיצוני ${ext_cash:,.0f}")
    _kpi(c2, "עלות רכישת LEAPS",  f"${total_leaps_cost:,.0f}", "#818cf8", "Cost Basis סך הצי")
    _kpi(c3, "קו כחול (30%)",     f"${blue_line:,.0f}",  "#38bdf8", "יעד הטנק")
    _kpi(c4, "סטטוס הטנק",        tank_status,          tank_color, tank_msg)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── ROW 2: Tank Gauge ───────────────────────────────────────────────────
    st.markdown('<div class="section-hdr">🛢️ מד הטנק — Cash Tank</div>', unsafe_allow_html=True)

    st.markdown(f"""
    <div class="pmcc-card">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.5rem;">
        <div style="font-size:1.2rem;font-weight:800;color:{tank_color};">${total_cash:,.0f}</div>
        <div style="font-size:0.78rem;color:#64748b;">{pct_raw:.1f}% מהיעד</div>
      </div>
      <div class="tank-bar">
        <div class="tank-bar-fill" style="width:{pct_bar:.1f}%;background:{tank_color};"></div>
      </div>
      <div style="display:flex;justify-content:space-between;font-size:0.62rem;
           color:#64748b;margin-top:6px;">
        <span>$0</span>
        <span style="color:#f87171;">🔴 ${red_line:,.0f} (15%)</span>
        <span style="color:#fbbf24;">🟡 ${yellow_line:,.0f} (20%)</span>
        <span style="color:#3b82f6;">🔵 ${blue_line:,.0f} (30%)</span>
      </div>
      <div style="margin-top:1rem;font-size:0.75rem;color:#94a3b8;
           background:rgba(255,255,255,0.03);border-radius:8px;padding:0.6rem;
           direction:rtl;text-align:right;">
        {tank_msg}
      </div>
    </div>""", unsafe_allow_html=True)

    if total_cash < red_line:
        if bot_mode >= 1:
            if st.button("📱 שלח התראת טנק לטלגרם", key="alert_tank_tg"):
                _send_telegram(
                    f"🚨 <b>אזהרת טנק PMCC!</b>\n"
                    f"מזומן: ${total_cash:,.0f}\n"
                    f"מתחת לרצפה 15%: ${red_line:,.0f}\n"
                    f"⚠️ שקול חיסול ליפס כדי להבטיח גלגולים!"
                )
                st.success("הודעה נשלחה!")

    st.markdown("<br>", unsafe_allow_html=True)

    # ── ROW 3: VIX Monitor ──────────────────────────────────────────────────
    st.markdown('<div class="section-hdr">⚡ מד VIX — טריגר פאניקה</div>', unsafe_allow_html=True)

    vix_threshold = settings_manager.get_rule("vix_threshold", config.VIX_AGGRESSIVE_ENTRY)

    with st.spinner("טוען VIX..."):
        vix_val = _fetch_vix()

    vix_triggered = vix_val >= vix_threshold and vix_val > 0
    vix_color = "#f87171" if vix_triggered else ("#fbbf24" if vix_val > 25 else "#34d399")

    st.markdown(f"""
    <div class="pmcc-card" style="text-align:center;">
      <div class="kpi-label">VIX — מדד הפחד</div>
      <div style="font-size:3rem;font-weight:900;color:{vix_color};
           {'animation:pulse-ring 1s infinite;' if vix_triggered else ''}">
        {vix_val:.1f}
      </div>
      {'<div class="webhook-badge">🚨 VIX TRIGGER ACTIVE — שקול פריסת מזומן מלאה!</div>'
       if vix_triggered else
       f'<div style="font-size:0.75rem;color:#64748b;">טריגר בסף: >{vix_threshold:.0f}</div>'}
    </div>""", unsafe_allow_html=True)

    if vix_triggered and bot_mode >= 1:
        if st.button("📱 שלח התראת VIX לטלגרם", key="vix_tg_alert"):
            free_cash = max(0, total_cash - red_line)
            _send_telegram(
                f"⚡ <b>VIX TRIGGER PMCC!</b>\n"
                f"VIX = {vix_val:.1f} (סף: {vix_threshold:.0f})\n"
                f"💰 מזומן פנוי לפריסה: ${free_cash:,.0f}\n"
                f"🚀 שקול רכישת ליפסים בכל המזומן הפנוי!"
            )
            st.success("הודעת VIX נשלחה!")

    st.markdown("<br>", unsafe_allow_html=True)

    # ── ROW 4: Settings Expander ────────────────────────────────────────────
    with st.expander("⚙️ הגדרות ניהול טנק וכללים (לחץ לפתיחה)", expanded=False):
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown('**💵 מזומן לחשבון 외부**')
            new_ext = st.number_input("הכנס סכום ($):", min_value=0.0,
                                      value=ext_cash, step=500.0, key="ext_cash_input")
            if new_ext != ext_cash:
                settings_manager.set_external_cash(new_ext)
                st.rerun()

        with c2:
            st.markdown('**⚡ סף התראת VIX**')
            new_vix_thr = st.number_input("VIX Trigger", 15, 80,
                                          int(vix_threshold), key="vix_thr_input")
            if new_vix_thr != vix_threshold:
                settings_manager.set_rule("vix_threshold", new_vix_thr)
                st.rerun()

        with c3:
            st.markdown("**📉 כללי ירידות — Tranches**")
            t1 = st.number_input("Tranche A (% ירידה)", 5, 30,
                                  int(abs(settings_manager.get_rule("dip_trigger_a_pct", 20))),
                                  key="t1_input")
            t2 = st.number_input("Tranche B (% ירידה)", 10, 50,
                                  int(abs(settings_manager.get_rule("dip_trigger_b_pct", 30))),
                                  key="t2_input")
            if st.button("💾 שמור טראנשים", key="save_t1_t2"):
                settings_manager.set_rule("dip_trigger_a_pct", t1)
                settings_manager.set_rule("dip_trigger_b_pct", t2)
                st.success("נשמר")

        st.markdown("<hr style='margin:1rem 0;opacity:0.2;'>", unsafe_allow_html=True)
        st.markdown("**כלל SMA-150 (מומנטום)**")
        wl = settings_manager.get_watchlist()
        new_wl_str = st.text_input("מניות לניטור SMA-150 (מופרדות בפסיק):",
                                   value=", ".join(wl), key="wl_input")
        if st.button("💾 שמור רשימה", key="save_wl"):
            new_wl = [t.strip().upper() for t in new_wl_str.split(",") if t.strip()]
            settings_manager.set_watchlist(new_wl)
            st.success(f"נשמרו {len(new_wl)} מניות")

    # ── ROW 5: SMA-150 Signal Status ──────────────────────────────────────
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown('<div class="section-hdr">🎯 מצב טריגרי רכישה</div>', unsafe_allow_html=True)

    watchlist = settings_manager.get_watchlist()
    if not quant_results and watchlist:
        st.info("הרץ Quant Analysis (בחלונית הפרוטפוליו) כדי לראות מצב הטריגרים.")
    else:
        cols = st.columns(min(len(quant_results) + 1, 5))
        col_idx = 0

        # VIX card
        with cols[col_idx % len(cols)]:
            vix_color2 = "#f87171" if vix_triggered else "#34d399"
            st.markdown(f"""
            <div class="pmcc-card" style="text-align:center;padding:0.8rem;">
              <div class="kpi-label">VIX</div>
              <div style="font-size:1.4rem;font-weight:900;color:{vix_color2};">{vix_val:.1f}</div>
              <div style="font-size:0.65rem;color:{vix_color2};">
                {'⚡ TRIGGERED' if vix_triggered else 'Normal'}
              </div>
            </div>""", unsafe_allow_html=True)
        col_idx += 1

        for ticker, qr in quant_results.items():
            if not hasattr(qr, "drawdown_pct"):
                continue
            dd        = qr.drawdown_pct
            cross150  = getattr(qr, "cross_above_150", False)
            above150  = getattr(qr, "above_ma150", False)

            if cross150:
                color, label = "#34d399", "✅ SMA-150!"
            elif dd <= config.DIP_TRIGGER_B:
                color, label = "#f87171", "TRANCHE B 🚨"
            elif dd <= config.DIP_TRIGGER_A:
                color, label = "#fbbf24", "TRANCHE A ⚠️"
            elif dd <= -0.10:
                color, label = "#38bdf8", "Watch -10%"
            else:
                color, label = "#64748b", "Waiting"

            free_cash = max(0, total_cash - red_line)
            tranche_amount = free_cash * settings_manager.get_rule("tranche_pct", 30) / 100.0

            with cols[col_idx % len(cols)]:
                st.markdown(f"""
                <div class="pmcc-card" style="text-align:center;padding:0.8rem;">
                  <div style="font-size:1rem;font-weight:800;color:#e2e8f0;">{ticker}</div>
                  <div style="font-size:1.2rem;font-weight:900;color:{color};">{dd:.1%}</div>
                  <div style="font-size:0.65rem;color:{color};font-weight:700;">{label}</div>
                  {f'<div style="font-size:0.65rem;color:#64748b;margin-top:4px;">ניתן לפרוס: ${tranche_amount:,.0f}</div>'
                   if label not in ["Waiting"] else ''}
                </div>""", unsafe_allow_html=True)

                if label not in ["Waiting", "Normal"] and bot_mode >= 1:
                    if st.button(f"📱 {ticker}", key=f"trig_tg_{ticker}",
                                 use_container_width=True):
                        _send_telegram(
                            f"🎯 <b>טריגר רכישה — {ticker}</b>\n"
                            f"ירידה: {dd:.1%} | {label}\n"
                            f"מזומן לפריסה: ${tranche_amount:,.0f}\n"
                            f"📊 שקול רכישת ליפס {ticker} Delta 0.80 / 540+ DTE"
                        )
                        st.success("הודעה נשלחה!")
            col_idx += 1

    st.markdown("<br>", unsafe_allow_html=True)

    # ── ROW 6: LEAPS DTE Alerts ───────────────────────────────────────────
    st.markdown('<div class="section-hdr">⏳ ליפסים הדורשים גלגול</div>',
                unsafe_allow_html=True)

    roll_threshold = int(settings_manager.get_rule("leaps_roll_dte", config.LEAPS_ROLL_DTE))
    alert_threshold = roll_threshold + 30

    leaps_to_roll = []
    for lp in leaps:
        dte = _get_dte(lp.get("expiry", ""))
        if dte <= alert_threshold:
            leaps_to_roll.append((lp, dte))

    if not leaps_to_roll:
        st.markdown("""
        <div class="alert-box alert-low" style="text-align:center;">
          ✅ כל הליפסים מרוחקים מספיק מגלגול — אין פעולה נדרשת
        </div>""", unsafe_allow_html=True)
    else:
        for lp, dte in leaps_to_roll:
            ticker = lp.get("ticker", "")
            strike = float(lp.get("strike", 0))
            expiry = lp.get("expiry", "")
            urgent = dte <= roll_threshold
            color  = "#f87171" if urgent else "#fbbf24"

            col_l, col_b = st.columns([4, 1])
            with col_l:
                st.markdown(f"""
                <div class="alert-box {'alert-high' if urgent else 'alert-medium'}"
                     style="direction:rtl;">
                  {'🚨' if urgent else '⚠️'} <b>{ticker}</b> — Strike ${strike:.0f}C | פקיעה: {expiry}
                  | <span style="color:{color};font-weight:700;">DTE: {dte}</span>
                  {'— גלגול מיידי נדרש!' if urgent else '— קרוב לגלגול'}
                </div>""", unsafe_allow_html=True)
            with col_b:
                if st.button(f"📱 התרע", key=f"roll_alert_{ticker}_{strike}",
                             use_container_width=True) and bot_mode >= 1:
                    _send_telegram(
                        f"{'🚨' if urgent else '⚠️'} <b>גלגול ליפס נדרש!</b>\n"
                        f"📋 {ticker} ${strike:.0f}C | פקיעה: {expiry}\n"
                        f"⏳ DTE: {dte} ({'חובה לגלגל!' if urgent else 'עדיין יש זמן'})"
                    )
                    st.success("הודעה נשלחה!")

    st.markdown("<br>", unsafe_allow_html=True)

    # ── ROW 7: Emergency Fleet Reduction ──────────────────────────────────
    st.markdown('<div class="section-hdr">🆘 חיסול חירום — Fleet Reduction</div>',
                unsafe_allow_html=True)

    st.markdown("""
    <div class="alert-box alert-high" style="direction:rtl;">
    ⚠️ <b>כלל חיסול חירום:</b> רק כאשר הטנק מתחת לקו האדום (15%) ואין ברירה.
    המנוע מחסל ליפסים קטנים/חלשים כדי לממן גלגול של שאר הצי ל-180+ DTE ב-Δ0.80.
    </div>
    """, unsafe_allow_html=True)

    if total_cash < red_line:
        st.warning(f"⚠️ מזומן נמוך (${total_cash:,.0f}) — מתחת לקו האדום (${red_line:,.0f})")
        if leaps:
            smallest = sorted(leaps,
                              key=lambda p: float(p.get("current_price", 0)))[0]
            tk = smallest.get("ticker", "")
            st.markdown(f"""
            <div class="alert-box alert-medium">
              💡 ליפס קטן ביותר לחיסול: <b>{tk}</b>
              Strike ${float(smallest.get('strike',0)):.0f}C | פקיעה {smallest.get('expiry','')}
              | ערך נוכחי: ~${float(smallest.get('current_price',0))*100:.0f}
            </div>""", unsafe_allow_html=True)

            col_f1, col_f2 = st.columns(2)
            with col_f1:
                if st.button(f"🆘 חסל {tk} ידנית", key="fleet_reduce_manual",
                             use_container_width=True) and tws:
                    import order_manager
                    om = order_manager.get_manager()
                    om.set_tws(tws)
                    om.submit_order(
                        ticker=tk, right="C",
                        strike=float(smallest.get("strike", 0)),
                        expiry=str(smallest.get("expiry", "")),
                        action="SELL", qty=abs(smallest.get("qty", 1)),
                        limit_price=float(smallest.get("current_price", 0)) * 0.98,
                        escalation_step_pct=2.0,
                        escalation_wait_mins=1,
                        order_type="MKT"
                    )
                    st.success(f"פקודת חיסול נשלחה עבור {tk}!")
            with col_f2:
                if st.button("📱 שלח להחלטה בטלגרם", key="fleet_tg",
                             use_container_width=True) and bot_mode >= 1:
                    _send_telegram(
                        f"🆘 <b>חיסול חירום נדרש!</b>\n"
                        f"הטנק: ${total_cash:,.0f} (מתחת ל-${red_line:,.0f})\n"
                        f"מועמד לחיסול: {tk} ${float(smallest.get('strike',0)):.0f}C\n"
                        f"האם לבצע? ענה YES לאישור"
                    )
                    st.info("הודעה נשלחה לטלגרם")
    else:
        st.markdown("""
        <div class="alert-box alert-low">
          ✅ הטנק מעל קו האדום — חיסול חירום אינו נדרש כעת
        </div>""", unsafe_allow_html=True)
