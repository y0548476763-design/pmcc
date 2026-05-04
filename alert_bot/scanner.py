import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import time
import json
import os
import pickle
import telegram_api
import io

try:
    from google.cloud import storage
    GCS_AVAILABLE = True
except ImportError:
    GCS_AVAILABLE = False

class AlertScanner:
    def __init__(self, config, log_callback=None):
        self.config = config
        self.log_callback = log_callback
        self.is_running = False
        
        # GCS Settings
        self.bucket_name = config.get('gcs_bucket_name')
        if GCS_AVAILABLE and self.bucket_name:
            try:
                self.storage_client = storage.Client()
            except:
                self.storage_client = None
        else:
            self.storage_client = None
        
        # Local state filenames (used as keys in GCS)
        self.cooldown_file = "cooldown_state.json"
        self.cache_file = "market_data_cache.pkl"
        
        # Initialize state
        self.cooldowns = self.load_cooldowns()
        self.daily_cache = self.load_cache() # Persistence for daily history
        
        self.engine1_universe = ['QQQ', 'SPY']
        self.engine2_universe = [
            'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'TSLA', 'META', 
            'AVGO', 'COST', 'NFLX', 'ADBE', 'AMD', 'PEP', 'CSCO', 'INTC', 'QCOM', 'AMAT'
        ]
        self.all_tickers = list(set(self.engine1_universe + self.engine2_universe + ['QQQ']))

    def log(self, message):
        msg = f"[{datetime.now().strftime('%H:%M:%S')}] {message}"
        if self.log_callback:
            self.log_callback(msg)
        else:
            print(msg)

    # --- GCS Persistence Logic ---
    
    def _get_blob(self, filename):
        if not self.storage_client or not self.bucket_name:
            return None
        try:
            bucket = self.storage_client.bucket(self.bucket_name)
            return bucket.blob(filename)
        except:
            return None

    def load_cooldowns(self):
        blob = self._get_blob(self.cooldown_file)
        if blob and blob.exists():
            try:
                data = json.loads(blob.download_as_text())
                self.log("Loaded cooldowns from GCS.")
                return {k: datetime.fromisoformat(v) for k, v in data.items()}
            except Exception as e:
                self.log(f"Error loading cooldowns from GCS: {e}")
        
        # Fallback to local if GCS fails or doesn't exist
        if os.path.exists(self.cooldown_file):
            try:
                with open(self.cooldown_file, 'r') as f:
                    data = json.load(f)
                    return {k: datetime.fromisoformat(v) for k, v in data.items()}
            except: pass
        return {}

    def save_cooldowns(self):
        data = {k: v.isoformat() for k, v in self.cooldowns.items()}
        # Save Local
        with open(self.cooldown_file, 'w') as f:
            json.dump(data, f)
        # Upload to GCS
        blob = self._get_blob(self.cooldown_file)
        if blob:
            try:
                blob.upload_from_string(json.dumps(data))
                self.log("Uploaded cooldowns to GCS.")
            except Exception as e:
                self.log(f"Failed to upload cooldowns to GCS: {e}")

    def load_cache(self):
        blob = self._get_blob(self.cache_file)
        if blob and blob.exists():
            try:
                buffer = blob.download_as_bytes()
                self.log("Loaded market data cache from GCS.")
                return pickle.loads(buffer)
            except Exception as e:
                self.log(f"Error loading cache from GCS: {e}")
        
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, 'rb') as f:
                    return pickle.load(f)
            except: pass
        return {}

    def save_cache(self):
        # Save Local
        with open(self.cache_file, 'wb') as f:
            pickle.dump(self.daily_cache, f)
        # Upload to GCS
        blob = self._get_blob(self.cache_file)
        if blob:
            try:
                blob.upload_from_string(pickle.dumps(self.daily_cache))
                self.log("Uploaded market data cache to GCS.")
            except Exception as e:
                self.log(f"Failed to upload cache to GCS: {e}")

    # --- Strategy Logic ---

    def calculate_rsi(self, series, period=2):
        delta = series.diff()
        gain = (delta.where(delta > 0, 0))
        loss = (-delta.where(delta < 0, 0))
        avg_gain = gain.rolling(window=period).mean()
        avg_loss = loss.rolling(window=period).mean()
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi

    def has_earnings_soon(self, ticker):
        try:
            t_obj = yf.Ticker(ticker)
            dates = t_obj.get_earnings_dates(limit=5)
            if dates is not None and not dates.empty:
                earnings_dates = pd.to_datetime(dates.index).tz_localize(None).date
                today = datetime.now().date()
                tomorrow = today + timedelta(days=1)
                if today in earnings_dates or tomorrow in earnings_dates:
                    return True
        except: pass
        return False

    def scan_once(self):
        self.log("--- Starting Cloud-Optimized Scan Cycle ---")
        start_time = time.time()
        
        # 1. Fetch Daily History (Bulk)
        # In a real production scenario, we'd check if we already have the cache for today
        # But yfinance is fast enough that we refresh the history each cycle
        self.log("Fetching 3-month daily history...")
        hist_data = yf.download(self.all_tickers, period="3mo", interval="1d", group_by="ticker", progress=False)
        
        # 2. Fetch Live Intraday Data (Bulk)
        self.log("Fetching real-time minute data...")
        live_data = yf.download(self.all_tickers, period="1d", interval="1m", group_by="ticker", progress=False)
        
        if hist_data.empty:
            self.log("[!] Failed to fetch market data.")
            return

        # Update cache in memory (and persist)
        self.daily_cache['last_update'] = datetime.now().isoformat()
        # Note: We store the raw close prices in the cache for GCS persistence
        self.daily_cache['hist_closes'] = hist_data.xs('Close', axis=1, level=1)
        self.save_cache()

        # Pre-calculate Macro QQQ Drop
        try:
            qqq_live_df = live_data['QQQ'].dropna()
            qqq_live = float(qqq_live_df['Close'].iloc[-1]) if not qqq_live_df.empty else float(hist_data['QQQ']['Close'].dropna().iloc[-1])
            qqq_prev = float(hist_data['QQQ']['Close'].dropna().iloc[-2])
            qqq_drop_pct = ((qqq_live - qqq_prev) / qqq_prev) * 100
            self.log(f"Macro QQQ State: Price=${qqq_live:.2f}, Drop={qqq_drop_pct:.2f}%")
        except Exception as e:
            self.log(f"[!] QQQ Calculation Error: {e}")
            return

        # Process tickers
        for ticker in self.all_tickers:
            if ticker in self.cooldowns:
                if (datetime.now() - self.cooldowns[ticker]).total_seconds() < 86400:
                    continue
                
            try:
                t_hist = hist_data[ticker].dropna(subset=['Close'])
                if len(t_hist) < 50: continue
                
                t_live = live_data[ticker].dropna(subset=['Close'])
                current_price = float(t_live['Close'].iloc[-1]) if not t_live.empty else float(t_hist['Close'].iloc[-1])
                prev_close = float(t_hist['Close'].iloc[-2])
                drop_pct = ((current_price - prev_close) / prev_close) * 100
                
                closes = t_hist['Close'].copy()
                closes.iloc[-1] = current_price
                
                rsi_val = self.calculate_rsi(closes, period=2).iloc[-1]
                sma_50_val = closes.rolling(window=50).mean().iloc[-1]
                
                if ticker in self.engine1_universe:
                    if drop_pct < -self.config['index_drop_thresh'] or rsi_val < self.config['index_rsi_thresh']:
                        strike = current_price * 0.93
                        msg = (f"🚨 <b>INDEX PANIC</b>: {ticker} dropped by {drop_pct:.2f}%.\n"
                               f"RSI(2) is {rsi_val:.2f}.\n"
                               f"Consider selling 15-Delta Put Spread (45 DTE).\n"
                               f"Target Strike: ~${strike:.2f}")
                        self.send_alert(ticker, msg)

                elif ticker in self.engine2_universe:
                    if drop_pct < -self.config['stock_drop_thresh'] and current_price < sma_50_val and qqq_drop_pct < -self.config['macro_qqq_thresh']:
                        if self.has_earnings_soon(ticker):
                            continue
                            
                        strike = current_price * 0.93
                        msg = (f"🚨 <b>STOCK PANIC</b>: {ticker} dropped by {drop_pct:.2f}%.\n"
                               f"Trading below SMA50 (${sma_50_val:.2f}). QQQ confirms panic ({qqq_drop_pct:.2f}%).\n"
                               f"Consider selling Put Spread. Target Strike: ~${strike:.2f}")
                        self.send_alert(ticker, msg)
                        
            except Exception as e:
                self.log(f"Error processing {ticker}: {e}")
                
        self.save_cooldowns() # Final upload of any new alerts
        elapsed = time.time() - start_time
        self.log(f"Scan cycle complete in {elapsed:.2f} seconds.")

    def send_alert(self, ticker, message):
        self.log(f"--> ALERT TRIGGERED for {ticker}")
        success, err = telegram_api.send_telegram_alert(self.config['tg_token'], self.config['tg_chat_id'], message)
        if success:
            self.log(f"Alert sent to Telegram for {ticker}")
            self.cooldowns[ticker] = datetime.now()
        else:
            self.log(f"Failed to send Telegram alert: {err}")

    def start(self):
        self.is_running = True
        interval = self.config.get('scan_interval_min', 5) * 60
        self.log(f"Bot started. Interval: {interval} seconds.")
        while self.is_running:
            try:
                self.scan_once()
            except Exception as e:
                self.log(f"Critical scan loop error: {e}")
            for _ in range(interval):
                if not self.is_running: break
                time.sleep(1)

    def stop(self):
        self.is_running = False
        self.log("Bot stopping...")
