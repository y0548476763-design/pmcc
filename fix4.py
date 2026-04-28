import re
import os

def clean_json_calls():
    # bot_tab.py
    with open('ui/bot_tab.py', 'r', encoding='utf-8') as f:
        c = f.read()
    c = c.replace('data = r.json()\n', '')
    with open('ui/bot_tab.py', 'w', encoding='utf-8') as f:
        f.write(c)

    # earnings_tab.py
    with open('ui/earnings_tab.py', 'r', encoding='utf-8') as f:
        c = f.read()
    c = c.replace('rj = resp.json()', 'rj = resp')
    # Also: close_payload, timeout=60).json()
    c = re.sub(r'json=close_payload, timeout=60\)\.json\(\)', 'json=close_payload, timeout=60)', c)
    # Also: orders = r.json().get("orders", [])
    c = c.replace('orders = r.json().get("orders", [])', 'orders = r.get("orders", []) if isinstance(r, dict) else []')
    with open('ui/earnings_tab.py', 'w', encoding='utf-8') as f:
        f.write(c)

    # roll_tab.py
    with open('ui/roll_tab.py', 'r', encoding='utf-8') as f:
        c = f.read()
    c = c.replace('rj = resp.json()', 'rj = resp')
    c = c.replace('orders = r.json().get("orders", [])', 'orders = r.get("orders", []) if isinstance(r, dict) else []')
    with open('ui/roll_tab.py', 'w', encoding='utf-8') as f:
        f.write(c)

    # short_calls_tab.py
    with open('ui/short_calls_tab.py', 'r', encoding='utf-8') as f:
        c = f.read()
    c = c.replace('data = r.json()', 'data = r')
    c = c.replace('r.json().get', 'r.get')
    c = c.replace('r_sell.json().get', 'r_sell.get')
    c = c.replace('search_data = r_search.json()', 'search_data = r_search')
    with open('ui/short_calls_tab.py', 'w', encoding='utf-8') as f:
        f.write(c)

clean_json_calls()
print("Cleaned .json() calls")
