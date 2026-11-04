"""
=============================================================
  Trading Bot - MT5 Connector
  الاتصال بـ MetaTrader 5 وتنفيذ الصفقات
=============================================================
"""
import logging
from datetime import datetime, timedelta
from typing import Optional

import MetaTrader5 as mt5
import pandas as pd

from config import MT5 as MT5_CFG, TRADING

logger = logging.getLogger(__name__)

# Timeframe mapping
TF_MAP = {
    "M1":  mt5.TIMEFRAME_M1,
    "M5":  mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1":  mt5.TIMEFRAME_H1,
    "H4":  mt5.TIMEFRAME_H4,
    "D1":  mt5.TIMEFRAME_D1,
}


# ===== CONNECTION =====

def connect() -> bool:
    """Initialize connection to MT5 terminal."""
    if not mt5.initialize():
        logger.error(f"MT5 initialize() failed: {mt5.last_error()}")
        return False
    info = mt5.terminal_info()
    if info is None:
        logger.error("Could not get terminal info")
        return False
    logger.info(f"Connected to MT5: {info.name} build {info.build}")
    acc = mt5.account_info()
    if acc:
        logger.info(f"Account: #{acc.login} | {acc.server} | Balance: ${acc.balance:.2f}")
    return True


def disconnect():
    """Shutdown MT5 connection."""
    mt5.shutdown()
    logger.info("MT5 disconnected")


def is_connected() -> bool:
    """Check if MT5 is still connected."""
    info = mt5.terminal_info()
    return info is not None and info.connected


# ===== ACCOUNT =====

def get_account_info() -> dict:
    """Return account info as a dict."""
    acc = mt5.account_info()
    if acc is None:
        return {}
    return {
        "login":        acc.login,
        "server":       acc.server,
        "balance":      acc.balance,
        "equity":       acc.equity,
        "profit":       acc.profit,
        "margin":       acc.margin,
        "margin_free":  acc.margin_free,
        "margin_level": acc.margin_level,
        "currency":     acc.currency,
        "leverage":     acc.leverage,
        "trade_allowed":acc.trade_allowed,
    }


# ===== MARKET DATA =====

def get_ohlcv(symbol: str, timeframe: str = "H1", bars: int = 500) -> Optional[pd.DataFrame]:
    """
    Fetch OHLCV bars from MT5.
    Returns DataFrame with columns: time, open, high, low, close, tick_volume, spread
    """
    tf = TF_MAP.get(timeframe, mt5.TIMEFRAME_H1)
    rates = mt5.copy_rates_from_pos(symbol, tf, 0, bars)
    if rates is None or len(rates) == 0:
        logger.warning(f"No data for {symbol} {timeframe}: {mt5.last_error()}")
        return None
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df.set_index("time", inplace=True)
    df.rename(columns={"tick_volume": "volume"}, inplace=True)
    return df[["open", "high", "low", "close", "volume", "spread"]]


def get_symbol_info(symbol: str) -> Optional[dict]:
    """Return symbol info dict."""
    info = mt5.symbol_info(symbol)
    if info is None:
        return None
    tick = mt5.symbol_info_tick(symbol)
    return {
        "name":           info.name,
        "digits":         info.digits,
        "point":          info.point,
        "pip":            info.point * 10 if info.digits in (4, 5) else info.point,
        "spread":         info.spread,
        "volume_min":     info.volume_min,
        "volume_max":     info.volume_max,
        "volume_step":    info.volume_step,
        "contract_size":  info.trade_contract_size,
        "margin_initial": info.margin_initial,
        "currency_base":  info.currency_base,
        "currency_profit":info.currency_profit,
        "trade_mode":     info.trade_mode,
        "bid":            tick.bid if tick else 0,
        "ask":            tick.ask if tick else 0,
    }


def get_symbols_available() -> list:
    """Return list of available symbol names."""
    syms = mt5.symbols_get()
    if syms is None:
        return []
    return [s.name for s in syms if s.visible]


def check_symbols(wanted: list) -> list:
    """Return subset of wanted symbols that are available in MT5."""
    available = set(get_symbols_available())
    # Also try enabling symbols
    result = []
    for sym in wanted:
        if sym in available:
            mt5.symbol_select(sym, True)
            result.append(sym)
        else:
            logger.warning(f"Symbol {sym} not available in this broker")
    return result


# ===== POSITIONS =====

def get_open_positions(magic: int = None) -> list:
    """Return list of open positions (optionally filtered by magic number)."""
    positions = mt5.positions_get()
    if positions is None:
        return []
    result = []
    for p in positions:
        if magic and p.magic != magic:
            continue
        result.append({
            "ticket":      p.ticket,
            "symbol":      p.symbol,
            "type":        "BUY" if p.type == mt5.ORDER_TYPE_BUY else "SELL",
            "type_code":   p.type,
            "volume":      p.volume,
            "open_price":  p.price_open,
            "current_price": p.price_current,
            "sl":          p.sl,
            "tp":          p.tp,
            "profit":      p.profit,
            "swap":        p.swap,
            "comment":     p.comment,
            "magic":       p.magic,
            "open_time":   datetime.fromtimestamp(p.time),
        })
    return result


def get_trade_history(days: int = 30) -> list:
    """Return closed trade history for last N days."""
    date_from = datetime.now() - timedelta(days=days)
    deals = mt5.history_deals_get(date_from, datetime.now())
    if deals is None:
        return []
    result = []
    for d in deals:
        if d.type in (mt5.DEAL_TYPE_BUY, mt5.DEAL_TYPE_SELL):
            result.append({
                "ticket":  d.ticket,
                "order":   d.order,
                "symbol":  d.symbol,
                "type":    "BUY" if d.type == mt5.DEAL_TYPE_BUY else "SELL",
                "volume":  d.volume,
                "price":   d.price,
                "profit":  d.profit,
                "swap":    d.swap,
                "commission": d.commission,
                "time":    datetime.fromtimestamp(d.time),
                "comment": d.comment,
            })
    return sorted(result, key=lambda x: x["time"], reverse=True)


# ===== ORDER EXECUTION =====

def place_order(
    symbol: str,
    order_type: str,       # "BUY" or "SELL"
    lot: float,
    sl: float = 0.0,
    tp: float = 0.0,
    comment: str = "TradingBot",
    magic: int = None,
) -> dict:
    """
    Place a market order on MT5.
    Returns dict with success, ticket, error.
    """
    if magic is None:
        magic = TRADING["magic_number"]

    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return {"success": False, "error": "No tick data"}

    if order_type == "BUY":
        price     = tick.ask
        order_t   = mt5.ORDER_TYPE_BUY
    else:
        price     = tick.bid
        order_t   = mt5.ORDER_TYPE_SELL

    request = {
        "action":    mt5.TRADE_ACTION_DEAL,
        "symbol":    symbol,
        "volume":    float(lot),
        "type":      order_t,
        "price":     price,
        "sl":        sl,
        "tp":        tp,
        "deviation": TRADING["slippage"],
        "magic":     magic,
        "comment":   comment,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(request)
    if result is None:
        err = mt5.last_error()
        logger.error(f"order_send returned None: {err}")
        return {"success": False, "error": str(err)}

    if result.retcode != mt5.TRADE_RETCODE_DONE:
        logger.error(f"Order failed: retcode={result.retcode} | {result.comment}")
        return {"success": False, "error": f"{result.retcode}: {result.comment}"}

    logger.info(f"Order placed: {order_type} {lot} {symbol} @ {price} | Ticket={result.order}")
    return {
        "success": True,
        "ticket":  result.order,
        "price":   result.price,
        "volume":  result.volume,
    }


def close_position(ticket: int) -> bool:
    """Close an open position by ticket."""
    pos = mt5.positions_get(ticket=ticket)
    if not pos:
        logger.warning(f"Position {ticket} not found")
        return False
    p = pos[0]
    tick = mt5.symbol_info_tick(p.symbol)
    if tick is None:
        return False

    if p.type == mt5.ORDER_TYPE_BUY:
        price   = tick.bid
        close_t = mt5.ORDER_TYPE_SELL
    else:
        price   = tick.ask
        close_t = mt5.ORDER_TYPE_BUY

    request = {
        "action":    mt5.TRADE_ACTION_DEAL,
        "symbol":    p.symbol,
        "volume":    p.volume,
        "type":      close_t,
        "position":  ticket,
        "price":     price,
        "deviation": TRADING["slippage"],
        "magic":     p.magic,
        "comment":   "close",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    result = mt5.order_send(request)
    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
        logger.info(f"Closed position {ticket}")
        return True
    logger.error(f"Close failed: {result.retcode if result else 'None'}")
    return False


def close_all_positions(magic: int = None) -> int:
    """Close all open positions. Returns count of closed positions."""
    if magic is None:
        magic = TRADING["magic_number"]
    positions = get_open_positions(magic=magic)
    closed = 0
    for pos in positions:
        if close_position(pos["ticket"]):
            closed += 1
    return closed


def modify_sl_tp(ticket: int, sl: float, tp: float) -> bool:
    """Modify SL and TP of an open position."""
    request = {
        "action":   mt5.TRADE_ACTION_SLTP,
        "position": ticket,
        "sl":       sl,
        "tp":       tp,
    }
    result = mt5.order_send(request)
    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
        logger.debug(f"Modified SL/TP for ticket {ticket}")
        return True
    return False
