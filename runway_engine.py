from datetime import datetime
from typing import Dict, Any, List
import config

def compute_tank_levels(leaps_positions, ibkr_live=False):
    total = 0.0
    for p in leaps_positions:
        if p.get('type') != 'LEAPS': continue
        qty = abs(int(p.get('qty', 1)))
        cb = float(p.get('cost_basis', 0.0))
        # IBKR returns avgCost already as total-per-contract (already x100)
        # Demo/manual data uses per-share cost -> x100
        multiplier = 1 if ibkr_live else 100
        total += qty * cb * multiplier
    return {'total_entry_cost': round(total, 2),
            'blue_line':   round(total * config.TANK_TARGET_PCT, 2),
            'yellow_line': round(total * config.TANK_WARNING_PCT, 2),
            'red_line':    round(total * config.TANK_FLOOR_PCT, 2)}

def compute_runway(cash_usd, leaps_positions=None, n_contracts=9,
                   monthly_savings_usd=None, short_premium_monthly=0.0, ibkr_live=True):
    if monthly_savings_usd is None: monthly_savings_usd = config.MONTHLY_SAVINGS_USD
    if leaps_positions is None: leaps_positions = []
    lv = compute_tank_levels(leaps_positions, ibkr_live=ibkr_live)
    blue_line = lv['blue_line']; yellow_line = lv['yellow_line']; red_line = lv['red_line']
    n = max(n_contracts, len([p for p in leaps_positions if p.get('type')=='LEAPS']))
    monthly_roll_cost = (1500 * 2 * n) / 12
    net_burn = max(monthly_roll_cost - short_premium_monthly - monthly_savings_usd, 1.0)
    pct = (cash_usd / blue_line * 100) if blue_line > 0 else 0.0
    if cash_usd < red_line:
        status = 'RED'; action = 'DANGER: Tank below 15pct. Sell 1 LEAPS. No new shorts.'
    elif cash_usd < yellow_line:
        status = 'YELLOW'; action = 'WARNING: Tank below 20pct. Channel premiums to tank.'
    elif cash_usd < blue_line:
        status = 'GREEN'; action = 'HEALTHY: Normal operations. Sell short calls per delta rules.'
    else:
        status = 'BLUE'; action = 'SURPLUS: Above 30pct target. Consider 1 new LEAPS.'
    return {'cash_usd': cash_usd, 'n_contracts': n,
            'total_entry_cost': lv['total_entry_cost'],
            'blue_line': blue_line, 'yellow_line': yellow_line, 'red_line': red_line,
            'pct_of_target': round(pct,1), 'monthly_roll': round(monthly_roll_cost),
            'monthly_income': round(short_premium_monthly+monthly_savings_usd),
            'net_burn': round(net_burn), 'static_months': round(cash_usd/net_burn,1),
            'status': status, 'action': action,
            'timestamp': datetime.utcnow().isoformat()}

def get_win_rate():
    try:
        import db; df = db.get_trades_df()
        if df.empty: return 0.0
        s = df[(df['option_type']=='CALL')&(df['action']=='BUY')]
        w = s[s['fill_price'] < s.get('entry_price',s['fill_price'])]
        return len(w)/len(s)*100 if len(s)>0 else 0.0
    except: return 0.0

def get_ytd_premium():
    try:
        import db; df = db.get_trades_df()
        if df.empty: return 0.0
        y = str(datetime.utcnow().year)
        s = df[(df['option_type']=='CALL')&(df['action']=='SELL')&(df['timestamp'].str.startswith(y))]
        return (s['fill_price']*s['qty'].abs()*100).sum()
    except: return 0.0
