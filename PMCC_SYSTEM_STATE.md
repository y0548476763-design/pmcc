# PMCC Quant Dashboard & Bot - System Summary

This document outlines the current state, architecture, and pending tasks of the PMCC (Poor Man's Covered Call) trading system. **Read this first when starting a new chat context.**

## 1. Core Architecture
The system is divided into a **Streamlit UI** and a **Background Automation Bot**, communicating via shared modules and IBKR (Interactive Brokers) via `ib_insync`.

*   **`app.py`**: The Streamlit entry point. Contains the UI tabs (Portfolio, Shield, Matrix, etc.). Run via `streamlit run app.py`.
*   **`ibkr_auto_bot.py`**: A standalone continuous back-end loop. Connects to TWS, scans positions every 60 seconds during market hours, and executes the PMCC strategy.
*   **`tws_client.py` (`TWSClient`)**: Abstracts `ib_insync`. Handles demo fallback, live connections, and order placement (`place_adaptive_order`, `place_combo_order`). Uses **Yahoo Finance (`yfinance`)** to fetch option chains and avoid IBKR data fees.
*   **`order_manager.py` (`OrderManager`)**: A background threading system that handles **Smart Order Escalation**. If a Limit or Combo order isn't filled within `N` minutes, it automatically steps up/down the price by a set percentage natively in TWS.
*   **`quant_engine.py`**: Fetches historical stock data (YF) to calculate technicals (RSI, SMA200, HV30). Outputs 4 signal states: `NO_TRADE`, `DEFENSIVE`, `NORMAL`, `AGGRESSIVE`, dictating the Delta target for short calls.
*   **`settings_manager.py`**: Stores persistent user configurations (`user_settings.json`), including `external_cash` and `bot_active` (Master Switch).
*   **`config.py`**: Static thresholds (Take Profit = 30%, LEAPS Roll DTE = 360, etc.).

## 2. Trading Logic (The Engine)
*   **Short Calls (Income)**: The bot continuously opens Short Calls against ITM LEAPS based on the `quant_engine` delta signals.
*   **Proactive Take Profit**: When a short call is opened, the bot immediately places a **GTC Limit Buy** order for 30% profit.
*   **Time Stops**: Closes short calls at 21 DTE or if Delta breaches 0.40.
*   **LEAPS Strategy**: Wait for -20% or -35% dips to buy. Need to be rolled when DTE falls below 360 days.

## 3. Current Work in Progress (Handover Status)
We are currently midway through an infrastructure update to add **Smart LEAPS Rolling** and a **Master Bot Switch**.

### What has been completed:
1.  **Sidebar Toggle (`ui/sidebar.py`)**: The UI now has a Master Switch that saves the boolean `bot_active` state via `settings_manager`.
2.  **Combo Orders (`tws_client.py`)**: `place_combo_order()` was added to support multi-leg spread execution (simultaneous Sell Old + Buy New).
3.  **LEAPS Discovery (`tws_client.py`)**: `get_leaps_options(min_dte=500, target_delta=0.8)` was added to scan YF for optimal roll targets.
4.  **Escalation Logic (`order_manager.py`)**: Handles `is_combo` flags and steps the net debit price up every minute to capture the tightest spread without manual babysitting.

### What STILL NEEDS to be done (Next Steps for New Chat):
1.  **Update `ibkr_auto_bot.py`**:
    *   Currently, the bot ignores the `bot_active` state. You need to wrap the `_open_new_short` and execution logic to respect the Master Switch (if OFF, only log alerts, do not place orders).
    *   Add the logic to automatically trigger the `OrderManager` Combo Roll if a LEAPS drops below 360 DTE.
2.  **Create the Manual Roll UI (`ui/roll_tab.py`)**:
    *   Build a new Streamlit tab.
    *   Provide a dropdown of current LEAPS positions.
    *   Display 3 valid roll targets (using `tws_client.get_leaps_options`).
    *   Provide a "Execute Roll" button that triggers the `OrderManager` with the Combo Spread.
3.  **Register the Tab**: Add `roll_tab.py` into the main `app.py` navigation.

## 4. Setup Notes
*   **Dependencies**: Requires `yfinance`, `streamlit`, `pandas`, `ib_insync`.
*   **TWS/Gateway**: Must be running. Port 4002 (Paper) or 7496 (Live). Client IDs ~42-46.
