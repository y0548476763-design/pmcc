import yfinance as yf
import pandas as pd
import numpy as np
from datetime import timedelta
import sys

# Define Mag7 Tickers
MAG7 = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'TSLA', 'META']

def calculate_hv(series, window=20):
    """
    Calculates Historical Volatility as a proxy for IV.
    """
    log_return = np.log(series / series.shift(1))
    hv = log_return.rolling(window=window).std() * np.sqrt(252)
    return hv

def get_earnings_dates(ticker_obj):
    """
    Attempts to fetch earnings dates to filter out trades near earnings.
    Note: yfinance history for earnings is limited.
    """
    try:
        earnings = ticker_obj.get_earnings_dates(limit=100)
        if earnings is not None:
            return pd.to_datetime(earnings.index).date
    except:
        pass
    return []

def run_backtest_mag7():
    print("[*] Starting Mag7 Strict Backtest (20 Years)...")
    
    # 1. Fetch QQQ data for macro filter
    qqq = yf.download("QQQ", period="20y")
    if isinstance(qqq.columns, pd.MultiIndex): qqq.columns = qqq.columns.get_level_values(0)
    qqq.index = qqq.index.tz_localize(None) # Normalize TZ
    qqq['qqq_change'] = qqq['Close'].pct_change()
    
    all_trades = []
    
    for ticker in MAG7:
        print(f"[*] Processing {ticker}...")
        t_obj = yf.Ticker(ticker)
        df = t_obj.history(period="20y")
        if df.empty: continue
        
        # Flatten columns
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        df.index = df.index.tz_localize(None) # Normalize TZ
        
        # Calculate Indicators
        df['pct_change'] = df['Close'].pct_change()
        df['SMA_50'] = df['Close'].rolling(window=50).mean()
        df['HV'] = calculate_hv(df['Close'])
        df['HV_Avg'] = df['HV'].rolling(window=100).mean()
        
        # Merge QQQ change
        df = df.join(qqq['qqq_change'], how='left')
        
        # Earnings Filter (heuristic if data missing)
        earnings_dates = get_earnings_dates(t_obj)
        
        # Strategy Logic
        # 1. Drop > 4%
        # 2. Price < SMA 50
        # 3. HV > 1.3 * HV_Avg
        # 4. QQQ Drop > 0.5%
        
        condition = (df['pct_change'] < -0.04) & \
                    (df['Close'] < df['SMA_50']) & \
                    (df['HV'] > 1.3 * df['HV_Avg']) & \
                    (df['qqq_change'] < -0.005)
        
        triggers = df[condition].copy()
        
        for entry_date, entry_row in triggers.iterrows():
            # Earnings check
            is_earnings = False
            if len(earnings_dates) > 0:
                # Check if entry_date is on or 1 day after earnings
                d = entry_date.date()
                if d in earnings_dates or (d - timedelta(days=1)) in earnings_dates:
                    is_earnings = True
            
            if is_earnings: continue
            
            entry_price = entry_row['Close']
            strike_price = entry_price * 0.93
            
            # Future data for exit
            future_data = df[df.index > entry_date].copy()
            if future_data.empty: continue
            
            tp_window_end = entry_date + timedelta(days=10)
            exit_date_target = entry_date + timedelta(days=45)
            
            won_early = False
            tp_data = future_data[future_data.index <= tp_window_end]
            if not tp_data.empty:
                tp_hits = tp_data[tp_data['High'] >= entry_price * 1.02]
                if not tp_hits.empty:
                    won_early = True
                    duration = (tp_hits.index[0] - entry_date).days
                    all_trades.append({'ticker': ticker, 'type': 'WIN_TP', 'duration': duration, 'result': 1})
            
            if not won_early:
                final_data = future_data[future_data.index <= exit_date_target]
                if not final_data.empty:
                    last_price = final_data.iloc[-1]['Close']
                    last_date = final_data.index[-1]
                    res = 1 if last_price > strike_price else 0
                    type_str = 'WIN_EXP' if res == 1 else 'LOSS_EXP'
                    all_trades.append({'ticker': ticker, 'type': type_str, 'duration': (last_date - entry_date).days, 'result': res})

    return pd.DataFrame(all_trades)

def print_hebrew_report(trades_df):
    if trades_df.empty:
        print("\n[!] לא נמצאו עסקאות העונות על התנאים המחמירים.")
        return

    total = len(trades_df)
    wins = trades_df[trades_df['result'] == 1]
    losses = trades_df[trades_df['result'] == 0]
    win_rate = (len(wins) / total) * 100
    
    print("\n" + "="*60)
    print("         דוח בדיקה אסטרטגית: Mag7 STRICT MODEL")
    print("="*60)
    print(f"סה\"כ עסקאות שנוצרו:          {total}")
    print(f"ניצחונות:                     {len(wins)} ({len(wins)/total:.1%})")
    print(f"הפסדים:                       {len(losses)} ({len(losses)/total:.1%})")
    print("-" * 60)
    print(f"אחוז הצלחה כולל (Win Rate):   {win_rate:.2f}%")
    print(f"זמן החזקה ממוצע לניצחון:      {wins['duration'].mean():.1f} ימים")
    print("-" * 60)
    
    print("פירוט לפי מניה:")
    ticker_stats = trades_df.groupby('ticker')['result'].agg(['count', 'mean'])
    for ticker, row in ticker_stats.iterrows():
        print(f" - {ticker:5}: עסקאות: {int(row['count']):3} | אחוז הצלחה: {row['mean']*100:6.2f}%")
    
    print("="*60 + "\n")

if __name__ == "__main__":
    results = run_backtest_mag7()
    print_hebrew_report(results)
