"""
=============================================================
  Trading Bot - Risk Manager
  إدارة المخاطر وحجم الصفقات
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
    sl_distance: float,       # SL distance in price units
    risk_pct: float = None,
) -> float:
    """
    Calculate lot size based on risk percentage and SL distance.
    Uses: lot = (balance * risk%) / (sl_distance * contract_size)
    """
    if risk_pct is None:
        risk_pct = TRADING["risk_per_trade_pct"]

    risk_amount  = account_balance * (risk_pct / 100)
    contract     = symbol_info.get("contract_size", 100000)
    min_lot      = symbol_info.get("volume_min", 0.01)
    max_lot      = min(symbol_info.get("volume_max", 100), TRADING["max_lot"])
    step         = symbol_info.get("volume_step", 0.01)

    if sl_distance <= 0:
        return TRADING["default_lot"]

    # For forex: pip value = contract_size * point
    # lot = risk_amount / (sl_pips * pip_value_per_lot)
    pip       = symbol_info.get("pip", symbol_info.get("point", 0.0001))
    pip_value = contract * pip  # value per lot per pip

    sl_pips = sl_distance / pip
    if sl_pips <= 0:
        return TRADING["default_lot"]

    raw_lot = risk_amount / (sl_pips * pip_value)

    # Snap to step
    lot = round(int(raw_lot / step) * step, 2)
    lot = max(min_lot, min(max_lot, lot))

    logger.debug(
        f"Lot calc: balance={account_balance:.2f} risk%={risk_pct} "
        f"risk$={risk_amount:.2f} sl_pips={sl_pips:.1f} lot={lot}"
    )
    return lot


def calculate_sl_tp(
    symbol_info: dict,
    order_type: str,       # "BUY" or "SELL"
    entry_price: float,
    atr_value: float,
    atr_multiplier_sl: float = 1.5,
    rr_ratio: float = None,
) -> tuple[float, float]:
    """
    Calculate SL and TP based on ATR.
    Returns (sl_price, tp_price).
    """
    if rr_ratio is None:
        rr_ratio = TRADING["reward_risk_ratio"]

    point   = symbol_info.get("point", 0.00001)
    min_sl  = point * 20  # minimum 20 points SL

    sl_dist = max(atr_value * atr_multiplier_sl, min_sl)
    tp_dist = sl_dist * rr_ratio

    if order_type == "BUY":
        sl = entry_price - sl_dist
        tp = entry_price + tp_dist
    else:
        sl = entry_price + sl_dist
        tp = entry_price - tp_dist

    # Round to symbol digits
    digits = symbol_info.get("digits", 5)
    sl = round(sl, digits)
    tp = round(tp, digits)

    return sl, tp


# ===== TRADING FILTERS =====

def should_trade(
    account_info: dict,
    open_positions: list,
    daily_profit: float,
    start_balance: float,
) -> tuple[bool, str]:
    """
    Check all risk management rules before opening a new trade.
    Returns (allowed: bool, reason: str).
    """
    balance = account_info.get("balance", 0)
    equity  = account_info.get("equity", 0)

    # 1. Check max total loss
    total_loss = balance - start_balance
    if total_loss <= -GOAL["max_loss_usd"]:
        return False, f"Max loss hit: ${total_loss:.2f} (limit: ${-GOAL['max_loss_usd']:.2f})"

    loss_pct = (total_loss / start_balance * 100) if start_balance else 0
    if loss_pct <= -GOAL["max_loss_pct"]:
        return False, f"Max loss % hit: {loss_pct:.1f}% (limit: {-GOAL['max_loss_pct']:.1f}%)"

    # 2. Check daily max loss
    if daily_profit <= -GOAL["daily_max_loss_usd"]:
        return False, f"Daily loss limit hit: ${daily_profit:.2f}"

    # 3. Check max positions
    if len(open_positions) >= TRADING["max_positions"]:
        return False, f"Max positions open: {len(open_positions)}/{TRADING['max_positions']}"

    # 4. Check if goal already achieved
    total_profit = balance - start_balance
    if total_profit >= GOAL["target_profit_usd"]:
        return False, f"GOAL ACHIEVED! Profit=${total_profit:.2f} >= target=${GOAL['target_profit_usd']:.2f}"

    # 5. Check margin level
    margin_level = account_info.get("margin_level", 999)
    if 0 < margin_level < 150:
        return False, f"Margin level too low: {margin_level:.0f}%"

    # 6. Check trade is allowed
    if not account_info.get("trade_allowed", True):
        return False, "Trading not allowed on this account"

    return True, "OK"


def apply_trailing_stop(
    position: dict,
    symbol_info: dict,
    atr_value: float,
    trail_multiplier: float = 1.0,
) -> Optional[float]:
    """
    Calculate new trailing SL.
    Returns new SL price if it should be moved, else None.
    """
    cur  = position["current_price"]
    old_sl = position["sl"]
    ptype  = position["type"]

    atr    = atr_value or 0
    trail  = max(atr * trail_multiplier, symbol_info.get("point", 0.00001) * 20)

    if ptype == "BUY":
        new_sl = cur - trail
        if old_sl and new_sl > old_sl + symbol_info.get("point", 0.00001) * 5:
            return round(new_sl, symbol_info.get("digits", 5))
    else:  # SELL
        new_sl = cur + trail
        if old_sl and new_sl < old_sl - symbol_info.get("point", 0.00001) * 5:
            return round(new_sl, symbol_info.get("digits", 5))

    return None


# ===== GOAL TRACKING =====

def check_goal_status(account_info: dict, start_balance: float, daily_profit: float) -> dict:
    """
    Returns complete goal status report.
    """
    balance = account_info.get("balance", 0)
    equity  = account_info.get("equity", 0)

    total_profit     = balance - start_balance
    total_profit_pct = (total_profit / start_balance * 100) if start_balance else 0
    target_usd       = GOAL["target_profit_usd"]
    target_pct       = GOAL["target_profit_pct"]
    max_loss         = GOAL["max_loss_usd"]

    progress_usd  = min(100, max(0, total_profit / target_usd * 100)) if target_usd else 0
    progress_pct  = min(100, max(0, total_profit_pct / target_pct * 100)) if target_pct else 0
    progress      = max(progress_usd, progress_pct)

    remaining     = max(0, target_usd - total_profit)
    daily_target  = GOAL["daily_target_usd"]
    daily_progress= min(100, max(0, daily_profit / daily_target * 100)) if daily_target else 0

    status = "ACTIVE"
    if total_profit >= target_usd:
        status = "GOAL_ACHIEVED"
    elif total_profit <= -max_loss:
        status = "STOP_LOSS"
    elif daily_profit <= -GOAL["daily_max_loss_usd"]:
        status = "DAILY_LIMIT"

    return {
        "status":          status,
        "start_balance":   start_balance,
        "current_balance": balance,
        "current_equity":  equity,
        "total_profit":    total_profit,
        "total_profit_pct":total_profit_pct,
        "daily_profit":    daily_profit,
        "target_usd":      target_usd,
        "remaining":       remaining,
        "progress":        progress,
        "daily_progress":  daily_progress,
        "max_loss":        max_loss,
    }
