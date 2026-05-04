import streamlit as st
import json
import os
import threading
import time
from scanner import AlertScanner
import global_state

CONFIG_FILE = "settings.json"

st.set_page_config(page_title="Mean Reversion Signal Bot", layout="wide")

# Default settings
DEFAULT_CONFIG = {
    "tg_token": "",
    "tg_chat_id": "",
    "gcs_bucket_name": "",
    "index_drop_thresh": 1.25,
    "index_rsi_thresh": 10.0,
    "stock_drop_thresh": 4.0,
    "macro_qqq_thresh": 0.5,
    "scan_interval_min": 5
}

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return DEFAULT_CONFIG.copy()

def save_config(cfg):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=4)

config = load_config()

st.title("📈 Dual-Engine Alert Agent (Model A)")

tab1, tab2, tab3 = st.tabs(["Control Panel", "Parameters", "Telegram Settings"])

with tab3:
    st.subheader("Cloud & Telegram Credentials")
    tg_token = st.text_input("Bot Token", value=config.get('tg_token', ''), type="password")
    tg_chat_id = st.text_input("Chat ID", value=config.get('tg_chat_id', ''))
    gcs_bucket = st.text_input("GCS Bucket Name (for persistence)", value=config.get('gcs_bucket_name', ''))
    if st.button("Save Credentials"):
        config['tg_token'] = tg_token
        config['tg_chat_id'] = tg_chat_id
        config['gcs_bucket_name'] = gcs_bucket
        save_config(config)
        st.success("Credentials saved!")

with tab2:
    st.subheader("Strategy Thresholds")
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Engine 1 (Indices)**")
        idx_drop = st.number_input("Index Drop Trigger (%)", value=config.get('index_drop_thresh', 1.25), step=0.1)
        idx_rsi = st.number_input("Index RSI(2) Trigger", value=config.get('index_rsi_thresh', 10.0), step=1.0)
    with col2:
        st.markdown("**Engine 2 (Stocks)**")
        stk_drop = st.number_input("Stock Drop Trigger (%)", value=config.get('stock_drop_thresh', 4.0), step=0.5)
        mac_qqq = st.number_input("QQQ Macro Drop Confirm (%)", value=config.get('macro_qqq_thresh', 0.5), step=0.1)
    
    interval = st.number_input("Scan Interval (minutes)", value=config.get('scan_interval_min', 5), min_value=1, max_value=60)
    
    if st.button("Save Parameters"):
        config['index_drop_thresh'] = idx_drop
        config['index_rsi_thresh'] = idx_rsi
        config['stock_drop_thresh'] = stk_drop
        config['macro_qqq_thresh'] = mac_qqq
        config['scan_interval_min'] = interval
        save_config(config)
        st.success("Parameters saved!")

with tab1:
    st.subheader("Bot Control")
    
    is_running = global_state.scanner is not None and global_state.scanner.is_running
    
    col_a, col_b = st.columns(2)
    with col_a:
        if not is_running:
            if st.button("▶️ Start Scanner", type="primary"):
                if not config['tg_token'] or not config['tg_chat_id']:
                    st.error("Please configure Telegram credentials first!")
                else:
                    global_state.scanner = AlertScanner(config, log_callback=global_state.add_log)
                    global_state.bot_thread = threading.Thread(target=global_state.scanner.start, daemon=True)
                    global_state.bot_thread.start()
                    st.success("Scanner started!")
                    time.sleep(0.5)
                    st.rerun()
        else:
            if st.button("⏹️ Stop Scanner", type="secondary"):
                if global_state.scanner:
                    global_state.scanner.stop()
                    global_state.add_log("Stop signal sent...")
                st.rerun()

    with col_b:
        status_text = "🟢 RUNNING" if is_running else "🔴 STOPPED"
        st.markdown(f"**Status:** {status_text}")
    
    st.markdown("### Live Console Logs")
    
    # Render logs
    log_container = st.empty()
    log_text = "\n".join(global_state.logs[-30:]) if global_state.logs else "No logs yet..."
    log_container.code(log_text, language="text")
    
    if st.button("🔄 Refresh Logs"):
        st.rerun()
