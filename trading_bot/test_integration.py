"""Integration test script."""
import sys, os
os.chdir(r'c:\Users\hassa\Desktop\New folder (14)\trading_bot')

import config as cfg
from mt5_connector import connect, get_account_info, get_symbols, get_ohlcv, get_symbol_info, disconnect
from indicators import analyze
from strategy import get_signal
from risk_manager import check_goal_status, should_trade, check_spread, calculate_lot_size

print('=== Full Integration Test ===')

# Connect
print('Connecting to MT5...')
ok = connect()
print(f'Connected: {ok}')

# Account
acc = get_account_info()
bal = acc.get('balance', 0)
print(f'Balance: ${bal:.2f}')
print(f'Server: {acc.get("server")}')

# Available symbols
syms = get_symbols()
print(f'Available symbols ({len(syms)}): {syms[:10]}')

# Test analysis on first available symbol
test_sym = syms[0] if syms else 'BTCUSDm'
print(f'Testing analysis on {test_sym}...')

df = get_ohlcv(test_sym, 'H1', 300)
bars = len(df) if df is not None else 0
print(f'OHLCV bars: {bars}')

if df is not None and len(df) > 50:
    indicators = analyze(df)
    rsi_val = indicators['rsi']['value']
    score = indicators['overall_score']
    conf = indicators['confidence']
    action = indicators['action']
    adx_val = indicators['adx']['adx']
    adx_str = indicators['adx']['trend_strength']
    bb_sig = indicators['bollinger']['signal']
    bb_pos = indicators['bollinger']['position']

    print(f'  RSI: {rsi_val:.1f}')
    print(f'  MACD: {indicators["macd"]["signal"]}')
    print(f'  EMA trend: {indicators["ema"]["signal"]}')
    print(f'  ADX: {adx_val:.1f} [{adx_str}]')
    print(f'  BB: {bb_sig} (pos: {bb_pos})')
    print(f'  Score: {score:+.1f}')
    print(f'  Confidence: {conf:.1f}%')
    print(f'  Action: {action}')

    sym_info = get_symbol_info(test_sym)
    spread_pts = sym_info.get('spread', 0)
    print(f'  Spread: {spread_pts} points')

    spread_ok, spread_val = check_spread(sym_info)
    print(f'  Spread OK: {spread_ok} ({spread_val})')

    signal = get_signal(test_sym, df, indicators, sym_info)
    sig_name = signal['signal']
    sig_conf = signal['confidence']
    sig_strat = signal['strategy']
    print(f'  Signal: {sig_name} ({sig_conf:.1f}%) [{sig_strat}]')
    if signal.get('sl'):
        sl = signal['sl']
        tp = signal['tp']
        print(f'  SL: {sl:.5f}, TP: {tp:.5f}')

goal_status = check_goal_status(acc, cfg.GOAL, start_balance=100.0)
print(f'Goal status: {goal_status["status"]}')

can_trade, reason = should_trade(acc, [])
print(f'Can trade: {can_trade} - {reason}')

disconnect()
print('=== Integration Test PASSED ===')
