
import sys, time, logging
sys.path.insert(0, r'c:\Users\User\Desktop\pmcc1')
import ibkr_auto_bot

logging.basicConfig(level=logging.INFO)
print('Running one cycle of the Auto Bot...')
try:
    ibkr_auto_bot.run_bot_cycle(mode='DEMO')
except Exception as e:
    print('Error during sequence:', e)
print('Cycle complete.')

