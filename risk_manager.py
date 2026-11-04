"""
=============================================================
  Trading Bot - Risk Manager  (v2 - Fixed)
  إدارة المخاطر وحجم الصفقات — محسوب على الرصيد الفعلي
=============================================================
"""
import logging
from datetime import datetime, date
from typing import Optional

from config import GOAL, TRADING

logger = logging.getLogger(__name__)


# ===== POSITION SIZING =====

def calculate_lot_size(
    symbol_info: dict,
    account_balance: float,
    sl_distance: float,       # SL distance in price units (abs value)
    risk_pct: float = None,
) -> float:
    """
    Calculate lot size based on risk percentage and SL distance.
    Uses: lot = (balance × risk%) / (sl_distance × contract_size)
    """
    if risk_pct is None:
        risk_pct = TRADING["risk_per_trade_pct"]

    risk_amount  = account_balance * (risk_pct / 100.0)
    contract     = symbol_info.get("contract_size", 100000)
    min_lot      = symbol_info.get("volume_min", 0.01)
    max_lot      = min(symbol_info.get("volume_max", 100.0), TRADING.get("max_lot", 0.10))
    step         = symbol_info.get("volume_step", 0.01)

    if sl_distance <= 0:
        return max(min_lot, TRADING.get("default_lot", 0.01))

    # Calculate correct contract value per lot
    # For XAUUSDm: contract_size=100 → 1 lot = 100 oz
    # For BTCUSDm: contract_size=1  → 1 lot = 1 BTC
    # For FX:      contract_size=100000
    # pip_value_per_lot = contract_size * point
    point = symbol_info.get("point", 0.00001)
    pip   = symbol_info.get("pip", point)

    # Money at risk per lot for given SL distance
    # risk_per_lot = sl_distance / point * (contract * point) = sl_distance * contract
    risk_per_lot = sl_distance * contract  # USD risk per 1 lot

    if risk_per_lot <= 0:
        return max(min_lot, TRADING.get("default_lot", 0.01))

    raw_lot = risk_amount / risk_per_lot

    # Snap to volume step
    if step > 0:
        raw_lot = int(raw_lot / step) * step

    lot = round(raw_lot, 2)
    lot = max(min_lot, min(max_lot, lot))

    logger.info(
        f"Lot calc: balance={account_balance:.2f} risk%={risk_pct} "
        f"risk$={risk_amount:.2f} sl_dist={sl_distance:.5f} "
        f"risk_per_lot={risk_per_lot:.2f} → lot={lot}"
    )
    return lot


def calculate_sl_tp(
    symbol_info: dict,
    order_type: str,       # "BUY" or "SELL"
    entry_price: float,
    atr_value: float,
    atr_multiplier_sl: float = 1.5,
    rr_ratio: float = None,
) -> tuple:
    """
    Calculate SL and TP based on ATR — properly rounded to symbol digits.
    Returns (sl_price, tp_price, sl_distance).
    """
    if rr_ratio is None:
        rr_ratio = TRADING.get("reward_risk_ratio", 2.0)

    digits  = symbol_info.get("digits", 5)
    point   = symbol_info.get("point", 0.00001)

    # Minimum SL = 50 points (protects against broker min-distance)
    min_sl_dist = point * 50

    # ATR-based SL distance
    sl_dist = max(atr_value * atr_multiplier_sl, min_sl_dist)
    tp_dist = sl_dist * rr_ratio

    if order_type.upper() == "BUY":
        sl = round(entry_price - sl_dist, digits)
        tp = round(entry_price + tp_dist, digits)
    else:
        sl = round(entry_price + sl_dist, digits)
        tp = round(entry_price - tp_dist, digits)

    # Sanity check: SL and TP must make sense
    if order_type.upper() == "BUY":
        if sl >= entry_price or tp <= entry_price:
            sl = round(entry_price - sl_dist, digits)
            tp = round(entry_price + tp_dist, digits)
    else:
        if sl <= entry_price or tp >= entry_price:
            sl = round(entry_price + sl_dist, digits)
            tp = round(entry_price - tp_dist, digits)

    logger.info(
        f"SL/TP calc [{order_type}]: entry={entry_price} "
        f"ATR={atr_value:.5f} × {atr_multiplier_sl} = SL_dist={sl_dist:.5f} "
        f"TP_dist={tp_dist:.5f} → SL={sl} TP={tp} (digits={digits})"
    )
    return sl, tp, sl_dist


# ===== TRADING FILTERS =====

def should_trade(
    account_info: dict,
    open_positions: list,
    daily_profit: float,
    start_balance: float,
    goal_state: dict = None,
) -> tuple:
    """
    Check all risk management rules before opening a new trade.
    Returns (allowed: bool, reason: str).
    Uses goal_state (user-set values) instead of hardcoded GOAL config.
    """
    balance = account_info.get("balance", 0)
    equity  = account_info.get("equity", 0)

    # Use user-defined goal values from GOAL_STATE if available
    if goal_state:
        target_usd      = float(goal_state.get("target_profit_usd", GOAL["target_profit_usd"]))
        max_loss_usd    = float(goal_state.get("max_loss_usd",       GOAL["max_loss_usd"]))
        daily_max_loss  = float(goal_state.get("daily_max_loss_usd", GOAL.get("daily_max_loss_usd", 3.0)))
        max_positions   = int(goal_state.get("max_positions", TRADING.get("max_positions", 3)))
    else:
        target_usd      = float(GOAL["target_profit_usd"])
        max_loss_usd    = float(GOAL["max_loss_usd"])
        daily_max_loss  = float(GOAL.get("daily_max_loss_usd", 3.0))
        max_positions   = int(TRADING.get("max_positions", 3))

    # 1. Total loss check
    total_loss = balance - start_balance
    if total_loss <= -max_loss_usd:
        return False, f"تم بلوغ الحد الأقصى للخسارة الإجمالية: ${total_loss:.2f} (الحد: -${max_loss_usd:.2f})"

    # 2. Daily loss check
    if daily_profit <= -daily_max_loss:
        return False, f"تم بلوغ الحد الأقصى للخسارة اليومية: ${daily_profit:.2f}"

    # 3. Max positions
    if len(open_positions) >= max_positions:
        return False, f"الحد الأقصى للصفقات المفتوحة: {len(open_positions)}/{max_positions}"

    # 4. Goal achieved
    total_profit = balance - start_balance
    if total_profit >= target_usd:
        return False, f"تم تحقيق الهدف المالي! ربح=${total_profit:.2f} >= هدف=${target_usd:.2f}"

    # 5. Margin level
    margin_level = account_info.get("margin_level", 999)
    if 0 < margin_level < 200:
        return False, f"مستوى الهامش منخفض جداً: {margin_level:.0f}% (الحد الأدنى: 200%)"

    # 6. Equity vs Balance drawdown protection (don't trade if floating loss > 5%)
    if balance > 0:
        eq_drawdown_pct = (balance - equity) / balance * 100
        if eq_drawdown_pct > 5.0:
            return False, f"خسارة عائمة عالية: {eq_drawdown_pct:.1f}% — انتظار استقرار"

    # 7. Trade allowed by broker
    if not account_info.get("trade_allowed", True):
        return False, "التداول غير مسموح على هذا الحساب"

    return True, "OK"


def apply_trailing_stop(
    position: dict,
    symbol_info: dict,
    atr_value: float,
    trail_multiplier: float = 1.0,
) -> Optional[float]:
    """
    Calculate new trailing SL based on ATR.
    Returns new SL price if it should be moved, else None.
    """
    cur    = position["current_price"]
    old_sl = position.get("sl", 0)
    ptype  = position["type"]

    atr   = atr_value or 0
    trail = max(atr * trail_multiplier, symbol_info.get("point", 0.00001) * 20)
    digits = symbol_info.get("digits", 5)

    if ptype == "BUY":
        new_sl = round(cur - trail, digits)
        if old_sl and new_sl > old_sl + symbol_info.get("point", 0.00001) * 5:
            return new_sl
    else:  # SELL
        new_sl = round(cur + trail, digits)
        if old_sl and new_sl < old_sl - symbol_info.get("point", 0.00001) * 5:
            return new_sl

    return None


# ===== GOAL TRACKING =====

def check_goal_status(account_info: dict, start_balance: float, daily_profit: float, goal_state: dict = None) -> dict:
    """
    Returns complete goal status report.
    Uses goal_state (user-set values) for accurate progress calculation.
    """
    balance = account_info.get("balance", 0)
    equity  = account_info.get("equity", 0)

    total_profit     = balance - start_balance
    total_profit_pct = (total_profit / start_balance * 100) if start_balance else 0

    # Use user-defined values from goal_state if available
    if goal_state:
        target_usd    = float(goal_state.get("target_profit_usd", GOAL["target_profit_usd"]))
        max_loss      = float(goal_state.get("max_loss_usd",       GOAL["max_loss_usd"]))
        daily_target  = float(goal_state.get("daily_target_usd",   GOAL.get("daily_target_usd", 5.0)))
        daily_max_loss= float(goal_state.get("daily_max_loss_usd", GOAL.get("daily_max_loss_usd", 3.0)))
    else:
        target_usd    = float(GOAL["target_profit_usd"])
        max_loss      = float(GOAL["max_loss_usd"])
        daily_target  = float(GOAL.get("daily_target_usd", 5.0))
        daily_max_loss= float(GOAL.get("daily_max_loss_usd", 3.0))

    # Progress based on ACTUAL user-set target
    progress       = min(100.0, max(0.0, (total_profit / target_usd * 100))) if target_usd > 0 else 0.0
    daily_progress = min(100.0, max(0.0, (daily_profit / daily_target * 100))) if daily_target > 0 else 0.0
    remaining      = max(0.0, target_usd - total_profit)

    status = "ACTIVE"
    if total_profit >= target_usd:
        status = "GOAL_ACHIEVED"
    elif total_profit <= -max_loss:
        status = "STOP_LOSS"
    elif daily_profit <= -daily_max_loss:
        status = "DAILY_LIMIT"

    return {
        "status":           status,
        "start_balance":    start_balance,
        "current_balance":  balance,
        "current_equity":   equity,
        "total_profit":     round(total_profit, 2),
        "total_profit_pct": round(total_profit_pct, 2),
        "daily_profit":     round(daily_profit, 2),
        "target_usd":       target_usd,
        "remaining":        round(remaining, 2),
        "progress":         round(progress, 1),
        "daily_progress":   round(daily_progress, 1),
        "max_loss":         max_loss,
        "daily_target":     daily_target,
    }
