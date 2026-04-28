import re
import textwrap

with open('ui/earnings_tab.py', 'r', encoding='utf-8') as f:
    c = f.read()

def repl(m):
    return 'st.markdown(f"""\n' + textwrap.dedent(m.group(1)) + '""", unsafe_allow_html=True)'

c = re.sub(r'st\.markdown\(f\"\"\"\n(.*?)(\"\"\", unsafe_allow_html=True\))', repl, c, flags=re.DOTALL)

with open('ui/earnings_tab.py', 'w', encoding='utf-8') as f:
    f.write(c)

# We should also fix roll_tab and short_calls_tab if they have the same issue.
for fname in ['ui/roll_tab.py', 'ui/short_calls_tab.py', 'ui/bot_tab.py', 'ui/cash_tab.py', 'app.py']:
    try:
        with open(fname, 'r', encoding='utf-8') as f:
            c = f.read()
        c = re.sub(r'st\.markdown\(f\"\"\"\n(.*?)(\"\"\", unsafe_allow_html=True\))', repl, c, flags=re.DOTALL)
        # Also fix regular strings:
        def repl_reg(m):
            return 'st.markdown("""\n' + textwrap.dedent(m.group(1)) + '""", unsafe_allow_html=True)'
        c = re.sub(r'st\.markdown\(\"\"\"\n(.*?)(\"\"\", unsafe_allow_html=True\))', repl_reg, c, flags=re.DOTALL)
        with open(fname, 'w', encoding='utf-8') as f:
            f.write(c)
    except: pass

print('Fixed HTML indentation globally')
