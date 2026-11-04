"""Quick test script for all bot modules."""
import sys
sys.path.insert(0, r'C:\Users\hassa\AppData\Roaming\Python\Python314\site-packages')

import os
os.chdir(r'c:\Users\hassa\Desktop\New folder (14)\trading_bot')

print("=" * 50)
print("TESTING BOT MODULES")
print("=" * 50)

# Test config
print("\n1. Testing config...")
import config as cfg
print(f"   Goal: ${cfg.GOAL['target_profit_usd']}")
print(f"   Max Loss: ${cfg.GOAL['max_loss_usd']}")
print(f"   Symbols: {cfg.TRADING['symbols']}")
print("   config OK [PASS]")

# Test indicators
print("\n2. Testing indicators...")
import numpy as np
import pandas as pd

np.random.seed(42)
n = 300
close = 1.1000 + np.cumsum(np.random.randn(n) * 0.0005)
high = close + np.abs(np.random.randn(n) * 0.0003)
low = close - np.abs(np.random.randn(n) * 0.0003)
open_ = close + np.random.randn(n) * 0.0002
volume = np.random.randint(100, 1000, n).astype(float)
df = pd.DataFrame({
    'open': open_, 'high': high, 'low': low,
    'close': close, 'tick_volume': volume
})

from indicators import analyze
result = analyze(df)
print(f"   RSI: {result['rsi']['value']:.2f} [{result['rsi']['signal']}]")
print(f"   MACD hist: {result['macd']['histogram']:.6f} [{result['macd']['signal']}]")
print(f"   EMA20: {result['ema']['ema20']:.5f}")
print(f"   ADX: {result['adx']['adx']:.2f} [{result['adx']['trend_strength']}]")
print(f"   BB: {result['bollinger']['signal']}")
print(f"   ATR: {result['atr']['value']:.6f}")
print(f"   Stoch K: {result['stochastic']['k']:.2f}")
print(f"   Overall score: {result['overall_score']:+.2f}")
print(f"   Confidence: {result['confidence']:.1f}%")
print(f"   Action: {result['action']}")
print(f"   Buy signals: {result['buy_signal_count']}")
print(f"   Sell signals: {result['sell_signal_count']}")
print("   indicators OK ✓")

# Test risk manager
print("\n3. Testing risk_manager...")
from risk_manager import (
    calculate_lot_size, calculate_sl_tp_prices,
    should_trade, check_goal_status, get_daily_pl
)

sym_info = {
    'point': 0.00001, 'digits': 5,
    'trade_contract_size': 100000,
    'trade_tick_value': 1.0, 'pip_value': 10.0,
    'volume_min': 0.01, 'volume_max': 100.0, 'volume_step': 0.01,
    'spread': 15,
}

lot = calculate_lot_size("EURUSDm", sl_pips=25, risk_pct=1.0,
                          account_balance=100.0, symbol_info=sym_info)
print(f"   Lot size (1% risk, 25 pip SL, $100): {lot}")

sl, tp = calculate_sl_tp_prices("BUY", 1.10000, 0.00120, sym_info)
print(f"   SL: {sl:.5f}, TP: {tp:.5f}")

can_trade, reason = should_trade(
    {'balance': 100, 'equity': 95, 'margin_free': 90, 'margin_level': 500},
    [], daily_pl=0.0
)
print(f"   should_trade: {can_trade} - {reason}")

goal_status = check_goal_status(
    {'balance': 105.0, 'equity': 105.0},
    cfg.GOAL, start_balance=100.0
)
print(f"   Goal status: {goal_status['status']} | Progress: {goal_status['progress_pct']:.1f}%")
print(f"   Profit: ${goal_status['total_profit']:.2f}")
print("   risk_manager OK ✓")

# Test strategy
print("\n4. Testing strategy...")
from strategy import (
    strategy_trend_following, strategy_mean_reversion,
    strategy_breakout, strategy_macd_divergence, get_signal
)

s1 = strategy_trend_following(df, result)
print(f"   Trend Following: {s1['signal']} ({s1['confidence']:.1f}%)")
s2 = strategy_mean_reversion(df, result)
print(f"   Mean Reversion:  {s2['signal']} ({s2['confidence']:.1f}%)")
s3 = strategy_breakout(df, result)
print(f"   Breakout:        {s3['signal']} ({s3['confidence']:.1f}%)")
s4 = strategy_macd_divergence(df, result)
print(f"   MACD Divergence: {s4['signal']} ({s4['confidence']:.1f}%)")

signal = get_signal("EURUSDm", df, result, sym_info)
print(f"   Best signal: {signal['signal']} ({signal['confidence']:.1f}%) [{signal['strategy']}]")
print("   strategy OK ✓")

# Test dashboard
print("\n5. Testing dashboard...")
from dashboard import Dashboard
dash = Dashboard()
dash.update(
    account_info={'balance': 100.0, 'equity': 100.5, 'profit': 0.5,
                  'margin': 2.0, 'margin_free': 98.0, 'margin_level': 5000.0,
                  'leverage': 2000, 'server': 'Exness-MT5Trial15'},
    goal_status=goal_status,
    open_positions=[],
    trade_history=[],
    market_analysis={"EURUSDm": result},
    signals={"EURUSDm": signal},
    last_action="Test cycle",
    next_scan_in=60,
)
dash.add_signal_log("Dashboard test", "INFO")
dash.print_message("Dashboard test successful", "SUCCESS")
print("   dashboard OK ✓")

# Test MT5 connector (import only - can't connect without MT5)
print("\n6. Testing mt5_connector imports...")
from mt5_connector import (
    connect, disconnect, is_connected, get_account_info,
    get_symbols, get_ohlcv, get_open_positions, get_trade_history,
    get_symbol_info, place_order, close_position,
)
print("   mt5_connector imports OK ✓")

print("\n" + "=" * 50)
print("ALL MODULES LOADED SUCCESSFULLY ✓")
print("=" * 50)
print("\nReady to run: python trading_bot.py --dry-run")
