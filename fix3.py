import re

def fix_bot_tab():
    content = open('ui/bot_tab.py', 'r', encoding='utf-8').read()
    content = re.sub(r'r = requests\.get\(f"\{IBKR\}/connect/\{mode_val\}", timeout=12\)',
                     r'r = {"status_code": 200}; data = api_ibkr.connect(mode_val)', content)
                     
    content = re.sub(r'p = requests\.get\(f"\{IBKR\}/portfolio", timeout=5\)\.json\(\)',
                     r'p = api_ibkr.get_positions()', content)
                     
    content = re.sub(r'requests\.get\(f"\{IBKR\}/connect/NONE", timeout=3\)',
                     r'api_ibkr.connect("NONE")', content)

    open('ui/bot_tab.py', 'w', encoding='utf-8').write(content)

fix_bot_tab()
print('Fixed bot tab')
