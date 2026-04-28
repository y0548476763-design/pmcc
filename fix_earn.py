import re

with open('ui/earnings_tab.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix 1: session_state mutation
old_state = """                st.session_state["earn_strikes"] = strikes
                st.session_state["earn_mult"]    = multiplier
                st.session_state["earn_wing"]    = wing_width
                st.session_state["earn_qty"]     = qty"""

new_state = """                st.session_state["earn_strikes"] = strikes
                st.session_state["saved_earn_mult"]    = multiplier
                st.session_state["saved_earn_wing"]    = wing_width
                st.session_state["saved_earn_qty"]     = qty"""
content = content.replace(old_state, new_state)

old_get = """    saved_mult = st.session_state.get("earn_mult", 1.15)
    saved_wing = st.session_state.get("earn_wing", 10.0)"""
new_get = """    saved_mult = st.session_state.get("saved_earn_mult", 1.15)
    saved_wing = st.session_state.get("saved_earn_wing", 10.0)"""
content = content.replace(old_get, new_get)

# Also fix the qty below
old_qty = """        saved_qty    = st.session_state.get("earn_qty", qty)"""
new_qty = """        saved_qty    = st.session_state.get("saved_earn_qty", qty)"""
content = content.replace(old_qty, new_qty)

# Fix 2: HTML tags split across lines (causes Markdown parser to mangle them)
content = re.sub(r'0\.35\);\s*border-radius:', r'0.35);border-radius:', content)
content = re.sub(r'0\.5\);\s*border-radius:', r'0.5);border-radius:', content)
content = re.sub(r'0\.55\);\s*border-radius:', r'0.55);border-radius:', content)
content = re.sub(r'0\.6\);\s*border-radius:', r'0.6);border-radius:', content)

with open('ui/earnings_tab.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('Fixed earnings_tab')
