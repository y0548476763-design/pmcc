import os

path = 'ui/cash_tab.py'
with open(path, 'r', encoding='utf-8', errors='ignore') as f:
    lines = f.readlines()

new_lines = []
for line in lines:
    if 'import yfinance as yf' in line:
        new_lines.append('        import requests\n')
        new_lines.append('        import yfinance as yf\n')
        new_lines.append('        s = requests.Session()\n')
        new_lines.append('        s.verify = False\n')
    elif 't = yf.Ticker("^VIX")' in line:
        new_lines.append('        t = yf.Ticker("^VIX", session=s)\n')
    else:
        new_lines.append(line)

with open(path, 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print("Done")
