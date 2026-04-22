"""
ui/roll_tab.py — LEAPS Roll Manager
Phase A: Yahoo Finance search (independent) → choose new LEAPS
Phase B: Resolve both on IBKR → send combo BAG order with escalation
"""
import streamlit as st
import threading
import time
from datetime import datetime, timezone
import requests
import urllib3
import config
import settings_manager
from tws_client import TWSClient

# Deferred imports can be moved to top if modules are globally available
import tws_combo
from ib_insync import Option as IBOption

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ── helpers ──────────────────────────────────────────────────────────────────

def _dte(exp: str) -> int:
    try:
        return max(0, (datetime.strptime(str(exp).replace("-",""), "%Y%m%d").date()
                       - datetime.now(timezone.utc).date()).days)
    except Exception:
        return 0

def _send_tg(msg: str) -> bool:
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{settings_manager.get_telegram_token()}/sendMessage",
            json={"chat_id": settings_manager.get_telegram_chat_id(),
                  "text": msg, "parse_mode": "HTML"}, timeout=8)
        return r.status_code == 200
    except Exception:
        return False

# ── Yahoo Finance with cookie session ────────────────────────────────────────

def _yahoo_session():
    """Create a requests.Session with Yahoo Finance cookies."""
    s = requests.Session()
    s.headers.update({
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/124.0.0.0 Safari/537.36"),
        "Accept": "application/json,text/html",
    })
    try:
        s.get("https://finance.yahoo.com", verify=False, timeout=6)
    except Exception:
        pass
    return s

def _search_yahoo_leaps(ticker: str, min_dte: int, target_delta: float,
                         n: int = 5) -> list:
    """Search Yahoo Finance for LEAPS call options. Uses 4-hour cache."""
    cache_key = f"leaps_{ticker}_{min_dte}_{target_delta}"
    cache = st.session_state.setdefault("_leaps_cache", {})
    if cache_key in cache:
        data, ts = cache[cache_key]
        if time.time() - ts < 14400:
            return data

    try:
        sess = _yahoo_session()

        # ── get available expirations ──
        r = sess.get(
            f"https://query2.finance.yahoo.com/v7/finance/options/{ticker}"
            "?formatted=false&lang=en-US&region=US",
            verify=False, timeout=12)

        if r.status_code != 200:
            st.error(f"❌ Yahoo Finance: HTTP {r.status_code} עבור {ticker}")
            return []

        root = r.json().get("optionChain", {}).get("result", [])
        if not root:
            st.error(f"❌ Yahoo לא החזיר תוצאות עבור {ticker}")
            return []

        all_ts = root[0].get("expirationDates", [])
        now_ts = time.time()

        # filter by min_dte
        valid = [(ts, int((ts - now_ts) / 86400))
                 for ts in all_ts if int((ts - now_ts) / 86400) >= min_dte]
        if not valid:
            # fallback: furthest available
            valid = [(ts, int((ts - now_ts) / 86400)) for ts in all_ts]
        if not valid:
            st.warning("לא נמצאו פקיעות מתאימות ביאהו פיננס.")
            return []

        valid.sort(key=lambda x: x[1])
        exp_ts, exp_dte = valid[0]
        exp_str = datetime.fromtimestamp(exp_ts, tz=timezone.utc).strftime("%Y-%m-%d")

        # ── get chain for chosen expiry ──
        r2 = sess.get(
            f"https://query2.finance.yahoo.com/v7/finance/options/{ticker}"
            f"?formatted=false&lang=en-US&region=US&date={exp_ts}",
            verify=False, timeout=12)

        if r2.status_code != 200:
            st.error(f"❌ Yahoo: HTTP {r2.status_code} (chain)")
            return []

        chain_data = r2.json().get("optionChain", {}).get("result", [])
        if not chain_data:
            return []

        calls = chain_data[0].get("options", [{}])[0].get("calls", [])
        underlying = float(chain_data[0].get("quote", {})
                          .get("regularMarketPrice", 0) or 0)

        if not calls:
            st.warning("שרשרת האופציות ריקה.")
            return []

        results = []
        for c in calls:
            strike = float(c.get("strike", 0) or 0)
            bid    = float(c.get("bid",    0) or 0)
            ask    = float(c.get("ask",    0) or 0)
            last   = float(c.get("lastPrice", 0) or 0)
            mid    = (bid + ask) / 2 if bid > 0 and ask > 0 else last
            if mid <= 0 or strike <= 0:
                continue
            
            mono  = strike / underlying if underlying > 0 else 1.0
            delta = max(0.05, min(0.99, 1.30 - mono * 0.80))
            
            results.append({
                "ticker": ticker, "strike": round(strike, 2),
                "expiry": exp_str, "dte": exp_dte, "right": "C",
                "delta": round(delta, 2), "mid": round(mid, 2),
                "bid": round(bid, 2), "ask": round(ask, 2),
                "source": "Yahoo Finance",
            })

        results.sort(key=lambda x: abs(x["delta"] - target_delta))
        final = results[:n]
        cache[cache_key] = (final, time.time())
        return final

    except Exception as e:
        st.error(f"❌ שגיאה בחיפוש Yahoo Finance: {e}")
        return []

# ── Phase B: resolve on IBKR + send combo ────────────────────────────────────

def _execute_combo(tws: TWSClient, old_lp: dict, new_tgt: dict,
                   esc_mins: int, esc_step: float,
                   bot_mode: int, via_bot: bool):

    ticker = old_lp["ticker"]
    qty    = abs(old_lp.get("qty", 1))

    if via_bot:
        if bot_mode == 0:
            st.warning("הבוט כבוי (מצב 0). השתמש בביצוע ידני.")
            return
        if bot_mode == 1:
            ok = _send_tg(
                f"❓ <b>אישור גלגול ליפס — {ticker}</b>\n"
                f"📤 מוכר: ${float(old_lp['strike']):.0f}  {old_lp['expiry']}\n"
                f"📥 קונה:  ${float(new_tgt['strike']):.0f}  {new_tgt['expiry']}\n"
                f"  Δ≈{new_tgt['delta']:.2f}\n⚠️ השב YES לאישור.")
            st.info("📱 נשלח לטלגרם!" if ok else "❌ כשל בשליחה")
            return

    if not tws or not getattr(tws, "connected", False) or not getattr(tws, "ib", None):
        st.error("❌ לא מחובר ל-TWS. לא ניתן לשלוח פקודה.")
        return

    ib = tws.ib

    with st.spinner("🔄 מאמת חוזים ב-IBKR ושואב מחירים חיים..."):
        try:
            sell_c = IBOption(ticker,
                              str(old_lp["expiry"]).replace("-",""),
                              float(old_lp["strike"]), "C", "SMART", currency="USD")
            buy_c  = IBOption(ticker,
                              str(new_tgt["expiry"]).replace("-",""),
                              float(new_tgt["strike"]), "C", "SMART", currency="USD")
            
            ib.qualifyContracts(sell_c, buy_c)

            if not sell_c.conId or not buy_c.conId:
                st.error("❌ לא ניתן לאמת חוזים ב-IBKR.")
                return

            tks = ib.reqTickers(sell_c, buy_c)
            ib.sleep(0.5)

            def _mid(t):
                b = t.bid if t.bid and t.bid > 0 else 0
                a = t.ask if t.ask and t.ask > 0 else 0
                return (b+a)/2 if b > 0 and a > 0 else (t.last or 0)

            ms = _mid(tks[0]) or float(old_lp.get("current_price", 0))
            mb = _mid(tks[1]) or float(new_tgt.get("mid", 0))
            combo_mid = round(mb - ms, 2)

            st.info(f"✅ SELL conId={sell_c.conId} (${ms:.2f}) | "
                    f"BUY conId={buy_c.conId} (${mb:.2f}) | "
                    f"קומבו Mid: **${combo_mid:.2f}**")

            # Execute synchronously to avoid ib_insync threading issues
            with st.spinner("⏳ שולח פקודת COMBO (BAG)..."):
                r = tws_combo.execute_combo_roll(
                    ib=ib,
                    sell_conid=sell_c.conId, sell_strike=sell_c.strike,
                    sell_expiry=sell_c.lastTradeDateOrContractMonth,
                    buy_conid=buy_c.conId,  buy_strike=buy_c.strike,
                    buy_expiry=buy_c.lastTradeDateOrContractMonth,
                    ticker=ticker, qty=qty,
                    limit_price=combo_mid, use_market=False,
                    escalation_step_pct=float(esc_step),
                    escalation_wait_secs=int(esc_mins)*60,
                    max_escalations=10,
                    log_cb=tws._log if hasattr(tws,"_log") else None,
                )

            if isinstance(r, dict) and r.get("status") == "FILLED":
                fill = r.get("fill_price", 0)
                _send_tg(f"🔄 <b>גלגול בוצע!</b>\n{ticker}\n"
                         f"📤 ${sell_c.strike:.0f}C  {sell_c.lastTradeDateOrContractMonth}\n"
                         f"📥 ${buy_c.strike:.0f}C  {buy_c.lastTradeDateOrContractMonth}\n"
                         f"💰 ${fill:.2f}")
                st.toast(f"✅ גלגול בוצע במחיר ${fill:.2f}", icon="🔄")
            elif isinstance(r, dict) and r.get("status") in ["PENDING", "ESCALATED"]:
                 st.success("⏳ פקודה נשלחה — ממתינה למילוי (Escalation פעיל).")
            else:
                 status_msg = r.get("status", "UNKNOWN") if isinstance(r, dict) else str(r)
                 st.error(f"❌ הפקודה נכשלה או במצב לא ידוע: {status_msg}")

        except Exception as e:
            st.error(f"❌ שגיאה קריטית בעת שליחת הפקודה: {e}")

    for k in ("roll_new_selected",):
        st.session_state.pop(k, None)
    st.rerun()

# ── Main render ───────────────────────────────────────────────────────────────

def render_roll_tab(tws: TWSClient) -> None:
    st.markdown("""
    <div style="padding:0.4rem 0 1rem 0;">
      <div class="pmcc-title">🔄 גלגול ליפסים — LEAPS Roll Engine</div>
      <div style="font-size:0.72rem;color:#64748b;margin-top:3px;">
        חיפוש ביאהו פיננס · אימות ב-IBKR · פקודת קומבו BAG עם הסלמה חכמה
      </div>
    </div>""", unsafe_allow_html=True)

    bot_mode = settings_manager.get_bot_mode()

    # ══════════════════════════════════════════════════════════════
    # PHASE A — Search Yahoo Finance (completely independent search)
    # ══════════════════════════════════════════════════════════════
    st.markdown('<div class="section-hdr">🔎 שלב א — חפש ליפס חדש ביאהו פיננס</div>',
                unsafe_allow_html=True)

    row1, row2, row3, row4 = st.columns([2, 2, 2, 1])
    with row1:
        ticker = st.text_input("טיקר:", value=st.session_state.get("roll_ticker","META"),
                               key="roll_ticker_input", placeholder="META / QQQ...").upper().strip()
    with row2:
        min_dte = st.number_input("מינימום DTE:", 200, 1000, 650, step=30, key="roll_min_dte")
    with row3:
        tgt_delta = st.slider("דלתא יעד:", 0.50, 0.99, 0.80, step=0.01, key="roll_tgt_delta")
    with row4:
        st.write("")
        st.write("")
        search_clicked = st.button("🔍 חפש", key="roll_search",
                                   type="primary", use_container_width=True)

    if search_clicked and ticker:
        # Clear old results when searching new ticker
        if st.session_state.get("roll_ticker") != ticker:
            for k in ("roll_targets","roll_new_selected"):
                st.session_state.pop(k, None)
        st.session_state["roll_ticker"] = ticker

        with st.spinner(f"מחפש LEAPS עבור {ticker} ביאהו פיננס..."):
            results = _search_yahoo_leaps(ticker, min_dte, tgt_delta)

        if results:
            st.session_state["roll_targets"] = results
            st.toast(f"נמצאו {len(results)} אפשרויות!", icon="🔍")
        else:
            st.session_state.pop("roll_targets", None)

    # ── Display search results ─────────────────────────────────────
    targets = st.session_state.get("roll_targets", [])

    if targets:
        st.markdown('<div class="section-hdr">📋 תוצאות — בחר ליפס יעד</div>',
                    unsafe_allow_html=True)
        cols = st.columns(len(targets))
        for i, tgt in enumerate(targets):
            with cols[i]:
                dc = "#f87171" if tgt["dte"] < 400 else ("#fbbf24" if tgt["dte"] < 600 else "#34d399")
                st.markdown(f"""
                <div class="pmcc-card" style="border-top:3px solid #6366f1;
                     padding:0.8rem 0.5rem;text-align:center;">
                  <div style="font-size:0.6rem;color:#64748b;">#{i+1}</div>
                  <div style="font-size:1.4rem;font-weight:900;color:#f1f5f9;">
                    ${tgt['strike']:.0f}</div>
                  <div style="font-size:0.68rem;color:#64748b;">{tgt['expiry']}</div>
                  <div style="font-size:0.7rem;color:{dc};font-weight:600;">{tgt['dte']}d</div>
                  <div style="color:#818cf8;font-weight:700;">Δ {tgt['delta']:.2f}</div>
                  <div style="font-size:1.05rem;font-weight:900;color:#34d399;">${tgt['mid']:.2f}</div>
                  <div style="font-size:0.6rem;color:#475569;">
                    B:{tgt['bid']:.2f} / A:{tgt['ask']:.2f}</div>
                </div>""", unsafe_allow_html=True)
                if st.button(f"✅ בחר", key=f"pick_{i}", use_container_width=True):
                    st.session_state["roll_new_selected"] = tgt
                    st.rerun()

        if st.button("🗑️ נקה", key="roll_clear_btn"):
            for k in ("roll_targets","roll_new_selected"):
                st.session_state.pop(k, None)
            st.rerun()

    # ══════════════════════════════════════════════════════════════
    # PHASE B — Pick old LEAPS from portfolio → execute combo
    # ══════════════════════════════════════════════════════════════
    new_tgt = st.session_state.get("roll_new_selected")
    if not new_tgt:
        return

    st.markdown("---")
    st.markdown('<div class="section-hdr">📤 שלב ב — בחר ליפס ישן לסגירה ושלח קומבו</div>',
                unsafe_allow_html=True)

    # New LEAPS summary bar
    st.markdown(f"""
    <div style="background:rgba(56,189,248,0.08);border:1px solid rgba(56,189,248,0.3);
         border-radius:10px;padding:0.7rem 1rem;margin-bottom:1rem;direction:rtl;">
      <b style="color:#38bdf8;">ליפס חדש (BUY):</b> &nbsp;
      {new_tgt['ticker']} &nbsp;|&nbsp; Strike <b>${new_tgt['strike']:.0f}</b>
      &nbsp;|&nbsp; {new_tgt['expiry']} &nbsp;|&nbsp;
      <span style="color:#34d399">{new_tgt['dte']}d</span> &nbsp;|&nbsp;
      Δ {new_tgt['delta']:.2f} &nbsp;|&nbsp;
      מחיר: <b style="color:#34d399">${new_tgt['mid']:.2f}</b>
    </div>""", unsafe_allow_html=True)

    # Old LEAPS from portfolio
    all_pos = st.session_state.get("positions", [])
    old_leaps = [p for p in all_pos
                 if p.get("type") == "LEAPS" and p.get("qty", 0) > 0
                 and p.get("ticker","") == new_tgt["ticker"]]
    if not old_leaps:
        old_leaps = [p for p in all_pos
                     if p.get("type") == "LEAPS" and p.get("qty", 0) > 0]

    if not old_leaps:
        st.warning("לא נמצאו פוזיציות LEAPS בתיק. ודא שהנתונים עודכנו בטאב פרוטפוליו.")
        if st.button("↩️ חזור לחיפוש", key="back_search"):
            st.session_state.pop("roll_new_selected", None)
            st.rerun()
        return

    def _lbl(p):
        d = p.get("dte", _dte(p.get("expiry","")))
        return f"{p['ticker']} | ${p.get('strike',0):.0f} | {p.get('expiry','')} | {d}d"

    labels  = [_lbl(p) for p in old_leaps]
    old_map = dict(zip(labels, old_leaps))

    col_left, col_right = st.columns([3, 2])
    with col_left:
        old_sel = st.selectbox("ליפס ישן לסגירה (SELL):", labels, key="roll_old_sel")
        old_lp  = old_map[old_sel]
        od      = old_lp.get("dte", _dte(old_lp.get("expiry","")))
        oc      = "#f87171" if od < 360 else "#fbbf24"
        st.markdown(f"""
        <div style="background:rgba(248,113,113,0.06);border:1px solid rgba(248,113,113,0.3);
             border-radius:8px;padding:0.55rem 0.9rem;font-size:0.82rem;direction:rtl;">
          <b style="color:#f87171;">ליפס ישן (SELL):</b> &nbsp;
          {old_lp['ticker']} &nbsp;|&nbsp; Strike <b>${float(old_lp['strike']):.0f}</b>
          &nbsp;|&nbsp; {old_lp.get('expiry','')}
          &nbsp;|&nbsp; <span style="color:{oc}">{od}d</span>
        </div>""", unsafe_allow_html=True)

        # Net cost preview
        mid_old = float(old_lp.get("current_price", 0))
        net     = round(new_tgt["mid"] - mid_old, 2)
        nc      = "#f87171" if net > 0 else "#34d399"
        nlbl    = f"עלות גלגול: ${net:.2f}" if net > 0 else f"קרדיט: ${abs(net):.2f}"
        st.markdown(f"""
        <div style="text-align:center;padding:0.5rem;font-weight:700;color:{nc};font-size:1rem;">
          {nlbl}
        </div>""", unsafe_allow_html=True)

    with col_right:
        st.markdown('<div class="pmcc-header" style="margin-bottom:6px">⚙️ הגדרות ביצוע</div>',
                    unsafe_allow_html=True)
        esc_mins = st.number_input("המתנה לפני הסלמה (דקות):", 1, 30,
                                   config.ESCALATION_WAIT_MINUTES, key="roll_esc_mins")
        esc_step = st.number_input("הסלמה (%):", 0.1, 5.0,
                                   config.ESCALATION_STEP_PCT, step=0.1, key="roll_esc_step")

    c1, c2, c3 = st.columns([2, 2, 1])
    with c1:
        if st.button("✋ ביצוע ידני", key="exec_manual",
                     type="primary", use_container_width=True):
            _execute_combo(tws, old_lp, new_tgt, esc_mins, esc_step,
                           bot_mode, via_bot=False)
    with c2:
        if st.button("🤖 ביצוע בוט", key="exec_bot", use_container_width=True):
            _execute_combo(tws, old_lp, new_tgt, esc_mins, esc_step,
                           bot_mode, via_bot=True)
    with c3:
        if st.button("↩️ ביטול", key="exec_cancel", use_container_width=True):
            st.session_state.pop("roll_new_selected", None)
            st.rerun()

    # ── Active Orders Monitor ──────────────────────────────────────
    try:
        import order_manager as _om_mod
        _om = _om_mod.get_manager()
        active = {i: mo for i, mo in _om._orders.items()
                  if mo.status in ("PENDING","ESCALATED") and mo.is_combo}
        if active:
            st.markdown("---")
            st.markdown("### 📋 פקודות קומבו פעילות")
            for iid, mo in active.items():
                sc = "#fbbf24" if mo.status == "ESCALATED" else "#38bdf8"
                st.markdown(f"""
                <div style="background:rgba(15,23,42,0.7);border:1px solid {sc};
                     border-radius:8px;padding:0.6rem 1rem;margin:0.3rem 0;direction:rtl;">
                  <b style="color:{sc};">{iid}</b> | {mo.ticker} ${mo.strike:.0f}C
                  | מחיר: ${mo.current_price:.2f}
                  | <span style="color:{sc};">{mo.status}</span>
                  | הסלמות: {mo.escalation_count}
                </div>""", unsafe_allow_html=True)
            if st.button("🔄 רענן", key="refresh_orders"):
                st.rerun()
    except Exception:
        pass