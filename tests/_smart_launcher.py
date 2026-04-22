import os, sys, subprocess, time, configparser, pathlib, socket
import threading

def is_port_open(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1.0)
        return s.connect_ex(('127.0.0.1', port)) == 0

print("=========================================================")
print("    PMCC NextOffice v3.0 — Smart Auto-Start System")
print("=========================================================")
print()
print("Select Mode:")
print("[1] PAPER TRADING (Demo) — מומלץ לבדיקות")
print("[2] LIVE TRADING (Real Money) — כסף אמיתי")
print("[3] START DASHBOARD ONLY — הצג ממשק בלבד (אם IBC כבר פועל)")
print()

choice = input("Enter 1, 2 or 3: ").strip()

if choice == "3":
    print("\n[+] Starting PMCC Auto-Bot...")
    subprocess.Popen(f"start cmd /k color 09 ^& python ibkr_auto_bot.py", shell=True, cwd=r"c:\Users\User\Desktop\pmcc1")
    print("[+] Starting Quant Dashboard...")
    subprocess.Popen("start cmd /k color 0B ^& streamlit run app.py --server.port 8501", shell=True, cwd=r"c:\Users\User\Desktop\pmcc1")
    time.sleep(3)
    os.system("start http://localhost:8501")
    sys.exit()

mode = "paper" if choice == "1" else "live"
py_mode = "" if mode == "paper" else "--live"
target_port = 4002 if mode == "paper" else 7496

# Save session config for the Dashboard to pick up
import json
with open(r"c:\Users\User\Desktop\pmcc1\session_config.json", "w") as f:
    json.dump({"mode": "DEMO" if mode == "paper" else "LIVE", "timestamp": time.time()}, f)

print(f"\n[+] Configuring IBC for {mode.upper()} mode...")

# Update config.ini (both local IBC/config.ini and Documents/IBC/config.ini if it exists)
ini_paths = [
    pathlib.Path(r"c:\Users\User\Desktop\pmcc1\tests\IBC\config.ini"),
    pathlib.Path(os.path.expanduser(r"~\Documents\IBC\config.ini"))
]

for ini_path in ini_paths:
    if ini_path.exists():
        content = ini_path.read_text(encoding="utf-8")
        lines = []
        for l in content.splitlines():
            if l.startswith("TradingMode="):
                lines.append(f"TradingMode={mode}")
            else:
                lines.append(l)
        ini_path.write_text("\n".join(lines), encoding="utf-8")
        print(f"    ✓ Updated {ini_path.name}")

print("\n[+] Starting IB Gateway via IBC...")
ibc_bat = r"c:\Users\User\Desktop\pmcc1\tests\IBC\StartGateway.bat"
# Use cmd /c so it detaches properly without /MIN hiding the UI
subprocess.Popen(["cmd.exe", "/c", "start", "IB Gateway", ibc_bat], cwd=r"c:\Users\User\Desktop\pmcc1\tests\IBC")

print(f"\n=========================================================")
print(f" ⏳ ממתין לחיבור Gateway בפורט {target_port}...")
print(f" 📱 אנא הכנס שם משתמש (אם חסר) ואשר את ההתחברות דרך ה-SMS")
print(f"=========================================================")

# Socket check loop
wait_time = 0
timeout = 300 # 5 minutes max
connected = False

while wait_time < timeout:
    if is_port_open(target_port):
        connected = True
        break
    time.sleep(2)
    wait_time += 2
    if wait_time % 10 == 0:
        print(f"    ...עדיין ממתין לחיבור (עברו {wait_time} שניות)...")

if not connected:
    print("\n❌ שגיאה: Gateway לא התחבר תוך 5 דקות. המערכת עוצרת.")
    input("לחץ Enter ליציאה...")
    sys.exit(1)

print("\n✅ Gateway מחובר ופעיל בהצלחה!")
print("[+] Starting PMCC Auto-Bot...")
subprocess.Popen(f"start cmd /k color 09 ^& python ibkr_auto_bot.py {py_mode}", shell=True, cwd=r"c:\Users\User\Desktop\pmcc1")

print("[+] Starting Quant Dashboard...")
subprocess.Popen("start cmd /k color 0B ^& streamlit run app.py --server.port 8501", shell=True, cwd=r"c:\Users\User\Desktop\pmcc1")

print("\n🚀 המערכת מוכנה! הממשק נפתח בדפדפן...")
time.sleep(4)
os.system("start http://localhost:8501")
print("You can close this window now.")
