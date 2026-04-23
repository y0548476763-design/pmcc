import os, sys, subprocess, time, pathlib, socket, json

def is_port_open(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1.0)
        return s.connect_ex(('127.0.0.1', port)) == 0

def wait_for_port(port, label, timeout=300):
    waited = 0
    while waited < timeout:
        if is_port_open(port):
            print(f"    ✅ {label} מחובר בפורט {port}")
            return True
        time.sleep(2); waited += 2
        if waited % 10 == 0:
            print(f"    ...ממתין ל-{label} (עברו {waited}s)...")
    print(f"    ❌ {label} לא הגיב תוך {timeout}s")
    return False

BASE = r"c:\Users\User\Desktop\pmcc1"

print("=========================================================")
print("    PMCC NextOffice v3.1 — Full Auto-Start System")
print("=========================================================")
print()
print("Select Mode:")
print("[1] PAPER TRADING (Demo) — מומלץ לבדיקות")
print("[2] LIVE TRADING (Real Money) — כסף אמיתי")
print("[3] START SERVICES ONLY — ללא Gateway (אם IBC כבר פועל)")
print()

choice = input("Enter 1, 2 or 3: ").strip()

mode = "paper" if choice == "1" else "live"
py_mode = "" if mode == "paper" else "--live"
target_port = 4002 if mode == "paper" else 7496

# ── Save session config ────────────────────────────────────────────────────
with open(os.path.join(BASE, "session_config.json"), "w") as f:
    json.dump({"mode": "DEMO" if mode == "paper" else "LIVE",
               "timestamp": time.time()}, f)

# ── Start IBC Gateway (skip in mode 3) ────────────────────────────────────
if choice != "3":
    # Update config.ini in both locations
    ini_paths = [
        pathlib.Path(BASE, "tests", "IBC", "config.ini"),
        pathlib.Path(os.path.expanduser(r"~\Documents\IBC\config.ini")),
    ]
    for ini_path in ini_paths:
        if ini_path.exists():
            lines = []
            for l in ini_path.read_text(encoding="utf-8").splitlines():
                lines.append(f"TradingMode={mode}" if l.startswith("TradingMode=") else l)
            ini_path.write_text("\n".join(lines), encoding="utf-8")
            print(f"    ✓ Updated {ini_path.name}")

    print("\n[1/4] Starting IB Gateway via IBC...")
    ibc_bat = os.path.join(BASE, "tests", "IBC", "StartGateway.bat")
    subprocess.Popen(["cmd.exe", "/c", "start", "IB Gateway", ibc_bat],
                     cwd=os.path.join(BASE, "tests", "IBC"))

    print(f"\n⏳ ממתין לחיבור Gateway בפורט {target_port}...")
    print(f"📱 אנא הכנס שם משתמש (אם חסר) ואשר התחברות דרך ה-SMS\n")

    if not wait_for_port(target_port, "IB Gateway", timeout=300):
        print("❌ Gateway לא התחבר. המערכת עוצרת.")
        input("לחץ Enter ליציאה...")
        sys.exit(1)
else:
    print("\n[SKIP] IBC Gateway — הפעלה ישירה של שירותים")

# ── Start Yahoo API server (port 8001) ────────────────────────────────────
print("\n[2/4] Starting Yahoo API server on port 8001...")
if is_port_open(8001):
    print("    ℹ️  Yahoo API כבר פועל על פורט 8001")
else:
    subprocess.Popen(
        "start \"PMCC Yahoo API\" cmd /k \"color 0A & python -m uvicorn api_yahoo:app --port 8001\"",
        shell=True, cwd=BASE)
    time.sleep(2)
    if wait_for_port(8001, "Yahoo API", timeout=20):
        pass
    else:
        print("    ⚠️  Yahoo API לא הגיב — ממשיך בכל מקרה")

# ── Start IBKR API server (port 8002) ─────────────────────────────────────
print("\n[3/4] Starting IBKR API server on port 8002...")
if is_port_open(8002):
    print("    ℹ️  IBKR API כבר פועל על פורט 8002")
else:
    subprocess.Popen(
        "start \"PMCC IBKR API\" cmd /k \"color 0B & python -m uvicorn api_ibkr:app --port 8002\"",
        shell=True, cwd=BASE)
    time.sleep(2)
    if wait_for_port(8002, "IBKR API", timeout=20):
        pass
    else:
        print("    ⚠️  IBKR API לא הגיב — ממשיך בכל מקרה")

# ── Start Bot + Dashboard ──────────────────────────────────────────────────
print("\n[4/4] Starting Bot + Dashboard...")
subprocess.Popen(
    f"start \"PMCC Bot\" cmd /k \"color 09 & python ibkr_auto_bot.py {py_mode}\"",
    shell=True, cwd=BASE)
time.sleep(1)
subprocess.Popen(
    "start \"PMCC Dashboard\" cmd /k \"color 0E & streamlit run app.py --server.port 8501\"",
    shell=True, cwd=BASE)

print("\n🚀 כל השירותים הופעלו! הממשק נפתח בדפדפן...")
time.sleep(4)
os.system("start http://localhost:8501")
print("You can close this window now.")
