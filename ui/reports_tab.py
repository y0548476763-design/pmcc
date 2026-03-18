"""
ui/reports_tab.py — Excel/PDF export + PnL history charts
"""
import streamlit as st
from datetime import datetime
import pandas as pd
import plotly.graph_objects as go

import db
import report_gen


def render_reports_tab() -> None:
    st.markdown("""
    <div class="pmcc-card shimmer">
      <div class="pmcc-header">📑 Reports & PnL Analytics</div>
      <div style="font-size:0.8rem;color:#64748b;">
        Export trade history, analyse PnL trends and return on cost basis.
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Load data ──────────────────────────────────────────────────────────────
    trades_df = db.get_trades_df()
    pnl_df    = db.get_pnl_history()

    # ── Summary metrics ───────────────────────────────────────────────────────
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        _metric("Total Trades", str(len(trades_df)), "#00d4ff")
    with c2:
        if not trades_df.empty and "fill_price" in trades_df.columns:
            vol = (trades_df["fill_price"] * trades_df["qty"].abs() *100).sum()
            _metric("Volume", f"${vol:,.0f}", "#7c3aed")
        else:
            _metric("Volume", "$0", "#7c3aed")
    with c3:
        if not pnl_df.empty and "net_pnl" in pnl_df.columns:
            pnl = pnl_df["net_pnl"].sum()
            col = "#10b981" if pnl >= 0 else "#ef4444"
            _metric("Total PnL", f"${pnl:,.0f}", col)
        else:
            _metric("Total PnL", "$0", "#10b981")
    with c4:
        if not pnl_df.empty and "cost_basis" in pnl_df.columns:
            cb  = pnl_df["cost_basis"].sum()
            pnl = pnl_df["net_pnl"].sum() if "net_pnl" in pnl_df.columns else 0
            ret = (pnl / cb * 100) if cb else 0
            col = "#10b981" if ret >= 0 else "#ef4444"
            _metric("Return on Cost", f"{ret:.1f}%", col)
        else:
            _metric("Return on Cost", "N/A", "#64748b")

    # ── PnL Chart ─────────────────────────────────────────────────────────────
    if not pnl_df.empty and "net_pnl" in pnl_df.columns:
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown('<div class="pmcc-header">📈 PnL History</div>',
                    unsafe_allow_html=True)

        fig = go.Figure()
        for ticker in pnl_df["ticker"].unique():
            sub = pnl_df[pnl_df["ticker"] == ticker].sort_values("timestamp")
            fig.add_trace(go.Scatter(
                x=sub["timestamp"],
                y=sub["net_pnl"].cumsum(),
                mode="lines+markers",
                name=ticker,
                line=dict(width=2),
            ))

        fig.update_layout(
            paper_bgcolor="#0a0e1a",
            plot_bgcolor="#0d1526",
            font=dict(family="Inter", color="#e2e8f0", size=11),
            legend=dict(bgcolor="rgba(17,24,39,0.8)", bordercolor="#1e293b",
                        borderwidth=1),
            xaxis=dict(gridcolor="#1e293b", tickfont=dict(color="#64748b")),
            yaxis=dict(gridcolor="#1e293b", tickprefix="$",
                       tickfont=dict(color="#64748b")),
            margin=dict(l=60, r=20, t=30, b=50),
            height=300,
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        _empty_pnl_preview()

    # ── Trades table ───────────────────────────────────────────────────────────
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown('<div class="pmcc-header">📋 Trade History</div>',
                unsafe_allow_html=True)

    if trades_df.empty:
        st.markdown('<div style="color:#475569;padding:1rem;">'
                    'No trades recorded yet. Submit orders to populate this log.'
                    '</div>', unsafe_allow_html=True)
    else:
        st.dataframe(
            trades_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "fill_price": st.column_config.NumberColumn("Fill Price", format="$%.2f"),
                "commission": st.column_config.NumberColumn("Commission", format="$%.2f"),
                "strike":     st.column_config.NumberColumn("Strike", format="$%.0f"),
            }
        )

    # ── Export buttons ─────────────────────────────────────────────────────────
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown('<div class="pmcc-header">⬇️ Export</div>',
                unsafe_allow_html=True)

    col_xl, col_pdf, col_csv = st.columns(3)

    with col_xl:
        xlsx_bytes = report_gen.generate_excel(
            trades_df if not trades_df.empty else _demo_df(),
            pnl_df if not pnl_df.empty else None,
        )
        st.download_button(
            "📊 Export Excel",
            data=xlsx_bytes,
            file_name=f"pmcc_report_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

    with col_pdf:
        pdf_bytes = report_gen.generate_pdf(
            trades_df if not trades_df.empty else _demo_df(),
            pnl_df if not pnl_df.empty else None,
        )
        st.download_button(
            "📄 Export PDF",
            data=pdf_bytes,
            file_name=f"pmcc_report_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.pdf",
            mime="application/pdf",
            use_container_width=True,
        )

    with col_csv:
        csv_bytes = trades_df.to_csv(index=False).encode() if not trades_df.empty \
                    else b"No trades"
        st.download_button(
            "📋 Export CSV",
            data=csv_bytes,
            file_name=f"pmcc_trades_{datetime.utcnow().strftime('%Y%m%d')}.csv",
            mime="text/csv",
            use_container_width=True,
        )


def _metric(label: str, value: str, color: str) -> None:
    st.markdown(f"""
    <div class="pmcc-card" style="text-align:center;padding:0.8rem;">
      <div class="pmcc-header">{label}</div>
      <div style="font-size:1.4rem;font-weight:700;color:{color};">{value}</div>
    </div>""", unsafe_allow_html=True)


def _empty_pnl_preview() -> None:
    """Show a placeholder chart with demo data."""
    import numpy as np
    dates = pd.date_range("2025-01-01", periods=60, freq="W")
    pnl   = np.cumsum(np.random.default_rng(42).normal(350, 120, 60))
    fig   = go.Figure(go.Scatter(
        x=dates, y=pnl,
        mode="lines",
        line=dict(color="#00d4ff", width=2),
        fill="tozeroy", fillcolor="rgba(0,212,255,0.07)",
        name="Sample PnL",
    ))
    fig.update_layout(
        paper_bgcolor="#0a0e1a", plot_bgcolor="#0d1526",
        font=dict(family="Inter", color="#e2e8f0"),
        xaxis=dict(gridcolor="#1e293b"),
        yaxis=dict(gridcolor="#1e293b", tickprefix="$"),
        margin=dict(l=60, r=20, t=30, b=40),
        height=270,
        title=dict(text="Sample PnL Preview (no real data yet)",
                   font=dict(color="#475569", size=12)),
    )
    st.plotly_chart(fig, use_container_width=True)


def _demo_df() -> pd.DataFrame:
    return pd.DataFrame([
        {"timestamp": "2025-01-10 09:30:00", "ticker": "NVDA", "action": "SELL_OPEN",
         "option_type": "CALL", "strike": 900, "expiry": "2025-03-21",
         "qty": 1, "fill_price": 8.40, "commission": 0.65},
    ])
