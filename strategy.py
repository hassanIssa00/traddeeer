"""
=============================================================
  Trading Bot - Strategy Engine
  محرك الاستراتيجيات (4 استراتيجيات)
=============================================================
  Strategy 1: Trend Following   (EMA Cross + ADX + MACD)
  Strategy 2: Mean Reversion    (BB + RSI + Stochastic)
  Strategy 3: Breakout          (Donchian + Volume + ATR)
  Strategy 4: MACD Divergence   (MACD + RSI + Patterns)
=============================================================
"""
import logging
from typing import Optional

import numpy as np
import pandas as pd

from config import TRADING, INDICATORS as CFG

logger = logging.getLogger(__name__)


# ===== STRATEGY BASE =====

def _build_signal(
    action: str,
    confidence: float,
    strategy: str,
    reason: str,
    entry: float,
    sl: float,
    tp: float,
    score: float,
) -> dict:
    """Build a standardized signal dict."""
    return {
        "action":     action,       # BUY / SELL / WAIT
        "confidence": round(float(confidence), 1),   # 0-100%
        "strategy":   strategy,
        "reason":     reason,
        "entry":      round(float(entry), 5),
        "sl":         round(float(sl), 5) if sl else 0.0,
        "tp":         round(float(tp), 5) if tp else 0.0,
        "score":      round(float(score), 3),
    }


# ===== STRATEGY 1: TREND FOLLOWING =====

def strategy_trend_following(df: pd.DataFrame, ind: dict, sym_info: dict) -> dict:
    """
    EMA Cross + ADX + MACD Trend Following.
    Entry: EMA alignment + ADX > 20 + MACD confirmation.
    """
    ema   = ind.get("ema", {})
    adx   = ind.get("adx", {})
    macd  = ind.get("macd", {})
    rsi   = ind.get("rsi", {})

    e20  = ema.get("ema20")
    e50  = ema.get("ema50")
    e200 = ema.get("ema200")
    adx_v = adx.get("adx", 0) or 0
    pdi   = adx.get("+di", 0) or 0
    mdi   = adx.get("-di", 0) or 0
    macd_v = macd.get("macd", 0) or 0
    macd_s = macd.get("signal_line", 0) or 0
    rsi_v  = rsi.get("value", 50) or 50
    cur    = df["close"].iloc[-1]
    atr    = ind.get("atr", {}).get("value", cur * 0.001) or cur * 0.001

    if not all([e20, e50, e200]):
        return _build_signal("WAIT", 10.0, "TrendFollowing", "بيانات EMA غير مكتملة", cur, 0, 0, 0)

    buy_conditions = [
        e20 > e50,           # EMA cross bullish
        e50 > e200,          # Long term uptrend
        cur > e20,           # Price above fast EMA
        adx_v > 20,          # Trending market
        pdi > mdi,           # +DI > -DI
        macd_v > macd_s,     # MACD bullish
        35 < rsi_v < 70,     # RSI not overbought
    ]
    sell_conditions = [
        e20 < e50,
        e50 < e200,
        cur < e20,
        adx_v > 20,
        mdi > pdi,
        macd_v < macd_s,
        30 < rsi_v < 65,
    ]

    buy_score  = sum(buy_conditions)
    sell_score = sum(sell_conditions)
    total      = len(buy_conditions)

    if buy_score >= 5:
        conf = (buy_score / total) * 100
        sl   = round(cur - atr * 1.5, sym_info.get("digits", 5))
        tp   = round(cur + atr * 3.0, sym_info.get("digits", 5))
        return _build_signal("BUY", conf, "TrendFollowing",
                             f"متوسطات صاعدة متوافقة، ADX={adx_v:.0f}، ماكد إيجابي ({buy_score}/{total})",
                             cur, sl, tp, buy_score / total)

    if sell_score >= 5:
        conf = (sell_score / total) * 100
        sl   = round(cur + atr * 1.5, sym_info.get("digits", 5))
        tp   = round(cur - atr * 3.0, sym_info.get("digits", 5))
        return _build_signal("SELL", conf, "TrendFollowing",
                             f"متوسطات هابطة متوافقة، ADX={adx_v:.0f}، ماكد سلبي ({sell_score}/{total})",
                             cur, sl, tp, -sell_score / total)

    # Partial alignment confidence
    max_score = max(buy_score, sell_score)
    partial_conf = round((max_score / total) * 80, 1)
    direction_hint = "شراء جزئي" if buy_score > sell_score else "بيع جزئي" if sell_score > buy_score else "حياد تام"
    return _build_signal("WAIT", partial_conf, "TrendFollowing",
                         f"اتجاه غير مكتمل: {direction_hint} ({max_score}/{total}) | ADX={adx_v:.0f}",
                         cur, 0, 0, (buy_score - sell_score) / total)


# ===== STRATEGY 2: MEAN REVERSION =====

def strategy_mean_reversion(df: pd.DataFrame, ind: dict, sym_info: dict) -> dict:
    """
    Bollinger Bands + RSI + Stochastic Mean Reversion.
    Entry: Price at extreme + oversold/overbought confluence.
    """
    bb    = ind.get("bollinger", {})
    rsi   = ind.get("rsi", {})
    stoch = ind.get("stochastic", {})
    adx   = ind.get("adx", {})

    pct_b  = bb.get("pct_b", 0.5) or 0.5
    rsi_v  = rsi.get("value", 50) or 50
    k      = stoch.get("k", 50) or 50
    d      = stoch.get("d", 50) or 50
    adx_v  = adx.get("adx", 0) or 0
    cur    = df["close"].iloc[-1]
    atr    = ind.get("atr", {}).get("value", cur * 0.001) or cur * 0.001

    # Mean reversion works best in ranging markets (low ADX)
    ranging = adx_v < 30

    buy_conds = [
        pct_b < 0.15,     # Near or below lower BB
        rsi_v < 38,       # RSI oversold
        k < 25,           # Stoch oversold
        k > d,            # Stoch turning up
        ranging,          # Ranging market
    ]
    sell_conds = [
        pct_b > 0.85,
        rsi_v > 65,
        k > 75,
        k < d,
        ranging,
    ]

    buy_score  = sum(buy_conds)
    sell_score = sum(sell_conds)
    total      = len(buy_conds)

    if buy_score >= 3:
        conf = (buy_score / total) * 100
        sl   = round(cur - atr * 1.2, sym_info.get("digits", 5))
        tp   = round((bb.get("mid") or cur + atr * 2), sym_info.get("digits", 5))
        return _build_signal("BUY", conf, "MeanReversion",
                             f"تشبع بيعي عند بولينجر السفلي: RSI={rsi_v:.0f} Stoch={k:.0f} ({buy_score}/{total})",
                             cur, sl, tp, buy_score / total)

    if sell_score >= 3:
        conf = (sell_score / total) * 100
        sl   = round(cur + atr * 1.2, sym_info.get("digits", 5))
        tp   = round((bb.get("mid") or cur - atr * 2), sym_info.get("digits", 5))
        return _build_signal("SELL", conf, "MeanReversion",
                             f"تشبع شرائي عند بولينجر العلوي: RSI={rsi_v:.0f} Stoch={k:.0f} ({sell_score}/{total})",
                             cur, sl, tp, -sell_score / total)

    # Return partial score
    max_score = max(buy_score, sell_score)
    partial_conf = round((max_score / total) * 75, 1)
    return _build_signal("WAIT", partial_conf, "MeanReversion",
                         f"توازن سعري: RSI={rsi_v:.0f} | بولينجر %B={pct_b:.2f} ({max_score}/{total})",
                         cur, 0, 0, (buy_score - sell_score) / total)


# ===== STRATEGY 3: BREAKOUT =====

def strategy_breakout(df: pd.DataFrame, ind: dict, sym_info: dict) -> dict:
    """
    Donchian Channel Breakout + Volume confirmation.
    Entry: Price breaks N-period high/low with high volume.
    """
    don   = ind.get("donchian", {})
    vol   = ind.get("volume", {})
    atr   = ind.get("atr", {})

    upper = don.get("upper")
    lower = don.get("lower")
    vol_ratio = vol.get("ratio", 1.0) or 1.0
    cur    = df["close"].iloc[-1]
    prev_h = df["high"].iloc[-2] if len(df) > 1 else cur
    prev_l = df["low"].iloc[-2] if len(df) > 1 else cur

    if not upper or not lower:
        return _build_signal("WAIT", 10.0, "Breakout", "بيانات قناة دونكيان غير متوفرة", cur, 0, 0, 0)

    high_vol = vol_ratio > 1.25
    breakout_up   = cur >= upper * 0.9995 and prev_h >= upper * 0.998
    breakout_down = cur <= lower * 1.0005 and prev_l <= lower * 1.002

    if breakout_up and high_vol:
        conf = min(92.0, 60.0 + vol_ratio * 10)
        sl   = round(lower, sym_info.get("digits", 5))
        tp   = round(cur + (cur - lower) * 0.5, sym_info.get("digits", 5))
        return _build_signal("BUY", conf, "Breakout",
                             f"اختراق صاعد لقناة دونكيان ({upper:.2f}) مع سيولة {vol_ratio:.1f}x",
                             cur, sl, tp, 0.8)

    if breakout_down and high_vol:
        conf = min(92.0, 60.0 + vol_ratio * 10)
        sl   = round(upper, sym_info.get("digits", 5))
        tp   = round(cur - (upper - cur) * 0.5, sym_info.get("digits", 5))
        return _build_signal("SELL", conf, "Breakout",
                             f"كسر هابط لقناة دونكيان ({lower:.2f}) مع سيولة {vol_ratio:.1f}x",
                             cur, sl, tp, -0.8)

    # Calculate distance to boundary
    ch_range = max(0.001, upper - lower)
    dist_up = max(0.0, (upper - cur) / ch_range)
    dist_dn = max(0.0, (cur - lower) / ch_range)
    edge_proximity = max(0.0, 1.0 - min(dist_up, dist_dn) * 2)
    partial_conf = round(edge_proximity * 45 + (15 if vol_ratio > 1.0 else 0), 1)

    return _build_signal("WAIT", partial_conf, "Breakout",
                         f"السعر داخل القناة (أعلى: {upper:.2f}، أدنى: {lower:.2f}) | حجم: {vol_ratio:.1f}x",
                         cur, 0, 0, 0)


# ===== STRATEGY 4: MACD DIVERGENCE =====

def strategy_macd_divergence(df: pd.DataFrame, ind: dict, sym_info: dict) -> dict:
    """
    MACD Divergence + RSI Recovery + Pattern Confirmation.
    Bullish: Price makes lower low but MACD higher low.
    Bearish: Price makes higher high but MACD lower high.
    """
    macd  = ind.get("macd", {})
    rsi   = ind.get("rsi", {})
    pat   = ind.get("patterns", {})

    rsi_v     = rsi.get("value", 50) or 50
    rsi_prev  = rsi.get("prev", 50) or 50
    hist      = macd.get("hist", 0) or 0
    patterns  = pat.get("patterns", {})
    cur       = df["close"].iloc[-1]
    atr       = ind.get("atr", {}).get("value", cur * 0.001) or cur * 0.001

    close_arr = df["close"].values
    n = min(20, len(close_arr) - 1)

    if n < 6:
        return _build_signal("WAIT", 15.0, "MACDDivergence", "بيانات غير كافية لحساب الدايفرجنس", cur, 0, 0, 0)

    price_low_now  = cur
    price_low_prev = min(close_arr[-n:-n//2])
    price_hi_now   = cur
    price_hi_prev  = max(close_arr[-n:-n//2])

    bullish_div = (
        price_low_now < price_low_prev and
        rsi_v > rsi_prev and
        rsi_v < 48 and
        hist > 0
    )
    bearish_div = (
        price_hi_now > price_hi_prev and
        rsi_v < rsi_prev and
        rsi_v > 52 and
        hist < 0
    )

    bullish_pat = any(p in patterns for p in ["Hammer", "Morning_Star", "Bullish_Engulf", "Piercing"])
    bearish_pat = any(p in patterns for p in ["Shooting_Star", "Evening_Star", "Dark_Cloud"])

    if bullish_div:
        conf = 65.0 + (10.0 if bullish_pat else 0.0)
        sl   = round(cur - atr * 2.0, sym_info.get("digits", 5))
        tp   = round(cur + atr * 4.0, sym_info.get("digits", 5))
        return _build_signal("BUY", conf, "MACDDivergence",
                             f"دايفرجنس شرائي: RSI={rsi_v:.0f} صاعد مع تحول هيستوجرام الماكد لإيجابي",
                             cur, sl, tp, 0.75)

    if bearish_div:
        conf = 65.0 + (10.0 if bearish_pat else 0.0)
        sl   = round(cur + atr * 2.0, sym_info.get("digits", 5))
        tp   = round(cur - atr * 4.0, sym_info.get("digits", 5))
        return _build_signal("SELL", conf, "MACDDivergence",
                             f"دايفرجنس بيعي: RSI={rsi_v:.0f} هابط مع تحول هيستوجرام الماكد لسلبي",
                             cur, sl, tp, -0.75)

    # Check partial divergence tendency
    div_tendency = 30.0
    if abs(hist) > 0.05:
        div_tendency += 15.0
    if bullish_pat or bearish_pat:
        div_tendency += 15.0

    return _build_signal("WAIT", div_tendency, "MACDDivergence",
                         f"لا يوجد دايفرجنس حاسم | RSI={rsi_v:.0f}، ماكد Hist={hist:.3f}",
                         cur, 0, 0, 0)


# ===== MASTER STRATEGY ENGINE =====

def get_signal(symbol: str, df: pd.DataFrame, ind: dict, sym_info: dict) -> dict:
    """
    Run all 4 strategies and return the best signal along with detailed status for all 4.
    """
    sig_tf   = strategy_trend_following(df, ind, sym_info)
    sig_mr   = strategy_mean_reversion(df, ind, sym_info)
    sig_bo   = strategy_breakout(df, ind, sym_info)
    sig_macd = strategy_macd_divergence(df, ind, sym_info)

    all_strategies = {
        "TrendFollowing": sig_tf,
        "MeanReversion":  sig_mr,
        "Breakout":       sig_bo,
        "MACDDivergence": sig_macd,
    }
    all_list = [sig_tf, sig_mr, sig_bo, sig_macd]

    # Find active signals (non-WAIT)
    active = [s for s in all_list if s["action"] != "WAIT"]

    min_conf = TRADING.get("min_confidence", 60.0)

    # If no active signals, choose the one with the highest partial confidence as hint
    if not active:
        best_candidate = max(all_list, key=lambda s: s["confidence"])
        out = {
            "action": "WAIT",
            "confidence": best_candidate["confidence"],
            "strategy": best_candidate["strategy"],
            "reason": best_candidate["reason"],
            "entry": best_candidate["entry"],
            "sl": 0.0,
            "tp": 0.0,
            "score": 0.0,
            "votes": 0,
            "strategies": all_strategies,
            "all_signals": all_list,
        }
        return out

    # Group by direction
    buy_votes  = [s for s in active if s["action"] == "BUY"]
    sell_votes = [s for s in active if s["action"] == "SELL"]

    winner = None
    if len(buy_votes) >= len(sell_votes) and buy_votes:
        top_buy = max(buy_votes, key=lambda s: s["confidence"])
        if top_buy["confidence"] >= min_conf:
            winner = dict(top_buy)
            winner["votes"] = len(buy_votes)

    if not winner and sell_votes:
        top_sell = max(sell_votes, key=lambda s: s["confidence"])
        if top_sell["confidence"] >= min_conf:
            winner = dict(top_sell)
            winner["votes"] = len(sell_votes)

    if winner:
        winner["strategies"] = all_strategies
        winner["all_signals"] = all_list
        return winner

    # No strategy crossed min_conf threshold
    highest = max(active, key=lambda s: s["confidence"])
    return {
        "action": "WAIT",
        "confidence": highest["confidence"],
        "strategy": highest["strategy"],
        "reason": f"إشارة {highest['action']} دون حد الثقة الأدنى ({highest['confidence']:.0f}% < {min_conf}%)",
        "entry": highest["entry"],
        "sl": 0.0,
        "tp": 0.0,
        "score": 0.0,
        "votes": len(buy_votes) if highest["action"] == "BUY" else len(sell_votes),
        "strategies": all_strategies,
        "all_signals": all_list,
    }
