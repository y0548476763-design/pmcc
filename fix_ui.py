import sys
import re

def fix_roll_tab():
    content = open('ui/roll_tab.py', 'r', encoding='utf-8').read()
    
    # Send combo
    old_combo = """    import requests
    try:
        resp = requests.post(f"{config.IBKR_API_URL}/order/combo", json=req, timeout=60)
        return resp.json()
    except Exception as e:
        return {"ok": False, "error": str(e)}"""
    new_combo = """    return api_ibkr.place_combo(ticker, legs, limit_price, False, esc_step, esc_wait_secs)"""
    content = content.replace(old_combo, new_combo)
    
    open('ui/roll_tab.py', 'w', encoding='utf-8').write(content)

def fix_short_calls_tab():
    content = open('ui/short_calls_tab.py', 'r', encoding='utf-8').read()
    
    # Place order
    content = re.sub(r'r = requests\.post\(f"\{IBKR\}/order/place", json=payload, timeout=10\)',
                     r'r = api_ibkr.place_order(payload["ticker"], payload["strike"], payload["expiry"], payload["right"], payload["action"], payload["qty"], payload.get("limit_price"))', content)
                     
    content = re.sub(r'r_sell = requests\.post\(f"\{IBKR\}/order/place", json=sell_payload, timeout=15\)',
                     r'r_sell = api_ibkr.place_order(sell_payload["ticker"], sell_payload["strike"], sell_payload["expiry"], sell_payload["right"], sell_payload["action"], sell_payload["qty"], sell_payload.get("limit_price"))', content)

    content = re.sub(r'requests\.post\(f"\{IBKR\}/order/place", json=tp_payload, timeout=10\)',
                     r'api_ibkr.place_order(tp_payload["ticker"], tp_payload["strike"], tp_payload["expiry"], tp_payload["right"], tp_payload["action"], tp_payload["qty"], tp_payload.get("limit_price"), tp_payload.get("order_type", "LMT"))', content)

    # Place combo
    content = re.sub(r'r_combo = requests\.post\(f"\{IBKR\}/order/combo", json=combo_payload, timeout=20\)',
                     r'r_combo = api_ibkr.place_combo(combo_payload["ticker"], combo_payload["legs"], combo_payload["limit_price"], combo_payload["use_market"], combo_payload["escalation_step_pct"], combo_payload["escalation_wait_secs"])', content)

    open('ui/short_calls_tab.py', 'w', encoding='utf-8').write(content)

def fix_earnings_tab():
    content = open('ui/earnings_tab.py', 'r', encoding='utf-8').read()
    
    content = re.sub(r'resp = requests\.post\(f"\{IBKR\}/order/combo",.*?json=payload, timeout=60\)',
                     r'resp = api_ibkr.place_combo(payload["ticker"], payload["legs"], payload["limit_price"], payload["use_market"], payload["escalation_step_pct"], payload["escalation_wait_secs"])', content, flags=re.DOTALL)
                     
    content = re.sub(r'cr = requests\.post\(f"\{IBKR\}/order/combo",.*?json=payload, timeout=60\)',
                     r'cr = api_ibkr.place_combo(payload["ticker"], payload["legs"], payload["limit_price"], payload["use_market"], payload["escalation_step_pct"], payload["escalation_wait_secs"])', content, flags=re.DOTALL)
                     
    content = re.sub(r'r = requests\.get\(f"\{IBKR\}/api/orders/active", timeout=5\)',
                     r'r = api_ibkr.get_active_orders()', content)
                     
    open('ui/earnings_tab.py', 'w', encoding='utf-8').write(content)

fix_roll_tab()
fix_short_calls_tab()
fix_earnings_tab()
print('Done fixing UI tabs!')
