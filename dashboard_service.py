"""
Dashboard & Trading Service
خدمة التحليل الفني ومحرك المؤشرات وإدارة الأهداف والبوت الآلي لـ MT5
"""

import json
import logging
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import numpy as np

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

import indicators as ind_engine
import strategy as strat_engine
import risk_manager as rm
from config import GOAL, TRADING

logger = logging.getLogger("dashboard_service")

ROOT = Path(__file__).parent
STATE_FILE = ROOT / "bot_goal_state.json"
BOT_CONFIG_FILE = ROOT / "bot_config.json"

_CACHE: Dict[str, Any] = {}
_LOCK = threading.Lock()


def _sanitize(obj):
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    if isinstance(obj, (np.integer, int)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return [_sanitize(x) for x in obj.tolist()]
    if isinstance(obj, dict):
        return {str(k): _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize(v) for v in obj]
    return obj


# ===== GOAL STATE =====

def load_goal_state() -> Dict[str, Any]:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "start_balance": None,
        "daily_start": None,
        "last_day": str(datetime.now().date()),
        "target_profit_usd": GOAL.get("target_profit_usd", 20.0),
        "target_profit_pct": GOAL.get("target_profit_pct", 20.0),
        "max_loss_usd": GOAL.get("max_loss_usd", 10.0),
        "max_loss_pct": GOAL.get("max_loss_pct", 10.0),
        "daily_target_usd": GOAL.get("daily_target_usd", 5.0),
    }


def save_goal_state(state: Dict[str, Any]) -> None:
    try:
        STATE_FILE.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
    except Exception as e:
        logger.error(f"Failed to save goal state: {e}")


GOAL_STATE = load_goal_state()


# ===== BOT CONFIG & STATE =====

BOT_LOGS: List[Dict[str, Any]] = []
BOT_LOGS_LOCK = threading.Lock()

BOT_STATE: Dict[str, Any] = {
    "running": True,                 # Auto-trading loop enabled by default
    "auto_trade": True,              # Execute real orders on MT5
    "min_confidence": 60.0,          # Minimum confidence to open trade
    "lot_size": 0.01,                # Standard lot size
    "max_positions": 2,              # Max concurrent open positions
    "trailing_stop": True,           # Enable smart trailing stop
    "scan_interval": 15,             # Scan interval in seconds
    "symbols": ["XAUUSDm", "BTCUSDm", "ETHUSDm"],
    "last_scan": None,
    "total_trades": 0,
    "last_action": "بدء تشغيل النظام والمراقبة الحية",
}


def add_bot_log(text: str, level: str = "INFO"):
    ts = datetime.now().strftime("%H:%M:%S")
    entry = {"time": ts, "level": level, "text": text}
    with BOT_LOGS_LOCK:
        BOT_LOGS.insert(0, entry)
        if len(BOT_LOGS) > 120:
            BOT_LOGS.pop()
    print(f"[{ts}] [{level}] {text}")


add_bot_log("🚀 تم تشغيل محرك البوت الآلي لـ MT5 بنجاح", "SUCCESS")


def ensure_mt5() -> bool:
    if mt5 is None:
        return False
    if not mt5.initialize():
        return False
    return True


def get_ohlcv(symbol: str, timeframe: str = "H1", count: int = 300) -> Optional[pd.DataFrame]:
    if not ensure_mt5():
        return None
    tf_map = {
        "M1": mt5.TIMEFRAME_M1,
        "M5": mt5.TIMEFRAME_M5,
        "M15": mt5.TIMEFRAME_M15,
        "M30": mt5.TIMEFRAME_M30,
        "H1": mt5.TIMEFRAME_H1,
        "H4": mt5.TIMEFRAME_H4,
        "D1": mt5.TIMEFRAME_D1,
    }
    tf = tf_map.get(timeframe.upper(), mt5.TIMEFRAME_H1)
    rates = mt5.copy_rates_from_pos(symbol, tf, 0, count)
    if rates is None or len(rates) == 0:
        return None
    df = pd.DataFrame(rates)
    df["time_dt"] = pd.to_datetime(df["time"], unit="s")
    df.set_index("time_dt", inplace=True)
    df.rename(columns={"tick_volume": "volume"}, inplace=True)
    return df[["open", "high", "low", "close", "volume", "time"]]


def analyze_symbol(symbol: str, timeframe: str = "H1") -> Dict[str, Any]:
    cache_key = f"{symbol}_{timeframe}"
    now = time.time()
    with _LOCK:
        cached = _CACHE.get(cache_key)
        if cached and (now - cached["timestamp"] < 2.0):
            return cached["data"]

    df = get_ohlcv(symbol, timeframe, count=350)
    if df is None or len(df) < 50:
        return {"success": False, "error": f"تعذر قراءة بيانات الشموع للرمز {symbol} من MT5"}

    analysis = ind_engine.analyze(df)

    sym_info = {}
    if mt5 is not None:
        info = mt5.symbol_info(symbol)
        tick = mt5.symbol_info_tick(symbol)
        if info:
            sym_info = {
                "name": info.name,
                "digits": info.digits,
                "point": info.point,
                "pip": info.point * 10 if info.digits in (4, 5) else info.point,
                "spread": info.spread,
                "volume_min": info.volume_min,
                "volume_max": info.volume_max,
                "volume_step": info.volume_step,
                "bid": tick.bid if tick else 0,
                "ask": tick.ask if tick else 0,
            }

    strategy_signal = strat_engine.get_signal(symbol, df, analysis["indicators"], sym_info)

    # Format candles for HTML5 canvas rendering (last 120 bars)
    candles = []
    tail_df = df.tail(120)
    for idx, row in tail_df.iterrows():
        candles.append({
            "time": int(row["time"]),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row["volume"]),
        })

    import talib
    full_close = df["close"].values.astype(float)
    e20 = talib.EMA(full_close, 20)[-len(candles):]
    e50 = talib.EMA(full_close, 50)[-len(candles):]
    e200 = talib.EMA(full_close, 200)[-len(candles):]
    bb_u, bb_m, bb_l = talib.BBANDS(full_close, 20, 2, 2)
    rsi_arr = talib.RSI(full_close, 14)[-len(candles):]

    for i, c in enumerate(candles):
        c["ema20"] = float(e20[i]) if not np.isnan(e20[i]) else None
        c["ema50"] = float(e50[i]) if not np.isnan(e50[i]) else None
        c["ema200"] = float(e200[i]) if not np.isnan(e200[i]) else None
        c["bb_u"] = float(bb_u[-len(candles):][i]) if not np.isnan(bb_u[-len(candles):][i]) else None
        c["bb_l"] = float(bb_l[-len(candles):][i]) if not np.isnan(bb_l[-len(candles):][i]) else None
        c["rsi"] = float(rsi_arr[i]) if not np.isnan(rsi_arr[i]) else None

    raw_result = {
        "success": True,
        "symbol": symbol,
        "timeframe": timeframe,
        "current_price": float(df["close"].iloc[-1]),
        "digits": int(sym_info.get("digits", 2)),
        "overall_score": float(analysis.get("overall_score", 0)),
        "confidence": float(analysis.get("confidence", 0)),
        "action": str(analysis.get("action", "WAIT")),
        "buy_signals": int(analysis.get("buy_signals", 0)),
        "sell_signals": int(analysis.get("sell_signals", 0)),
        "neutral_signals": int(analysis.get("neutral_signals", 0)),
        "indicators": analysis.get("indicators", {}),
        "strategy": strategy_signal,
        "candles": candles,
        "timestamp": now,
    }

    result = _sanitize(raw_result)
    with _LOCK:
        _CACHE[cache_key] = {"data": result, "timestamp": now}

    return result


def get_goal_and_account_status() -> Dict[str, Any]:
    if not ensure_mt5():
        return {"success": False, "error": "منصة MT5 غير متصلة"}

    acc = mt5.account_info()
    if not acc:
        return {"success": False, "error": "تعذر قراءة بيانات الحساب"}

    global GOAL_STATE
    bal = float(acc.balance)
    eq = float(acc.equity)

    if GOAL_STATE.get("start_balance") is None:
        GOAL_STATE["start_balance"] = bal
        GOAL_STATE["daily_start"] = bal
        save_goal_state(GOAL_STATE)

    today_str = str(datetime.now().date())
    if GOAL_STATE.get("last_day") != today_str:
        GOAL_STATE["daily_start"] = bal
        GOAL_STATE["last_day"] = today_str
        save_goal_state(GOAL_STATE)

    start_bal = GOAL_STATE["start_balance"] or bal
    daily_start = GOAL_STATE["daily_start"] or bal

    total_profit = bal - start_bal
    daily_profit = bal - daily_start
    total_profit_pct = (total_profit / start_bal * 100) if start_bal > 0 else 0.0

    target_usd = float(GOAL_STATE.get("target_profit_usd", 20.0))
    max_loss_usd = float(GOAL_STATE.get("max_loss_usd", 10.0))
    daily_target_usd = float(GOAL_STATE.get("daily_target_usd", 5.0))

    progress = max(0.0, min(100.0, (total_profit / target_usd * 100))) if target_usd > 0 else 0.0
    daily_progress = max(0.0, min(100.0, (daily_profit / daily_target_usd * 100))) if daily_target_usd > 0 else 0.0

    status = "ACTIVE"
    if total_profit >= target_usd:
        status = "GOAL_ACHIEVED"
    elif total_profit <= -max_loss_usd:
        status = "STOP_LOSS"

    positions = []
    mt5_positions = mt5.positions_get()
    if mt5_positions:
        for p in mt5_positions:
            positions.append({
                "ticket": p.ticket,
                "symbol": p.symbol,
                "type": "BUY" if p.type == mt5.ORDER_TYPE_BUY else "SELL",
                "volume": p.volume,
                "open_price": p.price_open,
                "current_price": p.price_current,
                "sl": p.sl,
                "tp": p.tp,
                "profit": round(float(p.profit), 2),
                "time": datetime.fromtimestamp(p.time).strftime("%H:%M:%S"),
            })

    history_deals = []
    date_from = datetime.now() - timedelta(days=7)
    deals = mt5.history_deals_get(date_from, datetime.now())
    if deals:
        for d in deals:
            if d.type in (mt5.DEAL_TYPE_BUY, mt5.DEAL_TYPE_SELL) and d.entry == mt5.DEAL_ENTRY_OUT:
                history_deals.append({
                    "ticket": d.ticket,
                    "order": d.order,
                    "symbol": d.symbol,
                    "type": "BUY" if d.type == mt5.DEAL_TYPE_BUY else "SELL",
                    "volume": d.volume,
                    "price": d.price,
                    "profit": round(float(d.profit), 2),
                    "time": datetime.fromtimestamp(d.time).strftime("%Y-%m-%d %H:%M"),
                })
        history_deals.sort(key=lambda x: x["time"], reverse=True)

    return _sanitize({
        "success": True,
        "account": {
            "login": acc.login,
            "server": acc.server,
            "balance": round(bal, 2),
            "equity": round(eq, 2),
            "profit": round(acc.profit, 2),
            "margin": round(acc.margin, 2),
            "margin_free": round(acc.margin_free, 2),
            "margin_level": round(acc.margin_level, 2),
            "currency": acc.currency,
        },
        "goal": {
            "status": status,
            "start_balance": round(start_bal, 2),
            "target_profit_usd": target_usd,
            "max_loss_usd": max_loss_usd,
            "daily_target_usd": daily_target_usd,
            "total_profit": round(total_profit, 2),
            "total_profit_pct": round(total_profit_pct, 2),
            "daily_profit": round(daily_profit, 2),
            "progress": round(progress, 1),
            "daily_progress": round(daily_progress, 1),
            "remaining_usd": round(max(0.0, target_usd - total_profit), 2),
        },
        "open_positions": positions,
        "closed_trades": history_deals[:25],
    })


def execute_order(symbol: str, action: str, lot: float = 0.01, sl: float = 0.0, tp: float = 0.0, comment: str = "Bot Auto") -> Dict[str, Any]:
    if not ensure_mt5():
        return {"success": False, "error": "منصة MT5 غير متصلة"}

    tick = mt5.symbol_info_tick(symbol)
    if not tick:
        return {"success": False, "error": f"تعذر قراءة سعر السوق للرمز {symbol}"}

    order_type = mt5.ORDER_TYPE_BUY if action.upper() == "BUY" else mt5.ORDER_TYPE_SELL
    price = tick.ask if action.upper() == "BUY" else tick.bid

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": float(lot),
        "type": order_type,
        "price": price,
        "sl": float(sl) if sl > 0 else 0.0,
        "tp": float(tp) if tp > 0 else 0.0,
        "deviation": 20,
        "magic": TRADING.get("magic_number", 20241104),
        "comment": comment[:31],
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(request)
    if result is None:
        err = str(mt5.last_error())
        add_bot_log(f"❌ فشل إرسال أمر {action} {lot} {symbol}: {err}", "ERROR")
        return {"success": False, "error": err}

    if result.retcode != mt5.TRADE_RETCODE_DONE:
        err_msg = f"تم رفض الأمر ({result.retcode}): {result.comment}"
        add_bot_log(f"❌ رفض الأمر على {symbol}: {err_msg}", "ERROR")
        return {"success": False, "error": err_msg}

    msg = f"تم تنفيذ صفقة {action} {lot} {symbol} بسعر {result.price} (تذكرة #{result.order})"
    add_bot_log(f"⚡ {msg} | SL: {sl} | TP: {tp}", "SUCCESS")
    BOT_STATE["total_trades"] = BOT_STATE.get("total_trades", 0) + 1

    return {
        "success": True,
        "ticket": result.order,
        "price": result.price,
        "volume": result.volume,
        "message": msg,
    }


def close_position(ticket: int) -> Dict[str, Any]:
    if not ensure_mt5():
        return {"success": False, "error": "MT5 غير متصل"}

    pos = mt5.positions_get(ticket=ticket)
    if not pos:
        return {"success": False, "error": f"الصفقة #{ticket} غير موجودة"}

    p = pos[0]
    tick = mt5.symbol_info_tick(p.symbol)
    if not tick:
        return {"success": False, "error": "تعذر قراءة السعر اللحظي للإغلاق"}

    order_type = mt5.ORDER_TYPE_SELL if p.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
    price = tick.bid if p.type == mt5.ORDER_TYPE_BUY else tick.ask

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": p.symbol,
        "volume": p.volume,
        "type": order_type,
        "position": ticket,
        "price": price,
        "deviation": 20,
        "magic": p.magic,
        "comment": "Bot Close",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(request)
    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
        msg = f"تم إغلاق الصفقة #{ticket} بنجاح عند {price} (ربح: ${p.profit:.2f})"
        add_bot_log(f"🔒 {msg}", "INFO")
        return {"success": True, "message": msg}

    err = str(result.comment if result else mt5.last_error())
    add_bot_log(f"❌ فشل إغلاق الصفقة #{ticket}: {err}", "ERROR")
    return {"success": False, "error": err}


def close_all_positions() -> Dict[str, Any]:
    if not ensure_mt5():
        return {"success": False, "error": "MT5 غير متصل"}
    pos = mt5.positions_get()
    if not pos:
        return {"success": True, "closed_count": 0, "message": "لا توجد صفقات مفتوحة لإغلاقها"}
    closed = 0
    for p in pos:
        res = close_position(p.ticket)
        if res.get("success"):
            closed += 1
    return {"success": True, "closed_count": closed, "message": f"تم إغلاق {closed} صفقة بنجاح"}


# ===== SMART TRAILING STOP =====

def check_trailing_stops():
    """Update trailing stop for open positions."""
    if not BOT_STATE.get("trailing_stop"):
        return

    if not ensure_mt5():
        return

    positions = mt5.positions_get()
    if not positions:
        return

    for p in positions:
        try:
            info = mt5.symbol_info(p.symbol)
            tick = mt5.symbol_info_tick(p.symbol)
            if not info or not tick:
                continue

            point = info.point
            digits = info.digits
            cur_price = tick.bid if p.type == mt5.ORDER_TYPE_BUY else tick.ask
            profit_points = (cur_price - p.price_open) / point if p.type == mt5.ORDER_TYPE_BUY else (p.price_open - cur_price) / point

            # If in profit by at least 150 points (15 pips)
            min_profit_points = 150
            trail_distance_points = 120

            if profit_points >= min_profit_points:
                new_sl = 0.0
                if p.type == mt5.ORDER_TYPE_BUY:
                    candidate_sl = round(cur_price - trail_distance_points * point, digits)
                    if candidate_sl > p.sl and candidate_sl > p.price_open:
                        new_sl = candidate_sl
                else:
                    candidate_sl = round(cur_price + trail_distance_points * point, digits)
                    if (p.sl == 0.0 or candidate_sl < p.sl) and candidate_sl < p.price_open:
                        new_sl = candidate_sl

                if new_sl > 0:
                    req = {
                        "action": mt5.TRADE_ACTION_SLTP,
                        "position": p.ticket,
                        "symbol": p.symbol,
                        "sl": new_sl,
                        "tp": p.tp,
                    }
                    res = mt5.order_send(req)
                    if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                        add_bot_log(f"🛡️ تم تحديث الوقف المتحرك للصفقة #{p.ticket} ({p.symbol}) إلى {new_sl}", "INFO")
        except Exception as e:
            logger.error(f"Error trailing stop: {e}")


# ===== BOT AUTOMATION ENGINE =====

def run_bot_scan_cycle():
    """Single automated trading scan iteration."""
    if not BOT_STATE.get("running"):
        return

    if not ensure_mt5():
        return

    now_str = datetime.now().strftime("%H:%M:%S")
    BOT_STATE["last_scan"] = now_str

    # 1. Update Goal and Stop Policy
    status_data = get_goal_and_account_status()
    goal = status_data.get("goal", {})
    if goal.get("status") == "GOAL_ACHIEVED":
        add_bot_log(f"🎉 تم تحقيق الهدف المالي بالكامل! (الربح: +${goal.get('total_profit'):.2f}) - تأمين الحساب", "SUCCESS")
        BOT_STATE["running"] = False
        return

    if goal.get("status") == "STOP_LOSS":
        add_bot_log(f"🛑 تم الوصول لأقصى حد خسارة مسموح (-${goal.get('max_loss_usd'):.2f}) - إيقاف التداول للأمان", "ERROR")
        BOT_STATE["running"] = False
        return

    # 2. Check and adjust Trailing Stop
    check_trailing_stops()

    # 3. Check open positions capacity
    open_positions = status_data.get("open_positions", [])
    max_pos = int(BOT_STATE.get("max_positions", 2))
    if len(open_positions) >= max_pos:
        BOT_STATE["last_action"] = f"الحد الأقصى للصفقات مكتمل ({len(open_positions)}/{max_pos}) - جاري المراقبة"
        return

    open_symbols = {p["symbol"] for p in open_positions}
    min_conf = float(BOT_STATE.get("min_confidence", 60.0))
    lot_size = float(BOT_STATE.get("lot_size", 0.01))

    # 4. Scan Symbols
    scan_summaries = []
    for sym in BOT_STATE.get("symbols", ["XAUUSDm", "BTCUSDm", "ETHUSDm"]):
        if sym in open_symbols:
            scan_summaries.append(f"{sym}: صفقته مفتوحة")
            continue

        try:
            analysis = analyze_symbol(sym, "H1")
            if not analysis.get("success"):
                continue

            strat = analysis.get("strategy", {})
            action = strat.get("action", "WAIT")
            conf = float(strat.get("confidence", 0))
            best_strat_name = strat.get("strategy", "—")

            scan_summaries.append(f"{sym}: {action} ({conf:.0f}%)")

            # Check entry criteria
            if action in ("BUY", "SELL") and conf >= min_conf:
                entry = strat.get("entry", analysis.get("current_price"))
                sl = strat.get("sl", 0.0)
                tp = strat.get("tp", 0.0)

                add_bot_log(
                    f"🎯 رصد إشارة دخول قوية: {action} على {sym} بثقة {conf:.0f}% (استراتيجية: {best_strat_name})",
                    "TRADE"
                )

                if BOT_STATE.get("auto_trade"):
                    res = execute_order(
                        symbol=sym,
                        action=action,
                        lot=lot_size,
                        sl=sl,
                        tp=tp,
                        comment=f"{best_strat_name[:7]}_{conf:.0f}%"
                    )
                    if res.get("success"):
                        open_symbols.add(sym)
                        if len(open_symbols) >= max_pos:
                            break
        except Exception as e:
            logger.error(f"Error scanning {sym}: {e}")

    summary_text = " | ".join(scan_summaries) if scan_summaries else "تم فحص الرموز"
    BOT_STATE["last_action"] = f"آخر فحص ({now_str}): {summary_text}"


def _bot_worker_loop():
    """Background thread running the auto-trading loop."""
    time.sleep(2.0)
    add_bot_log("⚙️ محرك التداول الآلي يعمل الآن في الخلفية ويفحص الفرص دورياً", "INFO")
    while True:
        try:
            if BOT_STATE.get("running"):
                run_bot_scan_cycle()
        except Exception as e:
            logger.error(f"Error in bot worker: {e}")
        interval = max(5, int(BOT_STATE.get("scan_interval", 15)))
        time.sleep(interval)


# Start Bot Background Thread
_WORKER_THREAD = threading.Thread(target=_bot_worker_loop, daemon=True)
_WORKER_THREAD.start()


# ===== BOT CONTROLLER API HELPERS =====

def start_bot() -> Dict[str, Any]:
    BOT_STATE["running"] = True
    add_bot_log("▶️ تم تشغيل البوت الآلي والتداول التلقائي بواسطة المستخدم", "SUCCESS")
    return {"success": True, "running": True, "message": "تم تفعيل التداول الآلي بنجاح"}


def stop_bot() -> Dict[str, Any]:
    BOT_STATE["running"] = False
    add_bot_log("⏸️ تم إيقاف البوت الآلي مؤقتاً (وضع المراقبة اليدوية)", "WARN")
    return {"success": True, "running": False, "message": "تم إيقاف التداول الآلي"}


def get_bot_status() -> Dict[str, Any]:
    with BOT_LOGS_LOCK:
        logs_copy = list(BOT_LOGS[:60])
    return _sanitize({
        "success": True,
        "state": BOT_STATE,
        "logs": logs_copy,
    })


def update_bot_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    if "min_confidence" in cfg:
        BOT_STATE["min_confidence"] = float(cfg["min_confidence"])
    if "lot_size" in cfg:
        BOT_STATE["lot_size"] = float(cfg["lot_size"])
    if "max_positions" in cfg:
        BOT_STATE["max_positions"] = int(cfg["max_positions"])
    if "trailing_stop" in cfg:
        BOT_STATE["trailing_stop"] = bool(cfg["trailing_stop"])
    if "scan_interval" in cfg:
        BOT_STATE["scan_interval"] = int(cfg["scan_interval"])
    if "auto_trade" in cfg:
        BOT_STATE["auto_trade"] = bool(cfg["auto_trade"])
    if "symbols" in cfg and isinstance(cfg["symbols"], list):
        BOT_STATE["symbols"] = [str(s) for s in cfg["symbols"]]

    add_bot_log(f"⚙️ تم تحديث إعدادات البوت: ثقة={BOT_STATE['min_confidence']}%، لوت={BOT_STATE['lot_size']}، صفقات={BOT_STATE['max_positions']}", "INFO")
    return {"success": True, "state": BOT_STATE}


def execute_test_trade(symbol: str = "XAUUSDm", action: str = "BUY") -> Dict[str, Any]:
    """Execute an immediate test trade (0.01 lot) to confirm live MT5 order placement."""
    add_bot_log(f"⚡ طلب تنفيذ صفقة تجريبية فورية على {symbol} ({action})...", "INFO")
    analysis = analyze_symbol(symbol, "H1")
    entry = analysis.get("current_price", 0.0)
    atr = analysis.get("indicators", {}).get("atr", {}).get("value", entry * 0.001) or entry * 0.001
    digits = analysis.get("digits", 2)

    if action.upper() == "BUY":
        sl = round(entry - atr * 1.5, digits)
        tp = round(entry + atr * 2.5, digits)
    else:
        sl = round(entry + atr * 1.5, digits)
        tp = round(entry - atr * 2.5, digits)

    return execute_order(symbol, action, lot=0.01, sl=sl, tp=tp, comment="Test Trade")
