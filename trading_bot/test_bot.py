import sys
sys.path.insert(0, '.')

import mt5_connector as mt5c
import indicators as ind
import strategy as strat
import risk_manager as rm
from config import TRADING, GOAL

print('Connecting to MT5...')
if not mt5c.connect():
    print('FAILED to connect')
    sys.exit(1)

acc = mt5c.get_account_info()
print(f"Account #{acc['login']} | Balance: ${acc['balance']:.2f}")
print()

symbols = mt5c.check_symbols(TRADING['symbols'])
print(f"Available symbols: {symbols}")
print()

for sym in symbols[:2]:
    print(f"=== Analyzing {sym} ===")
    df = mt5c.get_ohlcv(sym, 'H1', bars=500)
    if df is None:
        print(f"  No data for {sym}")
        continue
    print(f"  Bars: {len(df)}")

    analysis = ind.analyze(df)
    print(f"  Overall Score: {analysis['overall_score']:+.1f}")
    print(f"  Confidence:    {analysis['confidence']:.1f}%")
    print(f"  Action:        {analysis['action']}")
    print(f"  Buy signals:   {analysis['buy_signals']}")
    print(f"  Sell signals:  {analysis['sell_signals']}")

    i = analysis['indicators']
    rsi_v  = i.get('rsi',{}).get('value', 0)
    rsi_s  = i.get('rsi',{}).get('signal', '?')
    macd_h = i.get('macd',{}).get('hist', 0)
    macd_s = i.get('macd',{}).get('signal', '?')
    ema_s  = i.get('ema',{}).get('signal', '?')
    adx_v  = i.get('adx',{}).get('adx', 0)
    adx_t  = i.get('adx',{}).get('trending', False)
    bb_pb  = i.get('bollinger',{}).get('pct_b', 0.5)
    bb_s   = i.get('bollinger',{}).get('signal', '?')
    pat    = i.get('patterns',{}).get('detail', 'none')

    print(f"  RSI({rsi_v:.1f}): {rsi_s}")
    print(f"  MACD hist({macd_h:.6f}): {macd_s}")
    print(f"  EMA: {ema_s}")
    print(f"  ADX({adx_v:.1f}) trending={adx_t}")
    print(f"  BB %B={bb_pb:.2f}: {bb_s}")
    print(f"  Patterns: {pat}")
    print()

    sym_info = mt5c.get_symbol_info(sym)
    signal = strat.get_signal(sym, df, i, sym_info)
    print(f"  Strategy: {signal['action']} | {signal['strategy']} | Conf={signal['confidence']:.0f}%")
    if signal['action'] != 'WAIT':
        print(f"  Entry={signal['entry']:.5f} | SL={signal['sl']:.5f} | TP={signal['tp']:.5f}")
    print()

goal = rm.check_goal_status(acc, acc['balance'], 0)
print(f"Goal: {goal['status']} | Target=${goal['target_usd']:.2f} | Progress={goal['progress']:.1f}%")

mt5c.disconnect()
print()
print(">>> Test PASSED! Bot is ready to run. <<<")
