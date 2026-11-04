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
        "confidence": confidence,   # 0-100%
        "strategy":   strategy,
        "reason":     reason,
        "entry":      entry,
        "sl":         sl,
        "tp":         tp,
        "score":      score,
    }


# ===== STRATEGY 1: TREND FOLLOWING =====

def strategy_trend_following(df: pd.DataFrame, ind: dict, sym_info: dict) -> dict:
    """
    EMA Cross + ADX + MACD Trend Following.
    Entry: EMA alignment + ADX > 25 + MACD confirmation.
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
        return _build_signal("WAIT", 0, "TrendFollowing", "Missing EMA data", cur, 0, 0, 0)

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
                             f"EMA aligned bullish, ADX={adx_v:.0f}, MACD bullish ({buy_score}/{total})",
                             cur, sl, tp, buy_score / total)

    if sell_score >= 5:
        conf = (sell_score / total) * 100
        sl   = round(cur + atr * 1.5, sym_info.get("digits", 5))
        tp   = round(cur - atr * 3.0, sym_info.get("digits", 5))
        return _build_signal("SELL", conf, "TrendFollowing",
                             f"EMA aligned bearish, ADX={adx_v:.0f}, MACD bearish ({sell_score}/{total})",
                             cur, sl, tp, -sell_score / total)

    return _build_signal("WAIT", 0, "TrendFollowing", f"No trend: buy={buy_score} sell={sell_score}", cur, 0, 0, 0)


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

    upper  = bb.get("upper")
    lower  = bb.get("lower")
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
        pct_b < 0.1,      # Near or below lower BB
        rsi_v < 35,       # RSI oversold
        k < 25,           # Stoch oversold
        k > d,            # Stoch turning up
        ranging,          # Ranging market
    ]
    sell_conds = [
        pct_b > 0.9,
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
                             f"Oversold at BB lower: RSI={rsi_v:.0f} Stoch={k:.0f} ({buy_score}/{total})",
                             cur, sl, tp, buy_score / total)

    if sell_score >= 3:
        conf = (sell_score / total) * 100
        sl   = round(cur + atr * 1.2, sym_info.get("digits", 5))
        tp   = round((bb.get("mid") or cur - atr * 2), sym_info.get("digits", 5))
        return _build_signal("SELL", conf, "MeanReversion",
                             f"Overbought at BB upper: RSI={rsi_v:.0f} Stoch={k:.0f} ({sell_score}/{total})",
                             cur, sl, tp, -sell_score / total)

    return _build_signal("WAIT", 0, "MeanReversion", f"No extreme: RSI={rsi_v:.0f} %B={pct_b:.2f}", cur, 0, 0, 0)


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
    atr_v  = atr.get("value", 0) or 0
    cur    = df["close"].iloc[-1]
    prev_h = df["high"].iloc[-2]
    prev_l = df["low"].iloc[-2]

    if not upper or not lower:
        return _build_signal("WAIT", 0, "Breakout", "Missing Donchian data", cur, 0, 0, 0)

    high_vol = vol_ratio > 1.3  # 30% above average volume
    breakout_up   = cur >= upper and prev_h >= upper * 0.999
    breakout_down = cur <= lower and prev_l <= lower * 1.001

    if breakout_up and high_vol:
        conf = min(90, 60 + vol_ratio * 10)
        sl   = round(lower, sym_info.get("digits", 5))
        tp   = round(cur + (cur - lower) * 0.5, sym_info.get("digits", 5))
        return _build_signal("BUY", conf, "Breakout",
                             f"Breakout above {upper:.5f} with vol={vol_ratio:.1f}x",
                             cur, sl, tp, 0.8)

    if breakout_down and high_vol:
        conf = min(90, 60 + vol_ratio * 10)
        sl   = round(upper, sym_info.get("digits", 5))
        tp   = round(cur - (upper - cur) * 0.5, sym_info.get("digits", 5))
        return _build_signal("SELL", conf, "Breakout",
                             f"Breakout below {lower:.5f} with vol={vol_ratio:.1f}x",
                             cur, sl, tp, -0.8)

    return _build_signal("WAIT", 0, "Breakout",
                         f"No breakout: cur={cur:.5f} H={upper:.5f} L={lower:.5f} vol={vol_ratio:.1f}x",
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
    macd_v    = macd.get("macd", 0) or 0
    patterns  = pat.get("patterns", {})
    cur       = df["close"].iloc[-1]
    atr       = ind.get("atr", {}).get("value", cur * 0.001) or cur * 0.001

    # Look for divergence over last 20 bars
    close_arr = df["close"].values
    n = min(20, len(close_arr) - 1)

    price_low_now  = cur
    price_low_prev = min(close_arr[-n:-n//2])
    price_hi_now   = cur
    price_hi_prev  = max(close_arr[-n:-n//2])

    bullish_div = (
        price_low_now < price_low_prev and  # Price: lower low
        rsi_v > rsi_prev and               # RSI: higher low (divergence)
        rsi_v < 45 and                     # RSI still below mid
        hist > 0                           # MACD hist turning positive
    )
    bearish_div = (
        price_hi_now > price_hi_prev and
        rsi_v < rsi_prev and
        rsi_v > 55 and
        hist < 0
    )

    bullish_pat = any(p in patterns for p in ["Hammer", "Morning_Star", "Bullish_Engulf", "Piercing"])
    bearish_pat = any(p in patterns for p in ["Shooting_Star", "Evening_Star", "Dark_Cloud"])

    if bullish_div:
        conf = 65 + (10 if bullish_pat else 0)
        sl   = round(cur - atr * 2.0, sym_info.get("digits", 5))
        tp   = round(cur + atr * 4.0, sym_info.get("digits", 5))
        return _build_signal("BUY", conf, "MACDDivergence",
                             f"Bullish divergence: RSI={rsi_v:.0f} recovering, MACD hist turning positive",
                             cur, sl, tp, 0.75)

    if bearish_div:
        conf = 65 + (10 if bearish_pat else 0)
        sl   = round(cur + atr * 2.0, sym_info.get("digits", 5))
        tp   = round(cur - atr * 4.0, sym_info.get("digits", 5))
        return _build_signal("SELL", conf, "MACDDivergence",
                             f"Bearish divergence: RSI={rsi_v:.0f} declining, MACD hist negative",
                             cur, sl, tp, -0.75)

    return _build_signal("WAIT", 0, "MACDDivergence", "No divergence detected", cur, 0, 0, 0)


# ===== MASTER STRATEGY ENGINE =====

def get_signal(symbol: str, df: pd.DataFrame, ind: dict, sym_info: dict) -> dict:
    """
    Run all 4 strategies and return the best signal.
    Only returns non-WAIT signal if confidence >= min_confidence.
    """
    strategies = [
        strategy_trend_following,
        strategy_mean_reversion,
        strategy_breakout,
        strategy_macd_divergence,
    ]

    results = []
    for fn in strategies:
        try:
            sig = fn(df, ind, sym_info)
            results.append(sig)
            logger.debug(f"{symbol} | {sig['strategy']}: {sig['action']} conf={sig['confidence']:.0f}%")
        except Exception as e:
            logger.error(f"Strategy error {fn.__name__}: {e}")

    # Filter non-WAIT signals
    active = [r for r in results if r["action"] != "WAIT"]

    if not active:
        return _build_signal("WAIT", 0, "None", "No strategy triggered", df["close"].iloc[-1], 0, 0, 0)

    # Count votes
    buy_votes  = [r for r in active if r["action"] == "BUY"]
    sell_votes = [r for r in active if r["action"] == "SELL"]

    min_conf = TRADING["min_confidence"]

    # Consensus: pick direction with more votes
    if len(buy_votes) >= len(sell_votes) and buy_votes:
        # Pick highest confidence BUY
        best = max(buy_votes, key=lambda x: x["confidence"])
        if best["confidence"] >= min_conf:
            best["votes"]      = len(buy_votes)
            best["all_signals"]= results
            return best

    if len(sell_votes) > len(buy_votes) and sell_votes:
        best = max(sell_votes, key=lambda x: x["confidence"])
        if best["confidence"] >= min_conf:
            best["votes"]      = len(sell_votes)
            best["all_signals"]= results
            return best

    return _build_signal(
        "WAIT", 0, "Consensus",
        f"No consensus: BUY={len(buy_votes)} SELL={len(sell_votes)} (min conf={min_conf}%)",
        df["close"].iloc[-1], 0, 0, 0,
    )
