import sys, time, logging
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime
import config
from tws_client import get_client
from quant_engine import get_engine
import settings_manager
import order_manager

# --- Logging Configuration ---
file_handler = TimedRotatingFileHandler(config.LOG_PATH, when='midnight', backupCount=3, encoding='utf-8')
logging.basicConfig(level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[file_handler, logging.StreamHandler()])
log = logging.getLogger('ibkr_bot')

DEMO_MODE = '--live' not in sys.argv

def is_market_hours():
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo('America/New_York'))
    if now.weekday() >= 5: return False
    o = now.replace(hour=9,minute=30,second=0,microsecond=0)
    c = now.replace(hour=16,minute=0,second=0,microsecond=0)
    return o <= now <= c

def get_dte(expiry_str):
    try:
        exp = datetime.strptime(expiry_str.replace('-',''),'%Y%m%d')
        return max(0,(exp.date()-datetime.utcnow().date()).days)
    except: return 999

def _handle_leaps_rolls(client, positions):
    """Detects and executes automated rolls for LEAPS contracts < 360 DTE."""
    bot_active = settings_manager.get_bot_active()
    leaps = [p for p in positions if p.get('type') == 'LEAPS']
    
    for lp in leaps:
        ticker = lp.get('ticker')
        dte = get_dte(lp.get('expiry', '20990101'))
        
        if dte < config.LEAPS_ROLL_DTE: # 360 days
            log.info('[%s] 🔄 LEAPS DTE (%d) נמוך מ-%d. מאתר יעדים לגלגול...' % (ticker, dte, config.LEAPS_ROLL_DTE))
            targets = client.get_leaps_options(ticker, min_dte=540, target_delta=0.8)
            if not targets:
                log.warning('[%s] ⚠️ לא נמצאו חוזי LEAPS מתאימים לגלגול (540+ ימים, דלתא 0.8).' % ticker)
                continue
            
            target = targets[0] # Take best match
            log.info('[%s] 🎯 יעד גלגול נמצא: $%s %s (DTE: %d, Delta: %.2f)' % 
                     (ticker, target['strike'], target['expiry'], target['dte'], target['delta']))
            
            if not bot_active:
                log.warning('[%s] 🚫 הבוט כבוי - התראה בלבד: דרוש גלגול לליפס!' % ticker)
                continue
            
            # Execute Combo: SELL old, BUY new
            legs = [
                {'strike': lp['strike'], 'expiry': lp['expiry'], 'right': 'C', 'action': 'SELL'},
                {'strike': target['strike'], 'expiry': target['expiry'], 'right': 'C', 'action': 'BUY'}
            ]
            
            # Use mid price for initial submission
            initial_mid = target['mid'] - lp.get('current_price', 0)
            
            log.info('[%s] 🚀 שולח פקודת קומבו לגלגול (Escalation מופעל)...' % ticker)
            om = order_manager.get_manager()
            om.submit_order(
                ticker=ticker, right='C', strike=target['strike'], expiry=target['expiry'],
                action='BUY', qty=abs(lp['qty']), limit_price=initial_mid,
                escalation_step_pct=config.ESCALATION_STEP_PCT,
                escalation_wait_mins=config.ESCALATION_WAIT_MINUTES,
                is_combo=True, legs=legs
            )

def _open_new_short(client, ticker, positions):
    """Analyzes and opens a new short call as a hedge for a LEAPS."""
    bot_active = settings_manager.get_bot_active()
    try:
        try:
            sig = get_engine().analyse_ticker(ticker).signal
        except Exception as e:
            log.error('[%s] Engine error: %s' % (ticker, e))
            sig = 'NO_TRADE'
        
        if sig == 'NO_TRADE':
            log.info('[%s] ❄️ הקפאה: איתות NO_TRADE התקבל מהמנוע. מדלג על פתיחת שורט.' % ticker)
            return
            
        td = config.DELTA_TARGETS.get(sig, 0.10)
        chain = client.get_option_chain(ticker=ticker,right='C',min_dte=30,max_dte=55,target_delta=td)
        if not chain:
            log.warning('[%s] ⚠️ לא נמצא שרשרת אופציות מתאימה (DTE 30-55).' % ticker)
            return
            
        lps = [p for p in positions if p.get('ticker')==ticker and p.get('type')=='LEAPS']
        if not lps:
            log.warning('[%s] ⚠️ לא נמצאו חוזי LEAPS לגיבוי. לא פותח שורט.' % ticker)
            return

        # Determine current underlying price
        try:
            import yfinance as yf
            underlying_px = float(yf.Ticker(ticker).fast_info.last_price or 0)
        except Exception:
            underlying_px = float(chain[0].get('mid', 0) * 1.05) if chain else 0

        # Calculate breakeven (min safe strike for short call)
        min_safe_list = []
        for lp in lps:
            strike_val = float(lp.get('strike', 0))
            cb_raw     = float(lp.get('cost_basis', 0))
            cb_per_share = cb_raw / 100.0 if cb_raw > 500 else cb_raw
            breakeven    = strike_val + cb_per_share
            min_safe_list.append(breakeven)

        min_safe = max(min_safe_list) if min_safe_list else 0.0
        cand = next((o for o in chain if float(o.get('strike', 0)) >= min_safe), None)
        
        if not cand:
            cand = max(chain, key=lambda o: float(o.get('strike', 0)), default=None)
            if cand:
                log.warning('[%s] ⚠️ אין סטרייק מעל %.1f. משתמש בסטרייק הגבוה ביותר: %.1f' % (
                    ticker, min_safe, float(cand.get('strike', 0))))
            else:
                return

        strike=cand['strike']; expiry=cand['expiry']; mid=float(cand.get('mid',0)); qty=len(lps)
        
        if mid<=0.01:
            log.warning('[%s] ⚠️ פרמיה נמוכה מדי (%.2f). מחכה להזדמנות טובה יותר.' % (ticker, mid))
            return
            
        if not bot_active:
            log.warning('[%s] 🚫 הבוט כבוי - התראה בלבד: ניתן לפתוח שורט קול (STO %dx $%s %s)' % (ticker,qty,strike,expiry))
            return
            
        log.info('[%s] 🚀 פותח שורט חדש: STO %dx $%s %s (Target Delta: %.2f)' % (ticker,qty,strike,expiry,td))
        client.place_adaptive_order(ticker=ticker,right='C',strike=strike,expiry=expiry,action='SELL',qty=qty,limit_price=mid,order_type='MKT')
        
    except Exception as e:
        log.error('[%s] Error in opening short: %s' % (ticker, e))

def _handle_leaps_expansion(client, positions):
    """Proactively expands the LEAPS fleet based on Case Tank Surplus & Hybrid SMA-Tranche rules."""
    bot_active = settings_manager.get_bot_active()
    
    # 1. Financial Health Check
    cash = client.cash_balance
    leaps = [p for p in positions if p.get('type') == 'LEAPS']
    total_leaps_mtm = sum(float(p.get('current_price', 0)) * abs(p.get('qty', 0)) * 100 for p in leaps)
    
    reserve_target = total_leaps_mtm * config.TANK_TARGET_PCT
    cash_surplus = cash - reserve_target
    
    log.info('[Expansion] 💰 מזומן: $%.0f, רצפת יעד: $%.0f, עודף להתרחבות: $%.0f' % (cash, reserve_target, cash_surplus))
    
    if cash_surplus <= 0:
        return

    # 2. Iterate Monitored Tickers
    for ticker in config.EXPANSION_TICKERS:
        try:
            res = get_engine().analyse_ticker(ticker)
            dd = res.drawdown_pct
            
            # Find best match for ONE new LEAPS
            targets = client.get_leaps_options(ticker, min_dte=config.LEAPS_DTE_TARGET, target_delta=config.LEAPS_DELTA_TARGET)
            if not targets:
                continue
            
            target = targets[0]
            cost_one = (target['mid'] * 1.015) * 100 # 1.5% slippage estimate
            
            do_entry = False
            reason = ""
            
            # HYBRID RULE 1: SMA 150 Survival (Pure Momentum)
            if dd >= config.CORRECTION_THRESHOLD: # NORMAL MARKET
                if res.cross_above_150:
                    if cash_surplus > cost_one:
                        do_entry = True
                        reason = "SMA 150 Cross (Normal Market)"
                else:
                    log.info('[%s] ⏳ ממתין לפריצת ממוצע 150 (DD: %.1f%%)' % (ticker, dd*100))
            
            # HYBRID RULE 2: Tiered Tranches (Crisis Management)
            else: # CORRECTION MARKET
                # Determine allowed surplus deployment
                # -30 DD -> 100% surplus, -20 DD -> 60% surplus, -10 DD -> 30% surplus
                allowed_mult = 1.0 if dd <= config.DIP_TRIGGER_B else (0.6 if dd <= config.DIP_TRIGGER_A else 0.3)
                if cash_surplus * allowed_mult >= cost_one:
                    do_entry = True
                    reason = "Tiered Tranche (DD: %.1f%%, Allowed: %.0f%%)" % (dd*100, allowed_mult*100)
                else:
                    log.info('[%s] 📊 תיקון בשוק (%.1f%%). עודף בטרנש לא מספיק לליפס חדש.' % (ticker, dd*100))

            if do_entry:
                log.info('[%s] 🚀 פריצת דרך! %s. קונה ליפס חדש: $%s %s' % (ticker, reason, target['strike'], target['expiry']))
                if not bot_active:
                    log.warning('[%s] 🚫 בוט כבוי - התראה בלבד: דרושה קניית התרחבות!' % ticker)
                    continue
                
                # Execute Market-Adaptive BUY
                client.place_adaptive_order(
                    ticker=ticker, right='C', strike=target['strike'], expiry=target['expiry'],
                    action='BUY', qty=1, limit_price=target['mid'], order_type='MKT'
                )
                # Deduct from surplus locally to prevent double-buying in same cycle
                cash_surplus -= cost_one

        except Exception as e:
            log.error('[%s] Error in expansion: %s' % (ticker, e))

def run_bot_cycle(client):
    """Main scanning cycle: 1. Rolls, 2. TP Management, 3. Risk Management, 4. New Shorts."""
    bot_active = settings_manager.get_bot_active()
    log.info('--- התחלת מחזור סריקה [%s] ---' % ("ACTIVE" if bot_active else "MONITOR ONLY"))
    
    if client.connected:
        pos = client.get_positions()
        log.info('[TWS] נטענו %d פוזיציות מחשבון %s' % (len(pos), client.account_id))
    else:
        pos = list(config.DEMO_POSITIONS)
        log.info('[DEMO] אין חיבור ל-TWS — משתמש ב-DEMO_POSITIONS')
        
    if not pos:
        log.warning('⚠️ לא נמצאו פוזיציות.')
        return

    # 1. Handle LEAPS Rolls FIRST (Maintenance)
    _handle_leaps_rolls(client, pos)

    # 2. Handle LEAPS Expansion (Growth)
    _handle_leaps_expansion(client, pos)

    # 3. Handle Short Call Management (Income)
    leaps = [p for p in pos if p.get('type')=='LEAPS']
    shorts = [p for p in pos if p.get('type')=='SHORT_CALL']
    
    for sc in shorts:
        ticker=sc.get('ticker',''); strike=sc.get('strike',0); expiry=sc.get('expiry','')
        delta=abs(float(sc.get('delta',0))); dte=get_dte(expiry)
        qty=abs(int(sc.get('qty',1))); cur_px=float(sc.get('current_price',0.01))
        cb_raw = float(sc.get('cost_basis', 0))
        entry_px = cb_raw / 100.0 if cb_raw > 5 else (cb_raw if cb_raw > 0 else cur_px)

        if dte <= 0:
            log.warning('[%s] ⚠️ פוזיציה שפגה (%s). מדלג.' % (ticker, expiry))
            continue

        # --- A. Proactive Take Profit ---
        active_trades = [t for t in client.ib.trades() if t.order.action == "BUY" and t.order.orderType == "LMT" and t.orderStatus.status not in ("Filled", "Cancelled", "Inactive")]
        has_tp_order = any(t.contract.symbol == ticker and t.contract.strike == strike and t.contract.right == 'C' for t in active_trades)
        
        if not has_tp_order and entry_px > 0:
            tp_price = max(0.01, round(entry_px * (1.0 - config.TAKE_PROFIT_PCT), 2))
            if bot_active:
                log.info('[%s] 📝 יצירת פקודת TP: BUY %dx @ $%.2f' % (ticker, qty, tp_price))
                client.place_adaptive_order(ticker=ticker, right='C', strike=strike, expiry=expiry, action='BUY', qty=qty, limit_price=tp_price, tif='GTC')
            else:
                log.info('[%s] 🤖 בוט כבוי: פקודת TP דרושה ב-$%.2f' % (ticker, tp_price))

        # --- B. Take Profit (Current Price) ---
        if entry_px > 0 and cur_px > 0:
            profit_pct = (entry_px - cur_px) / entry_px
            if profit_pct >= config.TAKE_PROFIT_PCT:
                log.info('[%s] 💰 TAKE PROFIT (%.0f%%) הושג!' % (ticker, profit_pct * 100))
                if bot_active:
                    client.place_adaptive_order(ticker=ticker, right='C', strike=strike, expiry=expiry, action='BUY', qty=qty, limit_price=cur_px * 1.05, order_type='MKT')
                    time.sleep(5)
                    _open_new_short(client, ticker, pos)
                else:
                    log.warning('[%s] 🚫 בוט כבוי: רווח יעד הושג!' % ticker)
                continue

        # --- C. Risk Management (DTE < 21 or Delta >= 0.40) ---
        reason = None
        if dte < config.TIME_STOP_DAYS:
            reason = 'DTE=%d' % dte
        elif delta >= config.ROLL_UP_THRESHOLD:
            reason = 'Delta=%.2f' % delta

        if reason:
            log.info('[%s] ✂️ סגירה יזומה: %s' % (ticker, reason))
            if bot_active:
                client.place_adaptive_order(ticker=ticker, right='C', strike=strike, expiry=expiry, action='BUY', qty=qty, limit_price=cur_px * 1.05, order_type='MKT')
                time.sleep(5)
                _open_new_short(client, ticker, pos)
            else:
                log.warning('[%s] 🚫 בוט כבוי: גלגול שורט נדרש (%s)!' % (ticker, reason))
    # 3. Handle Uncovered LEAPS
    open_orders = client.get_open_orders()
    pending_shorts = {o.get('ticker') for o in open_orders if o.get('action') == 'SELL' and o.get('sec_type') == 'OPT'}
    
    covered={s.get('ticker') for s in shorts}
    for lp in leaps:
        t=lp.get('ticker','')
        if t not in covered and t not in pending_shorts:
            log.info('[%s] 🔍 מחפש כיסוי שורט עבור LEAPS...' % t)
            if bot_active:
                _open_new_short(client, t, pos)
            else:
                log.info('[%s] 🤖 בוט כבוי: ניתן למכור שורט קול חדש.' % t)
    
    log.info('--- סיום מחזור סריקה ---')

def main():
    mode='DEMO' if DEMO_MODE else 'LIVE'
    port=config.TWS_PORT_DEMO if DEMO_MODE else config.TWS_PORT_LIVE
    log.info('🚀 PMCC Bot [%s] מופעל בפורט %d' % (mode,port))
    client=get_client(); client.connect(mode=mode)
    log.info('✅ הבוט מחובר ופועל. לחץ Ctrl+C לעצירה.')
    while True:
        try:
            if is_market_hours():
                run_bot_cycle(client)
            else:
                log.info('🌙 הבורסה סגורה. הבוט בהמתנה ל-5 דקות.')
                time.sleep(300)
                continue
            time.sleep(60)
        except KeyboardInterrupt:
            log.info('🛑 נעצר על ידי המשתמש.')
            break
        except Exception as e:
            log.error('❌ שגיאה: %s' % e)
            time.sleep(30)

if __name__ == '__main__': main()
