import os, sys, subprocess, time, configparser, pathlib

print("=========================================")
print("    PMCC AUTO-START SYSTEM via IBC")
print("=========================================")
print()
print("Select Mode:")
print("[1] PAPER TRADING (Demo)")
print("[2] LIVE TRADING (Real Money)")
print()

choice = input("Enter 1 or 2: ").strip()

mode = "paper" if choice == "1" else "live"
py_mode = "" if mode == "paper" else "--live"

print(f"\nConfiguring IBC for {mode.upper()} mode...")

# Update config.ini
ini_path = pathlib.Path(r"c:\Users\User\Desktop\pmcc1\tests\IBC\config.ini")
if ini_path.exists():
    content = ini_path.read_text(encoding="utf-8")
    lines = []
    for l in content.splitlines():
        if l.startswith("TradingMode="):
            lines.append(f"TradingMode={mode}")
        else:
            lines.append(l)
    ini_path.write_text("\n".join(lines), encoding="utf-8")
else:
    print(f"ERROR: {ini_path} not found!")

print("Starting IB Gateway via IBC...")
ibc_bat = r"c:\Users\User\Desktop\pmcc1\tests\IBC\StartGateway.bat"
subprocess.Popen(["cmd.exe", "/c", ibc_bat], cwd=r"c:\Users\User\Desktop\pmcc1\tests\IBC")

print("Waiting 3 minutes (180s) for Gateway to completely connect (login, 2FA, data farms)...")
time.sleep(180)

print("Starting PMCC Auto-Bot...")
subprocess.Popen(f"start cmd /k python ibkr_auto_bot.py {py_mode}", shell=True, cwd=r"c:\Users\User\Desktop\pmcc1")

print("Starting Quant Dashboard...")
subprocess.Popen("start cmd /k streamlit run app.py", shell=True, cwd=r"c:\Users\User\Desktop\pmcc1")

print("\nSystem started successfully! You can close this window.")
