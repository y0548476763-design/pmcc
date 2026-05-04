import yfinance as yf
import pandas as pd
import numpy as np
from datetime import timedelta
import sys

# Define Tickers
INDICES = ['QQQ', 'SPY']
MAG7 = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'TSLA', 'META']

def calculate_hv(series, window=20):
    returns = np.log(series / series.shift(1))
    return returns.rolling(window=window).std() * np.sqrt(252)

def calculate_rsi_manual(series, period=2):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0))
    loss = (-delta.where(delta < 0, 0))
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def run_backtest():
    print("--- Starting Core Conservative Backtest (Indices + Mag7) ---")
    
    # Pre-fetch QQQ for the macro filter used by Mag7
    qqq_all = yf.download("QQQ", period="20y")
    if isinstance(qqq_all.columns, pd.MultiIndex): qqq_all.columns = qqq_all.columns.get_level_values(0)
    qqq_all.index = qqq_all.index.tz_localize(None)
    qqq_all['pct_change'] = qqq_all['Close'].pct_change()

    all_tickers = INDICES + MAG7
    final_report = []

    for ticker in all_tickers:
        print(f"Analyzing {ticker}...")
        df = yf.download(ticker, period="20y")
        if df.empty: continue
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        df.index = df.index.tz_localize(None)
        
        # Base indicators
        df['pct_change'] = df['Close'].pct_change()
        df['rsi2'] = calculate_rsi_manual(df['Close'], 2)
        df['sma50'] = df['Close'].rolling(window=50).mean()
        df['hv'] = calculate_hv(df['Close'], 20)
        df['hv_avg'] = df['hv'].rolling(window=100).mean()
        
        # Join with QQQ for macro filter
        df = df.join(qqq_all[['pct_change']], rsuffix='_qqq_macro')
        
        # Define Signal Logic
        if ticker in INDICES:
            # Model A (Index Rules)
            signals = df[(df['pct_change'] < -0.0125) | (df['rsi2'] < 10)].copy()
        else:
            # Strict Mag7 Rules
            signals = df[
                (df['pct_change'] < -0.04) & 
                (df['Close'] < df['sma50']) & 
                (df['hv'] > 1.3 * df['hv_avg']) & 
                (df['pct_change_qqq_macro'] < -0.005)
            ].copy()

        stats = {'total': 0, 'win_tp': 0, 'win_exp': 0, 'loss_sl': 0, 'loss_exp': 0}

        for entry_date, signal_row in signals.iterrows():
            entry_price = float(signal_row['Close'])
            strike_price = entry_price * 0.93
            tp_target = entry_price * 1.02
            sl_target = entry_price * 0.95
            
            # 45 calendar days lookahead (~31 trading bars)
            future_df = df.loc[entry_date:].iloc[1:32]
            if future_df.empty: continue
            
            stats['total'] += 1
            
            for i, (future_date, future_row) in enumerate(future_df.iterrows()):
                curr_close = float(future_row['Close'])
                
                # Check SL
                if curr_close <= sl_target:
                    stats['loss_sl'] += 1
                    break
                
                # Check TP (10 days)
                if i < 10 and curr_close >= tp_target:
                    stats['win_tp'] += 1
                    break
                
                # Check Expiration (45 days)
                if i == len(future_df) - 1:
                    if curr_close > strike_price:
                        stats['win_exp'] += 1
                    else:
                        stats['loss_exp'] += 1
                    break
        
        final_report.append((ticker, stats))

    # Detailed Hebrew Output
    print("\n" + "="*60)
    print("דוח סיכום שמרני (ריאלי) - מדדים ומניות Mag7")
    print("="*60)
    print(f"{'Ticker':<8} | {'Trades':<6} | {'Win%':<8} | {'TP':<5} | {'EXP_W':<6} | {'SL':<5}")
    print("-" * 60)
    
    for ticker, s in final_report:
        wins = s['win_tp'] + s['win_exp']
        wr = (wins / s['total'] * 100) if s['total'] > 0 else 0
        print(f"{ticker:<8} | {s['total']:<6} | {wr:>6.1f}% | {s['win_tp']:<5} | {s['win_exp']:<6} | {s['loss_sl']:<5}")

if __name__ == "__main__":
    run_backtest()
