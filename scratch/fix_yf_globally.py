import os
import ssl

files = [
    'ui/earnings_tab.py',
    'ui/portfolio_tab.py',
    'ui/cash_tab.py',
    'data_feed.py'
]

ssl_patch = """
import ssl
ssl._create_default_https_context = ssl._create_unverified_context
"""

for path in files:
    if not os.path.exists(path): continue
    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
    
    # Add SSL patch if not there
    if 'ssl._create_default_https_context' not in content:
        content = "import ssl\nssl._create_default_https_context = ssl._create_unverified_context\n" + content
    
    # Remove session from Ticker calls
    content = content.replace('session=yf_session', '')
    content = content.replace('session=session', '')
    content = content.replace('(ticker, )', '(ticker)')
    content = content.replace('(ticker,)', '(ticker)')
    content = content.replace('yf.Ticker(symbol, )', 'yf.Ticker(symbol)')
    content = content.replace('yf.Ticker("^VIX", )', 'yf.Ticker("^VIX")')
    
    # Fix potential trailing commas
    import re
    content = re.sub(r'yf\.Ticker\(([^,]+),\s*session=[^)]+\)', r'yf.Ticker(\1)', content)
    
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"Fixed {path}")
