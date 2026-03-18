"""
ui/theta_tab.py — Theta Hourglass: visualises time decay for each short call
"""
import streamlit as st
from typing import List, Dict
from datetime import datetime, date
import plotly.graph_objects as go
import numpy as np


def _days_to_expiry(expiry_str: str) -> int:
    try:
        exp = datetime.strptime(expiry_str.replace("-", ""), "%Y%m%d").date()
        return max(0, (exp - date.today()).days)
    except Exception:
        # Try alternate format
        try:
            exp = datetime.strptime(expiry_str, "%Y-%m-%d").date()
            return max(0, (exp - date.today()).days)
        except Exception:
            return 30


def _hourglass_gauge(label: str, dte: int, theta: float,
                     original_dte: int = 45) -> go.Figure:
    pct_elapsed = 1.0 - (dte / max(original_dte, 1))
    pct_elapsed = min(1.0, max(0.0, pct_elapsed))
    pct_remaining = 1.0 - pct_elapsed

    # Color transitions: green → yellow → red as DTE drops
    if dte > 21:
        bar_color = "#10b981"
    elif dte > 10:
        bar_color = "#f59e0b"
    else:
        bar_color = "#ef4444"

    fig = go.Figure(go.Indicator(
        mode="gauge+number+delta",
        value=dte,
        delta={"reference": original_dte, "relative": False,
               "decreasing": {"color": "#ef4444"},
               "increasing": {"color": "#10b981"}},
        title={"text": f"<b>{label}</b><br><span style='font-size:0.7rem;color:#64748b'>"
                        f"θ {theta:.4f}/day</span>",
               "font": {"size": 13, "color": "#e2e8f0"}},
        gauge={
            "axis": {"range": [0, original_dte],
                     "tickcolor": "#1e293b",
                     "tickfont": {"color": "#64748b", "size": 9}},
            "bar": {"color": bar_color, "thickness": 0.25},
            "bgcolor": "#0d1526",
            "borderwidth": 1,
            "bordercolor": "#1e293b",
            "steps": [
                {"range": [0, original_dte * 0.22], "color": "rgba(239,68,68,0.15)"},
                {"range": [original_dte * 0.22, original_dte * 0.50],
                 "color": "rgba(245,158,11,0.1)"},
                {"range": [original_dte * 0.50, original_dte],
                 "color": "rgba(16,185,129,0.08)"},
            ],
            "threshold": {
                "line": {"color": "#ef4444", "width": 2},
                "thickness": 0.75,
                "value": 7,
            },
        },
        number={"suffix": " DTE", "font": {"size": 20, "color": "#e2e8f0"},
                "valueformat": ".0f"},
    ))

    fig.update_layout(
        paper_bgcolor="#111827",
        height=220,
        margin=dict(l=20, r=20, t=40, b=10),
        font={"family": "Inter"},
    )
    return fig


def render_theta_tab(positions: List[Dict]) -> None:
    st.markdown("""
    <div class="pmcc-card shimmer">
      <div class="pmcc-header">⏳ Theta Hourglass</div>
      <div style="font-size:0.8rem;color:#64748b;">
        Visualise time decay and DTE for each short call position.
        Red zone = &lt; 7 DTE (consider rolling).
      </div>
    </div>
    """, unsafe_allow_html=True)

    short_calls = [p for p in positions if p["type"] == "SHORT_CALL"]

    if not short_calls:
        st.info("No short call positions found.")
        return

    # ── Gauges grid ───────────────────────────────────────────────────────────
    n_cols = min(3, len(short_calls))
    cols = st.columns(n_cols)

    for i, pos in enumerate(short_calls):
        ticker   = pos["ticker"]
        expiry   = pos.get("expiry", "")
        theta    = pos.get("theta", -0.04)
        dte      = _days_to_expiry(expiry)
        orig_dte = st.session_state.get(f"orig_dte_{ticker}", 45)

        label = f"{ticker} ${pos['strike']:.0f}C"
        fig   = _hourglass_gauge(label, dte, theta, orig_dte)

        with cols[i % n_cols]:
            st.plotly_chart(fig, use_container_width=True, key=f"theta_{i}")

            # Theta decay progress
            theta_daily = abs(theta) * 100  # in $ per day (×100 for 1 contract)
            total_decay = theta_daily * (orig_dte - dte)
            remaining_decay = theta_daily * dte
            st.markdown(f"""
            <div style="font-size:0.72rem;color:#64748b;text-align:center;">
              ${theta_daily:.2f}/day &nbsp;|&nbsp;
              Earned: <span style="color:#10b981;">${total_decay:.0f}</span> &nbsp;|&nbsp;
              Remaining: <span style="color:#00d4ff;">${remaining_decay:.0f}</span>
            </div>
            """, unsafe_allow_html=True)

    # ── Cumulative theta earned table ─────────────────────────────────────────
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown('<div class="pmcc-header">📊 Theta Earned Summary</div>',
                unsafe_allow_html=True)

    rows = ""
    total_theta_earned = 0
    for pos in short_calls:
        dte          = _days_to_expiry(pos.get("expiry", ""))
        orig_dte     = st.session_state.get(f"orig_dte_{pos['ticker']}", 45)
        premium      = pos.get("premium_received", 0) * 100
        pct_earned   = (1 - dte / max(orig_dte, 1)) * 100
        theta_earned = premium * (pct_earned / 100)
        total_theta_earned += theta_earned
        color = "#10b981" if pct_earned > 50 else "#f59e0b"
        rows += f"""
        <tr>
          <td><strong>{pos['ticker']}</strong></td>
          <td>${pos['strike']:.0f}C</td>
          <td>{dte} days</td>
          <td>${premium:.0f}</td>
          <td style="color:{color};">{pct_earned:.1f}%</td>
          <td style="color:#10b981;">${theta_earned:.0f}</td>
        </tr>"""

    st.markdown(f"""
    <div class="pmcc-card" style="overflow-x:auto;">
      <table class="pmcc-table">
        <thead><tr>
          <th>Ticker</th><th>Strike</th><th>DTE</th>
          <th>Premium</th><th>% Theta Earned</th><th>$ Earned</th>
        </tr></thead>
        <tbody>{rows}</tbody>
        <tfoot>
          <tr style="border-top:1px solid #1e293b;">
            <td colspan="5" style="text-align:right;color:#64748b;
                font-size:0.75rem;">Total theta earned:</td>
            <td style="color:#10b981;font-weight:700;">
              ${total_theta_earned:,.0f}
            </td>
          </tr>
        </tfoot>
      </table>
    </div>""", unsafe_allow_html=True)
