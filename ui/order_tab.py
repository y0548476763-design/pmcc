"""
ui/order_tab.py — Order Entry, Golden Rule validation, escalation tracker
Supports both SHORT CALL (SELL) and LEAPS (BUY) order types.
"""
import streamlit as st
from typing import List, Dict, Optional
from datetime import datetime, date

import config
from risk_guard import get_guard
from order_manager import get_manager


def render_order_tab(positions: List[Dict], tws_client=None) -> None:
    # Detect if coming from LEAPS matrix selection
    is_leaps_mode = st.session_state.get("order_is_leaps", False)

    leaps_badge = (
        '<span class="badge badge-cyan">📅 LEAPS BUY</span>'
        if is_leaps_mode
        else '<span class="badge badge-green">📞 Short Call SELL</span>'
    )
    st.markdown(f"""
    <div class="pmcc-card shimmer">
      <div class="pmcc-header">📤 Order Entry &nbsp; {leaps_badge}</div>
      <div style="font-size:0.8rem;color:#64748b;">
        {'קנייה ארוכה — LEAPS. Golden Rule לא חל על פתיחת פוזיציה.' if is_leaps_mode
         else 'מכירת Short Call. מוחל Golden Rule לפני שליחה.'}
      </div>
    </div>
    """, unsafe_allow_html=True)

    col_form, col_valid = st.columns([3, 2])

    with col_form:
        # ── Order fields (pre-populated from Matrix Picker if selected) ────────
        tickers = list({p["ticker"] for p in positions}) if positions else ["NVDA"]
        default_ticker = st.session_state.get("order_ticker", tickers[0])
        if default_ticker not in tickers:
            tickers.insert(0, default_ticker)

        ticker   = st.selectbox("Ticker", tickers, key="oform_ticker",
                                 index=tickers.index(default_ticker))
        action   = st.radio("Action", ["SELL", "BUY"], horizontal=True,
                             key="oform_action")
        right    = st.radio("Right", ["C", "P"], horizontal=True, key="oform_right")

        col_s, col_e = st.columns(2)
        with col_s:
            strike = st.number_input(
                "Strike ($)", min_value=0.5, step=0.5,
                value=float(st.session_state.get("order_strike", 100.0)),
                key="oform_strike",
            )
        with col_e:
            default_exp = st.session_state.get("order_expiry", "2025-03-21")
            expiry = st.text_input("Expiry (YYYY-MM-DD)", value=default_exp,
                                    key="oform_expiry")

        order_type_label = st.radio("Order Type", ["Limit (Adaptive Algo)", "Market"], horizontal=True, key="oform_type")
        is_mkt = (order_type_label == "Market")

        col_q, col_m, col_a3 = st.columns(3)
        with col_q:
            qty = st.number_input("Qty", min_value=1, value=1, key="oform_qty")
        with col_m:
            default_mid = max(0.01, float(st.session_state.get("order_mid", 5.00)))
            limit_price = st.number_input(
                "Initial Limit ($)", min_value=0.01, step=0.01,
                value=default_mid,
                key="oform_mid",
                disabled=is_mkt
            )
        with col_a3:
            escalation_step = st.number_input(
                "Escalation Step (%)", min_value=0.1, max_value=20.0, step=0.1,
                value=float(st.session_state.get("oform_esc_step", 1.0)),
                key="oform_esc_step",
                disabled=is_mkt
            )
        algo_speed = st.select_slider(
            "Algo Speed", options=config.ALGO_SPEEDS,
            value="Normal", key="oform_algo",
            disabled=is_mkt
        )

        # ── LEAPS context for validation ──────────────────────────────────────
        leaps = next(
            (p for p in positions
             if p["ticker"] == ticker and p["type"] == "LEAPS"),
            None,
        )

    with col_valid:
        # ── Golden Rule — only applies to SHORT CALL (SELL) orders ────────────
        st.markdown('<div class="pmcc-header">🛡️ Golden Rule Check</div>',
                    unsafe_allow_html=True)

        if is_leaps_mode:
            # BUY LEAPS — no Golden Rule restriction
            blocked = False
            st.markdown("""
            <div style="background:rgba(16,185,129,0.1);border:1px solid #10b981;
                 border-radius:10px;padding:0.8rem;font-size:0.8rem;">
              ✅ <strong>LEAPS BUY — Golden Rule לא חל</strong><br>
              <span style="color:#94a3b8;">
                קנייה של LEAPS היא פתיחת פוזיציה — אין הגבלה על Strike או Expiry.
              </span>
            </div>""", unsafe_allow_html=True)
        else:
            leaps = next(
                (p for p in positions
                 if p["ticker"] == ticker and p["type"] == "LEAPS"),
                None,
            )
            if leaps:
                leaps_strike  = leaps["strike"]
                leaps_cost    = leaps["cost_basis"]
                leaps_delta   = leaps.get("delta", 0.80)
                sc_delta      = abs(st.session_state.get("order_delta", 0.30))
                prem_received = leaps.get("premium_received", 0.0)

                results = get_guard().validate_short_call(
                    short_call_strike=strike,
                    leaps_strike=leaps_strike,
                    leaps_cost_basis=leaps_cost,
                    premium_received=prem_received,
                    leaps_delta=leaps_delta,
                    short_delta=sc_delta,
                )
                blocked = get_guard().is_blocked(results)

                for r in results:
                    st.markdown(f"""
                    <div style="margin:0.4rem 0;padding:0.5rem;
                         background:rgba(17,24,39,0.7);border-radius:8px;
                         font-size:0.75rem;border-left:3px solid
                         {'#ef4444' if not r.is_valid else '#10b981'};">
                      {'⛔' if not r.is_valid else '✅'}
                      <strong>{r.rule_name}</strong><br>
                      <span style="color:#94a3b8;">{r.reason}</span>
                    </div>""", unsafe_allow_html=True)
            else:
                blocked = False
                st.markdown("""
                <div style="color:#64748b;font-size:0.8rem;padding:1rem;">
                  No LEAPS found for this ticker.<br>Validation skipped.
                </div>""", unsafe_allow_html=True)

        # ── Order summary ──────────────────────────────────────────────────────
        summary_price = "MARKET PRICE" if is_mkt else f"${limit_price:.2f}"
        summary_esc = "N/A" if is_mkt else f"+{escalation_step:.1f}%"
        summary_algo = "Instant" if is_mkt else algo_speed

        st.markdown(f"""
        <div style="margin-top:1rem;font-size:0.9rem;">
          <div style="padding:0.8rem;background:rgba(30,41,59,0.5);border-radius:8px;">
            <strong>ORDER SUMMARY</strong><br>
            {action} {qty}x <strong>{ticker}</strong>
            ${strike:.0f}{right} <span style="color:#64748b;">{expiry}</span><br>
            Limit: <span style="color:#10b981;">{summary_price}</span> &nbsp;
            Escalation: <span style="color:#ef4444;">{summary_esc}</span> &nbsp;
            [{summary_algo}]<br>
            Est. Credit: <span style="color:#10b981;">
              ${limit_price * qty * 100:,.0f}
            </span>
          </div>
        </div>""", unsafe_allow_html=True)

    # ── Submit button ──────────────────────────────────────────────────────────
    st.markdown("<br>", unsafe_allow_html=True)

    if blocked:
        st.markdown("""
        <div style="background:rgba(239,68,68,0.15);border:1px solid #ef4444;
             border-radius:10px;padding:0.8rem;text-align:center;color:#ef4444;
             font-weight:700;font-size:0.9rem;">
          ⛔ ORDER BLOCKED — Golden Rule Violation.<br>
          <span style="font-size:0.75rem;font-weight:400;">
            Adjust strike to comply before submitting.
          </span>
        </div>""", unsafe_allow_html=True)
    else:
        if st.button("📤 Submit Order", use_container_width=True, type="primary",
                      key="oform_submit"):
            mgr = get_manager()
            mgr.set_tws(tws_client)
            iid = mgr.submit_order(
                ticker=ticker,
                right=right,
                strike=strike,
                expiry=expiry,
                action=action,
                qty=qty,
                limit_price=limit_price,
                escalation_step_pct=st.session_state["oform_esc_step"],
                escalation_wait_mins=st.session_state.get("escalation_mins", config.ESCALATION_WAIT_MINUTES),
                algo_speed=algo_speed,
                order_type="MKT" if is_mkt else "LMT",
            )
            mo = mgr.get_order(iid)
            if mo and mo.status == "REJECTED":
                st.error(f"❌ Order {iid} was explicitly REJECTED by TWS. Check parameters (e.g. invalid Strike/Expiry) or TWS connection.")
                _push_log("WARN", f"Order {iid} rejected instantly by backend/TWS.")
            else:
                is_live = getattr(tws_client, "ib", None) is not None and tws_client.ib.isConnected()
                prefix = "✅ " if is_live else "🟡 [SIMULATED DEMO] "
                if is_mkt:
                    st.success(f"{prefix}Market Order {iid} submitted instantly.")
                else:
                    st.success(f"{prefix}Order {iid} submitted @ Limit ${limit_price:.2f}. "
                               f"Escalation by {escalation_step:.1f}% in {config.ESCALATION_WAIT_MINUTES} min if unfilled.")
                
                _push_log("ACTION", f"Order {iid} submitted: {action} {qty}x "
                                    f"{ticker} ${strike}{right} {expiry} @ "
                                    f"{summary_price} [{summary_algo}]")

    # ── Live orders tracker ────────────────────────────────────────────────────
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown('<div class="pmcc-header">📋 Active Orders</div>',
                unsafe_allow_html=True)

    mgr = get_manager()
    orders = mgr.get_all_orders()

    if not orders:
        st.markdown('<div style="color:#475569;font-size:0.8rem;">'
                    'No active orders.</div>', unsafe_allow_html=True)
        return

    rows = ""
    # DEBUG DIAGNOSTICS
    if tws_client and tws_client.ib and tws_client.ib.isConnected():
        st.write("### Diagnostics")
        for t in tws_client.ib.trades():
            if t.orderStatus.status not in ("Filled", "Cancelled", "Inactive"):
                st.write(f"**{t.order.orderId}**: {t.order.lmtPrice}")
                st.write([log for log in t.log if "Error" in str(log) or "Reject" in str(log)])
    # /DEBUG DIAGNOSTICS
    for o in reversed(orders):
        status_css = {
            "PENDING":   "badge-yellow",
            "ESCALATED": "badge-cyan",
            "FILLED":    "badge-green",
            "CANCELLED": "badge-red",
        }.get(o.status, "badge-cyan")

        # Escalation progress bar HTML (Looping)
        last_action_time = o.escalated_at if o.escalated_at else o.submitted_at
        elapsed_s = (datetime.utcnow() - last_action_time).total_seconds()
        target_s  = config.ESCALATION_WAIT_MINUTES * 60
        pct       = min(100, int(max(0.0, elapsed_s) / target_s * 100))
        prog_color = "#f59e0b" if pct < 100 else "#10b981"
        step_pct   = o.__dict__.get('_escalation_step_pct', 1.0)
        escl_cnt   = o.escalation_count

        rows += f"""
        <tr>
          <td style="color:#00d4ff;font-weight:600;">{o.__dict__.get('_internal_id', '')}</td>
          <td>{o.ticker}</td>
          <td>${o.strike:.0f}{o.right}</td>
          <td style="color:#64748b;">{o.expiry}</td>
          <td>{o.action} {o.qty}</td>
          <td>${o.current_price:.2f}</td>
          <td><span class="badge {status_css}">{o.status}</span></td>
          <td>
            <div style="display:flex;align-items:center;gap:0.5rem;">
                <div style="background:#1e293b;border-radius:4px;height:6px;width:60px;">
                <div style="background:{prog_color};width:{pct}%;height:6px;
                    border-radius:4px;transition:width 1s;"></div>
                </div>
                <span style="font-size:0.65rem;color:#64748b;min-width:30px;">{pct}%</span>
                <span class="badge badge-yellow" style="font-size:0.6rem;">{escl_cnt}x (+{step_pct}%)</span>
            </div>
          </td>
        </tr>"""

    st.markdown(f"""
    <div class="pmcc-card" style="overflow-x:auto;padding:0.5rem;">
      <table class="pmcc-table">
        <thead><tr>
          <th>ID</th><th>Ticker</th><th>Strike</th><th>Expiry</th>
          <th>Side</th><th>Price</th><th>Status</th><th>Escalation</th>
        </tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </div>""", unsafe_allow_html=True)


def _push_log(level: str, msg: str) -> None:
    logs = st.session_state.get("console_logs", [])
    logs.insert(0, {
        "level": level, "msg": msg,
        "ts": datetime.utcnow().strftime("%H:%M:%S"),
    })
    st.session_state["console_logs"] = logs[:200]
