import yfinance as yf
import pandas as pd
import numpy as np
from datetime import timedelta
import sys

# Define Tickers
TICKERS = ['AVGO', 'COST', 'NFLX', 'ADBE', 'AMD', 'PEP', 'CSCO', 'INTC', 'QCOM', 'AMAT']

def calculate_hv(series, window=20):
    returns = np.log(series / series.shift(1))
    return returns.rolling(window=window).std() * np.sqrt(252)

def run_backtest():
    print("--- Starting Conservative Backtest (No Execution Bias) ---")
    
    # 1. Fetch QQQ data for macro filter
    qqq = yf.download("QQQ", period="20y")
    if isinstance(qqq.columns, pd.MultiIndex): qqq.columns = qqq.columns.get_level_values(0)
    qqq.index = qqq.index.tz_localize(None)
    qqq['pct_change'] = qqq['Close'].pct_change()

    total_stats = {
        'total_trades': 0,
        'win_tp': 0,
        'win_exp': 0,
        'loss_sl': 0,
        'loss_exp': 0,
        'ticker_stats': {}
    }

    for ticker in TICKERS:
        print(f"Analyzing {ticker}...")
        df = yf.download(ticker, period="20y")
        if df.empty: continue
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        df.index = df.index.tz_localize(None)
        
        # Calculate Indicators
        df['pct_change'] = df['Close'].pct_change()
        df['sma50'] = df['Close'].rolling(window=50).mean()
        df['hv'] = calculate_hv(df['Close'], window=20)
        df['hv_avg'] = df['hv'].rolling(window=100).mean()
        
        # Join with QQQ
        df = df.join(qqq[['pct_change']], rsuffix='_qqq')
        
        # Identify Signals
        signals = df[
            (df['pct_change'] < -0.04) &             # Stock drop > 4%
            (df['Close'] < df['sma50']) &            # Price < SMA50
            (df['hv'] > 1.3 * df['hv_avg']) &        # HV > 1.3 * HV_Avg
            (df['pct_change_qqq'] < -0.005)          # QQQ drop > 0.5%
        ].copy()

        ticker_results = {'wins': 0, 'losses': 0, 'total': 0}

        for entry_date, signal_row in signals.iterrows():
            entry_price = float(signal_row['Close'])
            strike_price = entry_price * 0.93
            tp_target = entry_price * 1.02
            sl_target = entry_price * 0.95
            
            # Look ahead for 45 calendar days (roughly 31 trading days)
            future_df = df.loc[entry_date:].iloc[1:32] # Next 31 trading bars
            if future_df.empty: continue
            
            trade_closed = False
            total_stats['total_trades'] += 1
            ticker_results['total'] += 1
            
            # Check for TP or SL using CLOSE price only (Realism)
            for i, (future_date, future_row) in enumerate(future_df.iterrows()):
                curr_close = float(future_row['Close'])
                
                # Check Stop Loss First (Conservative)
                if curr_close <= sl_target:
                    total_stats['loss_sl'] += 1
                    ticker_results['losses'] += 1
                    trade_closed = True
                    break
                
                # Check Take Profit (Only within first 10 trading days for MR)
                if i < 10 and curr_close >= tp_target:
                    total_stats['win_tp'] += 1
                    ticker_results['wins'] += 1
                    trade_closed = True
                    break
                
                # Exit at Expiration (45 days / end of future_df)
                if i == len(future_df) - 1:
                    if curr_close > strike_price:
                        total_stats['win_exp'] += 1
                        ticker_results['wins'] += 1
                    else:
                        total_stats['loss_exp'] += 1
                        ticker_results['losses'] += 1
                    trade_closed = True
                    break
            
        total_stats['ticker_stats'][ticker] = ticker_results

    # Report in Hebrew
    print("\n" + "="*50)
    print("דוח סיכום אסטרטגיה - מודל שמרני (ללא הטיות ביצוע)")
    print("="*50)
    
    total = total_stats['total_trades']
    wins = total_stats['win_tp'] + total_stats['win_exp']
    win_rate = (wins / total * 100) if total > 0 else 0
    
    print(f"סה\"כ טריידים: {total}")
    print(f"אחוז הצלחה ריאלי: {win_rate:.2f}%")
    print("-" * 30)
    print(f"ניצחונות (TP ב-10 ימים): {total_stats['win_tp']}")
    print(f"ניצחונות (פקיעה מעל סטרייק): {total_stats['win_exp']}")
    print(f"הפסדים (Stop Loss של 5%): {total_stats['loss_sl']}")
    print(f"הפסדים (פקיעה מתחת לסטרייק): {total_stats['loss_exp']}")
    print("-" * 30)
    
    print("\nסטטיסטיקה לפי מניה:")
    for ticker, stats in total_stats['ticker_stats'].items():
        t_wr = (stats['wins'] / stats['total'] * 100) if stats['total'] > 0 else 0
        print(f"{ticker}: {stats['total']} טריידים | {t_wr:.1f}% הצלחה")

if __name__ == "__main__":
    run_backtest()
