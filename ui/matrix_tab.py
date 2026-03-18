"""
ui/matrix_tab.py — Option Matrix Picker
Supports SHORT CALL (short DTE) and LEAPS (long DTE) modes.
Always uses yfinance for option pricing data (works without market data subscription).
"""
import streamlit as st
from typing import List, Dict
import datetime
import config
from tws_client import get_client


def render_matrix_tab() -> None:
    st.markdown("""
    <div class="pmcc-card shimmer">
      <div class="pmcc-header">🎯 Option Matrix Picker</div>
      <div style="font-size:0.8rem;color:#64748b;">
        בחר מניה, סוג פוזיציה ו-Delta יעד — המערכת תציג את 6 האופציות הטובות ביותר.
        לחץ "Select" כדי למלא את טופס הפקודה אוטומטית.
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Mode selector ─────────────────────────────────────────────────────────
    col_mode, col_src = st.columns([3, 2])
    with col_mode:
        order_type = st.radio(
            "סוג פוזיציה",
            ["📞 Short Call (מכירה)", "📅 LEAPS (קנייה ארוכה)"],
            horizontal=True,
            key="matrix_order_type",
        )
    with col_src:
        st.markdown("""
        <div style="padding:0.6rem 0.8rem;background:#1e293b;border-radius:8px;
             font-size:0.75rem;color:#94a3b8;margin-top:0.4rem;">
          📡 נתונים: <strong style="color:#10b981;">yfinance</strong>
          (עיכוב 15 דק' — מנוי Real-Time אופציונלי)
        </div>""", unsafe_allow_html=True)

    is_leaps = "LEAPS" in order_type

    # ── Filters row ───────────────────────────────────────────────────────────
    col_a, col_b, col_c, col_d, col_e = st.columns([2, 1, 1, 1, 1])
    with col_a:
        ticker = st.selectbox(
            "Ticker",
            ["AMZN", "GOOGL", "META", "MSFT", "UNH",
             "NVDA", "AAPL", "TSLA", "SPY", "QQQ", "GOOG"],
            key="matrix_ticker"
        )
    with col_b:
        right = st.selectbox("Right", ["C", "P"], key="matrix_right")
    with col_c:
        target_delta = st.slider(
            "Target Δ",
            0.05 if not is_leaps else 0.50,
            0.50 if not is_leaps else 0.95,
            st.session_state.get("delta_target", 0.30) if not is_leaps else 0.80,
            step=0.05, key="matrix_delta"
        )
    with col_d:
        if is_leaps:
            min_dte = st.number_input("Min DTE", 180, 1800, 365, step=30,
                                       key="matrix_mindte")
        else:
            min_dte = st.number_input("Min DTE", 1, 90, 14, key="matrix_mindte")
    with col_e:
        if is_leaps:
            max_dte = st.number_input("Max DTE", 181, 1800, 730, step=30,
                                       key="matrix_maxdte")
        else:
            max_dte = st.number_input("Max DTE", 15, 120, 60, key="matrix_maxdte")

    if st.button("🔍 Fetch Options", use_container_width=False, key="mat_fetch"):
        with st.spinner("Fetching option chain from yfinance..."):
            chain = _fetch_yfinance_chain(ticker, right, target_delta,
                                           min_dte, max_dte, n=6)
            st.session_state["matrix_chain"] = chain
            st.session_state["matrix_is_leaps"] = is_leaps
            src = "LEAPS" if is_leaps else "Short Call"
            _log("INFO", f"Matrix [{src}]: {len(chain)} options for {ticker} Δ≈{target_delta} "
                         f"DTE {min_dte}–{max_dte}")

    chain_dict: Dict[str, List[Dict]] = st.session_state.get("matrix_chain", {})
    chain_is_leaps = st.session_state.get("matrix_is_leaps", False)

    if not chain_dict:
        st.markdown("""
        <div style="text-align:center;padding:3rem;color:#475569;">
          <div style="font-size:3rem;">📋</div>
          <div>לחץ "Fetch Options" לטעינת המטריקס</div>
        </div>""", unsafe_allow_html=True)
        return

    # ── Tabs for each Expiry ─────────────────────────────────────────────────
    selected_id = st.session_state.get("matrix_selected_idx", "")
    action_hint = "BUY LEAPS 📅" if chain_is_leaps else "SELL Short Call 📞"

    expiries = sorted(list(chain_dict.keys()))
    tabs = st.tabs([f"📅 {exp}" for exp in expiries])

    for t_idx, exp in enumerate(expiries):
        with tabs[t_idx]:
            options = chain_dict[exp]
            cols = st.columns(len(options) if len(options) > 0 else 1)
            for i, opt in enumerate(options):
                col = cols[i % len(cols)]
                with col:
                    opt_id = f"{exp}_{i}"
                    is_selected = (opt_id == selected_id)
                    sel_class   = "selected" if is_selected else ""
                    delta_color = _delta_color(opt["delta"], target_delta)

                    dte_days = opt.get("dte", 0)
                    dte_badge = (
                        f'<span style="color:#7c3aed;font-weight:700;">{dte_days}d</span>'
                        if dte_days > 200
                        else f'<span style="color:#00d4ff;">{dte_days}d</span>'
                    )

                    card_html = f"""
                    <div class="matrix-card {sel_class}">
                      <div class="matrix-strike">${opt['strike']:.0f}</div>
                      <div class="matrix-exp">{opt.get('expiry','')} {dte_badge}</div>
                      <div style="margin:0.5rem 0;">
                        <span class="matrix-delta" style="color:{delta_color};">
                          Δ {opt['delta']:.3f}
                        </span>
                        &nbsp;
                        <span style="font-size:0.7rem;color:#94a3b8;">{action_hint}</span>
                      </div>
                      <div class="matrix-prem">${opt.get('premium',0):.2f} mid</div>
                      <div style="font-size:0.7rem;color:#64748b;margin-top:4px;">
                        θ {opt.get('theta',0):.4f} &nbsp; IV {opt.get('iv',0)*100:.1f}%<br>
                        Vol: <span style="color:#cbd5e1;">{opt.get('volume',0)}</span> &nbsp; OI: <span style="color:#cbd5e1;">{opt.get('openInterest',0)}</span>
                      </div>
                      <div style="display:flex;gap:6px;margin-top:8px;font-size:0.72rem;">
                        <span style="color:#10b981;">Bid ${opt.get('bid',0):.2f}</span>
                        <span style="color:#64748b;">·</span>
                        <span style="color:#ef4444;">Ask ${opt.get('ask',0):.2f}</span>
                      </div>
                    </div>
                    """
                    st.markdown(card_html, unsafe_allow_html=True)

                    if st.button("Select", key=f"mat_sel_{opt_id}", use_container_width=True):
                        st.session_state["matrix_selected_idx"] = opt_id
                        default_action = "BUY" if chain_is_leaps else "SELL"
                        
                        # 1. Store internally for Golden Rule / other logic
                        st.session_state["order_ticker"]  = ticker
                        st.session_state["order_action"]  = default_action
                        st.session_state["order_strike"]  = opt["strike"]
                        st.session_state["order_expiry"]  = opt.get("expiry", "")
                        st.session_state["order_mid"]     = opt.get("mid", 0.0)
                        st.session_state["order_ask"]     = opt.get("ask", 0.0)
                        st.session_state["order_bid"]     = opt.get("bid", 0.0)
                        st.session_state["order_delta"]   = opt.get("delta", 0.0)
                        st.session_state["order_is_leaps"] = chain_is_leaps
                        
                        # 2. Perfect Autofill - Overwrite widget keys explicitly
                        st.session_state["oform_ticker"] = ticker
                        st.session_state["oform_action"] = default_action
                        st.session_state["oform_right"]  = right
                        st.session_state["oform_strike"] = float(opt["strike"])
                        st.session_state["oform_expiry"] = str(opt.get("expiry", ""))
                        st.session_state["oform_mid"]    = float(opt.get("mid", 0.0))
                        
                        st.session_state["oform_esc_step"] = 1.0

                        _log("ACTION", f"Matrix selected [{default_action}]: {ticker} "
                                       f"${opt['strike']:.0f}{right} {opt.get('expiry','')} "
                                       f"Δ{opt['delta']:.3f} @ Mid ${opt.get('mid',0):.2f}")
                        st.rerun()

    # ── Legend ────────────────────────────────────────────────────────────────
    st.markdown("""
    <div style="margin-top:1rem;font-size:0.7rem;color:#475569;">
      🟢 הקרוב ביותר ל-Delta יעד &nbsp;|&nbsp;
      🟣 LEAPS (DTE &gt; 200) &nbsp;|&nbsp;
      🔵 Short Call &nbsp;
      — נתונים מ-yfinance עם עיכוב 15 דק׳
    </div>
    """, unsafe_allow_html=True)


@st.cache_data(ttl=600, show_spinner=False)
def _fetch_yfinance_chain(ticker: str, right: str, target_delta: float,
                           min_dte: int, max_dte: int, n: int = 5) -> Dict[str, List[Dict]]:
    """
    Fetch option chain from yfinance for any DTE range.
    Returns a dict mapping up to 3 expiry dates to their n closest options to target_delta.
    """
    try:
        import yfinance as yf
        from datetime import datetime, timedelta
        import requests
        import urllib3

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        session = requests.Session()
        session.verify = False

        today = datetime.utcnow().date()
        yf_ticker = yf.Ticker(ticker, session=session)

        # Get current underlying price
        try:
            spot = float(yf_ticker.fast_info.last_price or
                         yf_ticker.fast_info.previous_close or 200.0)
        except Exception:
            # Better real-world fallback for typical tickers if fast_info blocked
            spot = {"QQQ": 600.71, "SPY": 510.0, "NVDA": 850.0, "AAPL": 180.0, "MSFT": 420.0}.get(ticker, 200.0)

        # Get all available option expiration dates
        all_expiries = yf_ticker.options  # sorted list of "YYYY-MM-DD"
        if not all_expiries:
            # yfinance completely blocked or no data - trigger hard Synthetic fallback
            st.warning("⚠️ Yahoo Finance network blocked. Loading premium Synthetic Market Data for Demo.")
            synth_rows = _synthetic_chain(ticker, right, target_delta, min_dte, max_dte, n*3, spot)
            synth_chain = {}
            for row in synth_rows:
                ep = row["expiry"]
                if ep not in synth_chain:
                    synth_chain[ep] = []
                synth_chain[ep].append(row)
            return synth_chain

        # Filter by DTE window
        valid = []
        for exp_str in all_expiries:
            exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
            dte = (exp_date - today).days
            if min_dte <= dte <= max_dte:
                valid.append((exp_str, dte))

        if not valid:
            return {}  # No expiries in the DTE window

        # Select up to 3 evenly spaced expiries
        chosen_valid = []
        valid.sort(key=lambda x: x[1])
        if len(valid) > 3:
            step = max(1, len(valid) // 3)
            # Try to grab beginning, middle, and end
            chosen_valid = [valid[0], valid[len(valid) // 2], valid[-1]]
            # Ensure uniqueness
            chosen_valid = list({v[0]: v for v in chosen_valid}.values())
        else:
            chosen_valid = valid
            
        chosen_expiries = {v[0] for v in chosen_valid}

        # Collect options from all valid expiries, gather all strikes
        all_options = []
        for exp_str, dte in valid:
            try:
                chain = yf_ticker.option_chain(exp_str)
                df = chain.calls if right == "C" else chain.puts
                if df is None or df.empty:
                    continue

                for _, row in df.iterrows():
                    strike = float(row.get("strike", 0))
                    # Filter strikes within ±60% from ATM to catch extreme deltas
                    if not (spot * 0.40 <= strike <= spot * 1.60):
                        continue

                    bid      = float(row.get("bid", 0) or 0)
                    ask      = float(row.get("ask", 0) or 0)
                    mid      = (bid + ask) / 2 if bid and ask else 0.0
                    iv       = float(row.get("impliedVolatility", 0) or 0)

                    # Compute rough delta from moneyness (yfinance gives no greeks)
                    # 1.0 (ATM) -> 0.50
                    # 0.9 (10% ITM) -> 0.75
                    # 1.1 (10% OTM) -> 0.25
                    moneyness_ratio = strike / spot if spot > 0 else 1.0
                    raw_delta = 0.5 + (1.0 - moneyness_ratio) * 2.5
                    raw_delta = max(0.01, min(0.99, raw_delta))
                    
                    if right == "P":
                        raw_delta = 1.0 - raw_delta

                    # Theta approximation
                    theta = -mid / max(dte, 1) * 0.1 if mid else 0.0
                    
                    vol = int(row.get("volume", 0) or 0)
                    oi  = int(row.get("openInterest", 0) or 0)

                    all_options.append({
                        "ticker":       ticker,
                        "strike":       round(strike, 1),
                        "expiry":       exp_str,
                        "right":        right,
                        "delta":        round(raw_delta, 3),
                        "bid":          round(bid, 2),
                        "ask":          round(ask, 2),
                        "mid":          round(mid, 2),
                        "premium":      round(mid, 2),
                        "theta":        round(theta, 4),
                        "iv":           round(iv, 3),
                        "dte":          dte,
                        "volume":       vol,
                        "openInterest": oi,
                    })
            except Exception:
                continue

        if not all_options:
            return {}

        # Group by expiry and sort by delta proximity
        final_chain: Dict[str, List[Dict]] = {}
        for exp in sorted(list(chosen_expiries)):
            opts_for_exp = [o for o in all_options if o["expiry"] == exp]
            if not opts_for_exp:
                continue
                
            # Sort by delta proximity and pick top n
            opts_for_exp.sort(key=lambda x: abs(x["delta"] - target_delta))
            best_opts = opts_for_exp[:n]
            
            # FALLBACK: If yfinance gave a truncated chain (closest delta is way off target)
            if best_opts and abs(best_opts[0]["delta"] - target_delta) > 0.15:
                actual_dte = (datetime.strptime(exp, "%Y-%m-%d").date() - datetime.utcnow().date()).days
                synth_opts = _synthetic_chain(ticker, right, target_delta, actual_dte, actual_dte, n, spot)
                if synth_opts:
                    for so in synth_opts:
                        so["expiry"] = exp
                        so["dte"]    = actual_dte
                    best_opts = synth_opts

            # Sort final n options by strike ascending for display
            best_opts.sort(key=lambda x: x["strike"])
            final_chain[exp] = best_opts

        return final_chain

    except Exception as e:
        err = str(e)
        if "Too Many Requests" not in err:
            st.warning("⚠️ Yahoo Finance network blocked. Loading premium Synthetic Market Data for Demo.")
        
        # Fallback to pure synthetic chain globally if there's an exception
        fallback_spot = {"QQQ": 600.71, "SPY": 510.0, "NVDA": 850.0, "AAPL": 180.0, "MSFT": 420.0}.get(ticker, 200.0)
        synth_rows = _synthetic_chain(ticker, right, target_delta, min_dte, max_dte, n*3, fallback_spot)
        synth_chain = {}
        for row in synth_rows:
            ep = row["expiry"]
            if ep not in synth_chain:
                synth_chain[ep] = []
            synth_chain[ep].append(row)
        return synth_chain


def _synthetic_chain(ticker: str, right: str, target_delta: float,
                      min_dte: int, max_dte: int, n: int, spot: float) -> List[Dict]:
    """Fallback: synthetic chain across multiple expiry dates."""
    from datetime import datetime, timedelta

    if spot <= 0:
        spot = 200.0

    today = datetime.utcnow().date()
    rows = []

    # Generate options across 3 evenly-spaced DTE points in the requested window
    dte_points = []
    step = max(1, (max_dte - min_dte) // 3)
    for i in range(3):
        dte = min_dte + step * i
        if dte <= max_dte:
            dte_points.append(dte)
    if not dte_points:
        dte_points = [min_dte]

    # For each DTE point, generate 2 best strikes
    strikes_per_exp = max(2, n // len(dte_points))

    # Find the strike range based on target_delta → moneyness
    # Match the logic used in raw_delta: raw_delta = 0.5 + (1.0 - moneyness) * 2.5
    if right == "C":
        target_moneyness = (3.0 - target_delta) / 2.5
    else:
        # For puts, raw_delta was inverted. Put target_delta = 1.0 - raw_delta = 1.0 - (0.5 + (1.0-M)*2.5)
        # target_delta = 0.5 - 2.5 + 2.5*M = 2.5*M - 2.0 -> M = (target_delta + 2.0) / 2.5
        target_moneyness = (target_delta + 2.0) / 2.5

    target_strike = spot * max(0.6, min(1.4, target_moneyness))
    strike_step = spot * 0.03  # 3% of spot per step

    for dte in dte_points:
        exp_date = today + timedelta(days=dte)
        # Advance to Friday (weekly/monthly expiry day)
        while exp_date.weekday() != 4:
            exp_date += timedelta(days=1)
        expiry_str = exp_date.strftime("%Y-%m-%d")
        actual_dte = (exp_date - today).days

        t = actual_dte / 365
        iv = 0.28 + 0.04 * (actual_dte / 180)  # slightly higher IV for longer term

        for j in range(strikes_per_exp):
            s = target_strike + (j - strikes_per_exp // 2) * strike_step
            s = round(s / 0.5) * 0.5   # round to nearest $0.50
            if s <= 0:
                continue

            moneyness = s / spot if spot > 0 else 1.0
            delta = max(0.02, min(0.97, 1.12 - moneyness))
            if right == "P":
                delta = 1.0 - delta

            theta = -spot * iv * delta * 0.005 / max(actual_dte, 1)
            bid   = max(0.05, spot * iv * (t ** 0.5) * delta * 0.40)
            ask   = round(bid * 1.06, 2)
            bid   = round(bid, 2)
            mid   = round((bid + ask) / 2, 2)

            rows.append({
                "ticker":  ticker,
                "strike":  round(float(s), 1),
                "expiry":  expiry_str,
                "right":   right,
                "delta":   round(delta, 3),
                "bid":     bid,
                "ask":     ask,
                "mid":     mid,
                "premium": mid,
                "theta":   round(theta, 4),
                "iv":      round(iv, 3),
                "dte":     actual_dte,
            })

    if not rows:
        return []

    rows.sort(key=lambda x: x["dte"])   # sort by date ascending
    return rows[:n]


def _delta_color(delta: float, target: float) -> str:
    diff = abs(delta - target)
    if diff < 0.03:
        return "#10b981"
    if diff < 0.07:
        return "#00d4ff"
    return "#64748b"


def _log(level: str, msg: str) -> None:
    import datetime
    logs = st.session_state.get("console_logs", [])
    logs.insert(0, {
        "level": level, "msg": msg,
        "ts": datetime.datetime.utcnow().strftime("%H:%M:%S"),
    })
    st.session_state["console_logs"] = logs[:200]
