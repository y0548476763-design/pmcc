import re

for fname in ['ui/earnings_tab.py', 'ui/roll_tab.py', 'ui/short_calls_tab.py', 'ui/bot_tab.py', 'app.py']:
    try:
        with open(fname, 'r', encoding='utf-8') as f:
            c = f.read()

        def strip_all_indent_f(m):
            lines = m.group(1).split('\n')
            stripped = '\n'.join(line.lstrip() for line in lines)
            return 'st.markdown(f"""' + stripped + '""", unsafe_allow_html=True)'

        def strip_all_indent_reg(m):
            lines = m.group(1).split('\n')
            stripped = '\n'.join(line.lstrip() for line in lines)
            return 'st.markdown("""' + stripped + '""", unsafe_allow_html=True)'

        c = re.sub(r'st\.markdown\(f\"\"\"(.*?)\"\"\",\s*unsafe_allow_html=True\)', strip_all_indent_f, c, flags=re.DOTALL)
        c = re.sub(r'st\.markdown\(\"\"\"(.*?)\"\"\",\s*unsafe_allow_html=True\)', strip_all_indent_reg, c, flags=re.DOTALL)

        with open(fname, 'w', encoding='utf-8') as f:
            f.write(c)
    except Exception as e:
        pass

print('Fixed HTML indentation aggressively')
