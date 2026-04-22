import sys
sys.path.append('c:/Users/User/Desktop/pmcc1')
from tws_client import TWSClient

t = TWSClient()

def test_dte(min_dte):
    print(f'\n=== TEST: min_dte={min_dte} ===')
    res = t.get_leaps_options('MSFT', min_dte=min_dte, target_delta=0.80)
    if not res:
        print('  FAIL: no results returned')
        return False
    for r in res:
        print(f'  Expiry: {r["expiry"]}  DTE: {r["dte"]}  Strike: {r["strike"]}  Delta: {r["delta"]}  Mid: ${r["mid"]}  Source: {r["source"]}')
    first = res[0]
    if first['dte'] >= min_dte:
        print(f'  PASS: dte {first["dte"]} >= {min_dte}')
        return True
    else:
        print(f'  FAIL: dte {first["dte"]} < {min_dte}')
        return False

ok1 = test_dte(540)
ok2 = test_dte(650)

print('\n' + ('ALL TESTS PASSED' if ok1 and ok2 else 'SOME TESTS FAILED'))
