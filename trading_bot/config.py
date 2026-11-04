"""
=============================================================
  Trading Bot - Configuration & Goals
  تكوين البوت وأهداف التداول
=============================================================
"""

# ===== GOAL CONFIGURATION =====
GOAL = {
    "target_profit_usd": 20.0,       # هدف الربح بالدولار
    "target_profit_pct": 20.0,        # هدف الربح بالنسبة المئوية 20%
    "max_loss_usd":      10.0,        # أقصى خسارة مسموحة
    "max_loss_pct":      10.0,        # أقصى خسارة 10%
    "daily_target_usd":   5.0,        # هدف يومي $5
    "daily_max_loss_usd": 3.0,        # أقصى خسارة يومية $3
}

# ===== TRADING CONFIGURATION =====
TRADING = {
    "symbols": ["XAUUSDm", "BTCUSDm", "ETHUSDm", "EURUSDm", "GBPUSDm"],
    "primary_timeframe": "H1",
    "entry_timeframe":   "M15",
    "max_positions":      3,
    "risk_per_trade_pct": 1.0,
    "default_lot":        0.01,
    "max_lot":            0.10,
    "min_lot":            0.01,
    "magic_number":       20241104,
    "slippage":           10,
    "min_confidence":     65,
    "scan_interval_sec":  60,
    "reward_risk_ratio":  2.0,
}

# ===== INDICATOR SETTINGS =====
INDICATORS = {
    "rsi_period":     14,
    "rsi_overbought": 70,
    "rsi_oversold":   30,
    "macd_fast":      12,
    "macd_slow":      26,
    "macd_signal":    9,
    "ema_fast":       20,
    "ema_slow":       50,
    "ema_trend":      200,
    "bb_period":      20,
    "bb_std":         2.0,
    "atr_period":     14,
    "stoch_k":        14,
    "stoch_d":        3,
    "adx_period":     14,
    "cci_period":     20,
    "williams_period":14,
    "mfi_period":     14,
    "obv_sma":        20,
    "donchian_period":20,
    "aroon_period":   25,
}

MT5 = {
    "login":    None,
    "password": None,
    "server":   None,
    "timeout":  10000,
}

LOG = {
    "level":        "INFO",
    "file_prefix":  "bot",
    "max_bytes":    5_000_000,
    "backup_count": 3,
}
