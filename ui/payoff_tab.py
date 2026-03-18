"""
ui/payoff_tab.py — Risk/Payoff graph at expiration using Plotly
"""
import streamlit as st
import numpy as np
import plotly.graph_objects as go
from typing import List, Dict


def render_payoff_tab(positions: List[Dict]) -> None:
    st.markdown("""
    <div class="pmcc-card shimmer">
      <div class="pmcc-header">📈 Risk / Payoff Graph</div>
      <div style="font-size:0.8rem;color:#64748b;">
        Visualise full PMCC payoff at expiration for each position pair.
      </div>
    </div>
    """, unsafe_allow_html=True)

    if not positions:
        st.info("No positions to display.")
        return

    # ── Ticker selector ───────────────────────────────────────────────────────
    tickers = list({p["ticker"] for p in positions})
    ticker  = st.selectbox("Select ticker", tickers, key="payoff_ticker")

    leaps = next((p for p in positions
                   if p["ticker"] == ticker and p["type"] == "LEAPS"), None)
    short = next((p for p in positions
                   if p["ticker"] == ticker and p["type"] == "SHORT_CALL"), None)

    if not leaps or not short:
        st.warning("Need both a LEAPS and a Short Call for this ticker to draw payoff.")
        return

    und_price = leaps.get("underlying_price", 200.0)

    # Slider for underlying price range
    price_min = und_price * 0.5
    price_max = und_price * 1.6
    assumed   = st.slider(
        "Assumed stock price at expiration",
        float(price_min), float(price_max),
        float(und_price),
        step=1.0,
        key="payoff_slider"
    )

    # ── Payoff calculation ────────────────────────────────────────────────────
    stock_range = np.linspace(price_min, price_max, 400)

    leaps_strike  = leaps["strike"]
    short_strike  = short["strike"]
    leaps_cost    = leaps["cost_basis"]
    short_premium = short.get("premium_received", 0)
    qty           = abs(leaps.get("qty", 1))

    # LEAPS payoff (long call)
    leaps_pnl = (np.maximum(stock_range - leaps_strike, 0) - leaps_cost) * qty * 100

    # Short call payoff
    short_pnl = (short_premium - np.maximum(stock_range - short_strike, 0)) * qty * 100

    # Combined PMCC payoff
    combined  = leaps_pnl + short_pnl

    # ── Breakeven & key levels ────────────────────────────────────────────────
    max_profit  = float(np.max(combined))
    max_loss    = float(np.min(combined))
    # Estimate breakeven: where combined crosses 0 going up
    sign_change = np.where(np.diff(np.sign(combined)))[0]
    breakevens  = [stock_range[i] for i in sign_change]

    # ── Plotly graph ──────────────────────────────────────────────────────────
    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=stock_range, y=combined,
        mode="lines",
        name="PMCC Combined",
        line=dict(color="#00d4ff", width=2.5),
        fill="tozeroy",
        fillcolor="rgba(0,212,255,0.08)",
    ))
    fig.add_trace(go.Scatter(
        x=stock_range, y=leaps_pnl,
        mode="lines",
        name="LEAPS Only",
        line=dict(color="#7c3aed", width=1.2, dash="dot"),
    ))
    fig.add_trace(go.Scatter(
        x=stock_range, y=short_pnl,
        mode="lines",
        name="Short Call",
        line=dict(color="#10b981", width=1.2, dash="dash"),
    ))

    # Zero line
    fig.add_hline(y=0, line_color="#475569", line_width=1)

    # Mark current price
    fig.add_vline(x=und_price, line_color="#64748b", line_dash="dash",
                  annotation_text=f"Current ${und_price:.0f}",
                  annotation_font_color="#64748b")

    # Mark assumed price
    assumed_y = float(np.interp(assumed, stock_range, combined))
    fig.add_vline(x=assumed, line_color="#f59e0b", line_width=2,
                  annotation_text=f"Assumed ${assumed:.0f}",
                  annotation_font_color="#f59e0b")
    fig.add_trace(go.Scatter(
        x=[assumed], y=[assumed_y],
        mode="markers",
        marker=dict(color="#f59e0b", size=10, symbol="diamond"),
        name=f"P/L @ ${assumed:.0f}",
        showlegend=True,
    ))

    # Breakeven lines
    for be in breakevens[:2]:
        fig.add_vline(x=be, line_color="#10b981", line_dash="dot",
                      annotation_text=f"B/E ${be:.0f}",
                      annotation_font_color="#10b981")

    fig.update_layout(
        paper_bgcolor="#0a0e1a",
        plot_bgcolor="#0d1526",
        font=dict(family="Inter", color="#e2e8f0", size=11),
        title=dict(
            text=f"<b>{ticker}</b> PMCC Payoff at Expiration",
            font=dict(color="#00d4ff", size=16),
        ),
        legend=dict(
            bgcolor="rgba(17,24,39,0.8)",
            bordercolor="#1e293b",
            borderwidth=1,
            font=dict(size=10),
        ),
        xaxis=dict(
            title="Stock Price at Expiration ($)",
            gridcolor="#1e293b",
            zerolinecolor="#1e293b",
            tickprefix="$",
        ),
        yaxis=dict(
            title="Profit / Loss ($)",
            gridcolor="#1e293b",
            zerolinecolor="#ef4444",
            tickprefix="$",
        ),
        margin=dict(l=60, r=30, t=60, b=50),
        height=420,
    )

    st.plotly_chart(fig, use_container_width=True)

    # ── Key stats ─────────────────────────────────────────────────────────────
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        _stat("Max Profit", f"${max_profit:,.0f}", "#10b981")
    with col2:
        _stat("Max Loss", f"${max_loss:,.0f}", "#ef4444")
    with col3:
        if breakevens:
            _stat("Breakeven", f"${breakevens[0]:,.0f}", "#10b981")
        else:
            _stat("Breakeven", "N/A", "#64748b")
    with col4:
        color = "#10b981" if assumed_y >= 0 else "#ef4444"
        _stat(f"P/L @ ${assumed:.0f}", f"${assumed_y:,.0f}", color)


def _stat(label: str, value: str, color: str) -> None:
    st.markdown(f"""
    <div class="pmcc-card" style="text-align:center;padding:0.7rem;">
      <div class="pmcc-header">{label}</div>
      <div style="font-size:1.2rem;font-weight:700;color:{color};">{value}</div>
    </div>""", unsafe_allow_html=True)
