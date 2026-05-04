import yfinance as yf
import pandas as pd
import numpy as np
from datetime import timedelta
import sys

def calculate_rsi_manual(series, period=2):
    """
    Calculates RSI manually (Wilder's Smoothing).
    """
    delta = series.diff()
    gain = (delta.where(delta > 0, 0))
    loss = (-delta.where(delta < 0, 0))
    
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    
    # Avoid division by zero
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def fetch_data(ticker="QQQ", years=20):
    """
    Fetches historical data for the ticker.
    Adds a buffer to ensure we have enough data for indicators at the start.
    """
    print(f"[*] Fetching {years} years of data for {ticker}...")
    end_date = pd.Timestamp.now()
    start_date = end_date - pd.DateOffset(years=years, months=1) # Extra month for indicator warmup
    
    df = yf.download(ticker, start=start_date, end=end_date)
    if df.empty:
        print("[!] Error: No data fetched. Check ticker or internet connection.")
        sys.exit(1)
    
    # Flatten columns if MultiIndex (yf sometimes returns multi-index)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
        
    return df

def calculate_indicators(df):
    """
    Calculates RSI(2) and Daily Returns.
    """
    print("[*] Calculating indicators (RSI 2, Daily Return)...")
    # Daily Return
    df['pct_change'] = df['Close'].pct_change()
    
    # RSI(2) manual
    df['RSI_2'] = calculate_rsi_manual(df['Close'], period=2)
    
    return df.dropna()

def run_backtest(df):
    """
    Simulates the Mean Reversion Put Spread strategy.
    """
    print("[*] Running backtest simulation...")
    trades = []
    
    # Strategy Rules:
    # 1. Entry: Close down > 1.25% OR RSI_2 < 10
    triggers = df[(df['pct_change'] < -0.0125) | (df['RSI_2'] < 10)].copy()
    
    for entry_date, entry_row in triggers.iterrows():
        entry_price = entry_row['Close']
        strike_price = entry_price * 0.93
        
        # Define windows
        tp_window_end = entry_date + timedelta(days=10)
        exit_date_target = entry_date + timedelta(days=45)
        
        # Look ahead data
        future_data = df[df.index > entry_date].copy()
        
        # Win Condition 1: Up 2% within 10 calendar days
        # We check the High of the day to see if it touched the target
        tp_data = future_data[future_data.index <= tp_window_end]
        
        won_early = False
        exit_day = None
        duration = 0
        
        if not tp_data.empty:
            # Check if any day's High reached entry * 1.02
            tp_hits = tp_data[tp_data['High'] >= entry_price * 1.02]
            if not tp_hits.empty:
                won_early = True
                exit_day = tp_hits.index[0]
                duration = (exit_day - entry_date).days
        
        if won_early:
            trades.append({
                'entry_date': entry_date,
                'type': 'WIN_TP',
                'duration': duration,
                'result': 1
            })
        else:
            # Win Condition 2: Hold to day 45, Price > Strike
            # Find the closest trading day to the 45-day target
            final_data = future_data[future_data.index <= exit_date_target]
            if not final_data.empty:
                last_day_available = final_data.index[-1]
                last_price = final_data.iloc[-1]['Close']
                
                # We only count it if we reached close enough to 45 days (e.g. at least 40)
                # To be robust, we just take the last day in the window
                if last_price > strike_price:
                    trades.append({
                        'entry_date': entry_date,
                        'type': 'WIN_EXP',
                        'duration': (last_day_available - entry_date).days,
                        'result': 1
                    })
                else:
                    trades.append({
                        'entry_date': entry_date,
                        'type': 'LOSS_EXP',
                        'duration': (last_day_available - entry_date).days,
                        'result': 0
                    })
            else:
                # Trade still active or insufficient data at end of series
                pass

    return pd.DataFrame(trades)

def print_report(trades_df):
    """
    Prints a beautiful summary report.
    """
    if trades_df.empty:
        print("\n[!] No trades were generated. Check trigger conditions.")
        return

    total_trades = len(trades_df)
    wins_df = trades_df[trades_df['result'] == 1]
    losses_df = trades_df[trades_df['result'] == 0]
    
    total_wins = len(wins_df)
    total_losses = len(losses_df)
    win_rate = (total_wins / total_trades) * 100
    
    avg_duration_wins = wins_df['duration'].mean()
    
    tp_wins = len(trades_df[trades_df['type'] == 'WIN_TP'])
    exp_wins = len(trades_df[trades_df['type'] == 'WIN_EXP'])

    print("\n" + "="*50)
    print("       MODEL A OPTIMIZED: QQQ MEAN REVERSION")
    print("="*50)
    print(f"Total Trades Generated (20Y):  {total_trades}")
    print(f"Total Wins:                    {total_wins} ({total_wins/total_trades:.1%})")
    print(f"  - Early Take Profit (10D):   {tp_wins}")
    print(f"  - Expiration Win (45D):      {exp_wins}")
    print(f"Total Losses:                  {total_losses} ({total_losses/total_trades:.1%})")
    print("-" * 50)
    print(f"OVERALL WIN RATE:              {win_rate:.2f}%")
    print(f"Avg Holding Time (Wins):       {avg_duration_wins:.1f} days")
    print("="*50 + "\n")

if __name__ == "__main__":
    try:
        data = fetch_data("QQQ", years=20)
        data = calculate_indicators(data)
        results = run_backtest(data)
        print_report(results)
    except Exception as e:
        print(f"\n[!] Critical Error: {e}")
