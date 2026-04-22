import sys, time, subprocess, pathlib
sys.path.insert(0, r'c:\Users\User\Desktop\pmcc1')
from tws_client import get_client

print('Starting IB Gateway via IBC...')
ibc_bat = r'c:\Users\User\Desktop\pmcc1\tests\IBC\StartGateway.bat'
print('> cmd.exe /c ' + ibc_bat)
gw = subprocess.Popen(['cmd.exe', '/c', ibc_bat], cwd=r'c:\Users\User\Desktop\pmcc1\tests\IBC')

print('Waiting 60 seconds to ensure Gateway UI has time to login and load...')
time.sleep(60)

client = get_client()
print('Connecting to checking Gateway on port 4002...')
client.connect(mode='DEMO')

if client.connected:
    print('\n[SUCCESS] Connected to Gateway!')
    pos = client.get_positions()
    leaps = [p for p in pos if p.get('type') == 'LEAPS']
    shorts = [p for p in pos if p.get('type') == 'SHORT_CALL']
    print(f'Detected {len(leaps)} LEAPS and {len(shorts)} Short Calls.')
    
    print('\nRunning 1 BOT CYCLE...')
    try:
        import ibkr_auto_bot
        ibkr_auto_bot.run_bot_cycle(client)
    except Exception as e:
        print('Bot cycle error:', e)
    
    client.disconnect()
else:
    print('\n[FAILED] Could not connect to port 4002.')

print('Terminating Gateway process tree...')
subprocess.Popen('taskkill /F /T /IM ibgateway.exe', shell=True)
subprocess.Popen('taskkill /F /T /IM java.exe', shell=True)
