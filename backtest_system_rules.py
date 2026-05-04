import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import os

# Define Universe
INDICES = ['QQQ', 'SPY']
MAG7 = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'TSLA', 'META']

def calculate_rsi_manual(series, period=2):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0))
    loss = (-delta.where(delta < 0, 0))
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def run_system_backtest():
    print("--- Running Backtest based on ACTUAL System Rules (Scanner.py) ---")
    
    # 1. Fetch QQQ for macro filter
    qqq = yf.download("QQQ", period="20y")
    if isinstance(qqq.columns, pd.MultiIndex): qqq.columns = qqq.columns.get_level_values(0)
    qqq.index = qqq.index.tz_localize(None)
    qqq['pct_change'] = qqq['Close'].pct_change()

    all_tickers = INDICES + MAG7
    report = []

    for ticker in all_tickers:
        print(f"Processing {ticker}...")
        df = yf.download(ticker, period="20y")
        if df.empty: continue
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        df.index = df.index.tz_localize(None)
        
        # Indicators as calculated in scanner.py
        df['pct_change'] = df['Close'].pct_change()
        df['rsi2'] = calculate_rsi_manual(df['Close'], 2)
        df['sma50'] = df['Close'].rolling(window=50).mean()
        
        # Join with QQQ macro
        df = df.join(qqq[['pct_change']], rsuffix='_qqq_macro')
        
        # Fetch Earnings for strict filtering (using heuristic for backtest)
        # Note: Historical earnings are approximate in this context
        earnings_dates = []
        try:
            t_obj = yf.Ticker(ticker)
            e_df = t_obj.get_earnings_dates(limit=50) # Recent years
            if e_df is not None and not e_df.empty:
                earnings_dates = pd.to_datetime(e_df.index).tz_localize(None).date
        except: pass

        stats = {'total': 0, 'win': 0, 'loss': 0}

        # Scan for signals
        for i in range(50, len(df)):
            row = df.iloc[i]
            prev_row = df.iloc[i-1]
            date = df.index[i].date()
            
            trigger = False
            # Engine 1 (Indices)
            if ticker in INDICES:
                if row['pct_change'] < -0.0125 or row['rsi2'] < 10:
                    trigger = True
            # Engine 2 (Stocks)
            else:
                if (row['pct_change'] < -0.04 and 
                    row['Close'] < row['sma50'] and 
                    row['pct_change_qqq_macro'] < -0.005):
                    # Filter earnings
                    if date in earnings_dates or (date + timedelta(days=1)) in earnings_dates:
                        continue
                    trigger = True

            if trigger:
                # Evaluation (Conservative Exit Rules)
                entry_price = float(row['Close'])
                strike = entry_price * 0.93
                tp_target = entry_price * 1.02
                sl_target = entry_price * 0.95
                
                # Next 31 trading days (~45 calendar days)
                future = df.iloc[i+1 : i+32]
                if future.empty: continue
                
                stats['total'] += 1
                trade_result = 'EXP'
                
                for j, (f_date, f_row) in enumerate(future.iterrows()):
                    f_close = float(f_row['Close'])
                    
                    # SL first
                    if f_close <= sl_target:
                        stats['loss'] += 1
                        trade_result = 'SL'
                        break
                    
                    # TP (10 days)
                    if j < 10 and f_close >= tp_target:
                        stats['win'] += 1
                        trade_result = 'TP'
                        break
                    
                    # Expiration
                    if j == len(future) - 1:
                        if f_close > strike:
                            stats['win'] += 1
                        else:
                            stats['loss'] += 1
                        break
        
        report.append((ticker, stats))

    print("\n" + "="*50)
    print("דוח בדיקה היסטורית - לפי כללי המערכת (Scanner.py)")
    print("="*50)
    print(f"{'Ticker':<8} | {'Trades':<6} | {'Win%':<8} | {'Wins':<5} | {'Losses':<5}")
    print("-" * 50)
    for ticker, s in report:
        wr = (s['win'] / s['total'] * 100) if s['total'] > 0 else 0
        print(f"{ticker:<8} | {s['total']:<6} | {wr:>6.1f}% | {s['win']:<5} | {s['loss']:<5}")

if __name__ == "__main__":
    run_system_backtest()
