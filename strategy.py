"""
=============================================================
  Trading Bot - Strategy Engine  (v2 - Fixed Logic)
  محرك الاستراتيجيات — لوجيك قوي مع Consensus + Multi-TF
=============================================================
  Strategy 1: Trend Following   (EMA Cross + ADX + MACD)
  Strategy 2: Mean Reversion    (BB + RSI + Stochastic)
  Strategy 3: Breakout          (Donchian + Volume + ATR)
  Strategy 4: MACD Divergence   (MACD + RSI + Patterns)
=============================================================
  Entry Rules:
  - Minimum 2 strategies agree on direction
  - Confidence >= 70% for real entry (configurable)
  - If 3-4 strategies agree → STRONG signal (90%+ conf)
  - SL/TP calculated properly per symbol digits
=============================================================
"""
import logging
from typing import Optional

import numpy as np
import pandas as pd

from config import TRADING, INDICATORS as CFG

logger = logging.getLogger(__name__)


# ===== SIGNAL BUILDER =====

def _build_signal(
    action: str,
    confidence: float,
    strategy: str,
    reason: str,
    entry: float,
    sl: float,
    tp: float,
    score: float,
    digits: int = 5,
) -> dict:
    """Build a standardized signal dict with proper rounding."""
    return {
        "action":     action,
        "confidence": round(float(confidence), 1),
        "strategy":   strategy,
        "reason":     reason,
        "entry":      round(float(entry), digits),
        "sl":         round(float(sl), digits) if sl else 0.0,
        "tp":         round(float(tp), digits) if tp else 0.0,
        "score":      round(float(score), 3),
    }


def _get_digits(sym_info: dict) -> int:
    return int(sym_info.get("digits", 5))


def _get_atr(ind: dict, cur: float) -> float:
    """Get ATR, fallback to 0.1% of price."""
    atr = ind.get("atr", {}).get("value") or 0
    return float(atr) if atr and atr > 0 else cur * 0.001


# ===== STRATEGY 1: TREND FOLLOWING =====

def strategy_trend_following(df: pd.DataFrame, ind: dict, sym_info: dict) -> dict:
    """
    EMA Cross + ADX + MACD Trend Following.
    Strong trend identification — requires 5/7 conditions.
    """
    digits = _get_digits(sym_info)
    ema    = ind.get("ema", {})
    adx    = ind.get("adx", {})
    macd   = ind.get("macd", {})
    rsi    = ind.get("rsi", {})

    e20   = ema.get("ema20")
    e50   = ema.get("ema50")
    e200  = ema.get("ema200")
    adx_v = float(adx.get("adx", 0) or 0)
    pdi   = float(adx.get("+di", 0) or 0)
    mdi   = float(adx.get("-di", 0) or 0)
    macd_v = float(macd.get("macd", 0) or 0)
    macd_s = float(macd.get("signal_line", 0) or 0)
    rsi_v  = float(rsi.get("value", 50) or 50)
    cur    = float(df["close"].iloc[-1])
    atr    = _get_atr(ind, cur)

    if not all([e20, e50, e200]):
        return _build_signal("WAIT", 10.0, "TrendFollowing", "بيانات EMA غير مكتملة", cur, 0, 0, 0, digits)

    e20, e50, e200 = float(e20), float(e50), float(e200)

    buy_conditions = [
        e20 > e50,              # EMA bullish cross
        e50 > e200,             # Long-term uptrend
        cur > e50,              # Price above medium EMA
        adx_v > 25,             # Strong trend (raised from 20)
        pdi > mdi,              # +DI dominates
        macd_v > macd_s,        # MACD bullish
        30 < rsi_v < 65,        # RSI healthy zone
    ]
    sell_conditions = [
        e20 < e50,
        e50 < e200,
        cur < e50,
        adx_v > 25,
        mdi > pdi,
        macd_v < macd_s,
        35 < rsi_v < 70,
    ]

    buy_score  = sum(buy_conditions)
    sell_score = sum(sell_conditions)
    total      = len(buy_conditions)

    if buy_score >= 5:
        conf = 60.0 + (buy_score / total) * 40.0   # 60-100%
        sl   = round(cur - atr * 1.5, digits)
        tp   = round(cur + atr * 3.0, digits)
        return _build_signal("BUY", conf, "TrendFollowing",
                             f"تريند صاعد قوي: EMA متوافقة، ADX={adx_v:.0f}، MACD إيجابي ({buy_score}/{total})",
                             cur, sl, tp, buy_score / total, digits)

    if sell_score >= 5:
        conf = 60.0 + (sell_score / total) * 40.0
        sl   = round(cur + atr * 1.5, digits)
        tp   = round(cur - atr * 3.0, digits)
        return _build_signal("SELL", conf, "TrendFollowing",
                             f"تريند هابط قوي: EMA متوافقة، ADX={adx_v:.0f}، MACD سلبي ({sell_score}/{total})",
                             cur, sl, tp, -sell_score / total, digits)

    max_score   = max(buy_score, sell_score)
    partial_conf = round((max_score / total) * 55.0, 1)
    direction   = "صاعد جزئي" if buy_score > sell_score else "هابط جزئي" if sell_score > buy_score else "محايد"
    return _build_signal("WAIT", partial_conf, "TrendFollowing",
                         f"تريند غير مكتمل: {direction} ({max_score}/{total}) | ADX={adx_v:.0f}",
                         cur, 0, 0, (buy_score - sell_score) / total, digits)


# ===== STRATEGY 2: MEAN REVERSION =====

def strategy_mean_reversion(df: pd.DataFrame, ind: dict, sym_info: dict) -> dict:
    """
    Bollinger Bands + RSI + Stochastic Mean Reversion.
    Works in ranging markets (ADX < 25).
    """
    digits = _get_digits(sym_info)
    bb    = ind.get("bollinger", {})
    rsi   = ind.get("rsi", {})
    stoch = ind.get("stochastic", {})
    adx   = ind.get("adx", {})

    pct_b  = float(bb.get("pct_b", 0.5) or 0.5)
    rsi_v  = float(rsi.get("value", 50) or 50)
    k      = float(stoch.get("k", 50) or 50)
    d      = float(stoch.get("d", 50) or 50)
    adx_v  = float(adx.get("adx", 0) or 0)
    cur    = float(df["close"].iloc[-1])
    atr    = _get_atr(ind, cur)
    bb_mid = bb.get("mid")
    bb_mid = float(bb_mid) if bb_mid else cur

    # Mean reversion requires ranging market
    ranging = adx_v < 25

    buy_conds = [
        pct_b < 0.1,       # At or below lower BB (tightened from 0.15)
        rsi_v < 35,        # RSI clearly oversold
        k < 25,            # Stoch oversold
        k > d,             # Stoch turning up
        ranging,           # Ranging market
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
        conf = 55.0 + (buy_score / total) * 45.0
        sl   = round(cur - atr * 1.2, digits)
        tp   = round(bb_mid, digits)   # TP = mean (middle BB)
        # Ensure TP > entry for BUY
        if tp <= cur:
            tp = round(cur + atr * 2.0, digits)
        return _build_signal("BUY", conf, "MeanReversion",
                             f"ارتداد من القاع: RSI={rsi_v:.0f} تشبع بيعي، BB%={pct_b:.2f} ({buy_score}/{total})",
                             cur, sl, tp, buy_score / total, digits)

    if sell_score >= 3:
        conf = 55.0 + (sell_score / total) * 45.0
        sl   = round(cur + atr * 1.2, digits)
        tp   = round(bb_mid, digits)   # TP = mean
        if tp >= cur:
            tp = round(cur - atr * 2.0, digits)
        return _build_signal("SELL", conf, "MeanReversion",
                             f"ارتداد من القمة: RSI={rsi_v:.0f} تشبع شرائي، BB%={pct_b:.2f} ({sell_score}/{total})",
                             cur, sl, tp, -sell_score / total, digits)

    max_score   = max(buy_score, sell_score)
    partial_conf = round((max_score / total) * 50.0, 1)
    return _build_signal("WAIT", partial_conf, "MeanReversion",
                         f"توازن: RSI={rsi_v:.0f} | BB%={pct_b:.2f} | ADX={adx_v:.0f} ({max_score}/{total})",
                         cur, 0, 0, (buy_score - sell_score) / total, digits)


# ===== STRATEGY 3: BREAKOUT =====

def strategy_breakout(df: pd.DataFrame, ind: dict, sym_info: dict) -> dict:
    """
    Donchian Channel Breakout + Volume + ATR confirmation.
    """
    digits = _get_digits(sym_info)
    don    = ind.get("donchian", {})
    vol    = ind.get("volume", {})
    atr    = _get_atr(ind, float(df["close"].iloc[-1]))

    upper     = don.get("upper")
    lower     = don.get("lower")
    vol_ratio = float(vol.get("ratio", 1.0) or 1.0)
    cur       = float(df["close"].iloc[-1])

    if not upper or not lower:
        return _build_signal("WAIT", 10.0, "Breakout", "بيانات دونكيان غير متوفرة", cur, 0, 0, 0, digits)

    upper = float(upper)
    lower = float(lower)

    # Volume must be above average for valid breakout
    high_vol      = vol_ratio > 1.3   # Raised from 1.25
    breakout_up   = cur >= upper * 0.9998
    breakout_down = cur <= lower * 1.0002

    if breakout_up and high_vol:
        conf = min(90.0, 65.0 + vol_ratio * 8.0)
        sl   = round(lower, digits)   # SL below channel
        tp   = round(cur + (cur - lower) * 0.618, digits)  # Fibonacci extension
        if tp <= cur:
            tp = round(cur + atr * 3.0, digits)
        return _build_signal("BUY", conf, "Breakout",
                             f"اختراق صاعد مؤكد: كسر {upper:.4f} مع سيولة {vol_ratio:.1f}x",
                             cur, sl, tp, 0.85, digits)

    if breakout_down and high_vol:
        conf = min(90.0, 65.0 + vol_ratio * 8.0)
        sl   = round(upper, digits)
        tp   = round(cur - (upper - cur) * 0.618, digits)
        if tp >= cur:
            tp = round(cur - atr * 3.0, digits)
        return _build_signal("SELL", conf, "Breakout",
                             f"اختراق هابط مؤكد: كسر {lower:.4f} مع سيولة {vol_ratio:.1f}x",
                             cur, sl, tp, -0.85, digits)

    # Proximity to channel edge
    ch_range       = max(0.001, upper - lower)
    dist_up        = (upper - cur) / ch_range
    dist_dn        = (cur - lower) / ch_range
    edge_proximity = max(0.0, 1.0 - min(dist_up, dist_dn) * 2)
    partial_conf   = round(edge_proximity * 40.0 + (10.0 if vol_ratio > 1.1 else 0), 1)

    return _build_signal("WAIT", partial_conf, "Breakout",
                         f"داخل القناة (أعلى:{upper:.4f} أدنى:{lower:.4f}) | حجم:{vol_ratio:.1f}x",
                         cur, 0, 0, 0, digits)


# ===== STRATEGY 4: MACD DIVERGENCE =====

def strategy_macd_divergence(df: pd.DataFrame, ind: dict, sym_info: dict) -> dict:
    """
    MACD Divergence + RSI Recovery + Candlestick Pattern Confirmation.
    """
    digits = _get_digits(sym_info)
    macd   = ind.get("macd", {})
    rsi    = ind.get("rsi", {})
    pat    = ind.get("patterns", {})

    rsi_v     = float(rsi.get("value", 50) or 50)
    rsi_prev  = float(rsi.get("prev", 50) or 50)
    hist      = float(macd.get("hist", 0) or 0)
    hist_prev = float(macd.get("hist_prev", hist) or hist)
    patterns  = pat.get("patterns", {}) if isinstance(pat.get("patterns"), dict) else {}
    cur       = float(df["close"].iloc[-1])
    atr       = _get_atr(ind, cur)

    close_arr = df["close"].values.astype(float)
    n = min(20, len(close_arr) - 1)

    if n < 6:
        return _build_signal("WAIT", 15.0, "MACDDivergence", "بيانات غير كافية", cur, 0, 0, 0, digits)

    half = n // 2
    price_low_prev  = float(np.min(close_arr[-n:-half]))
    price_hi_prev   = float(np.max(close_arr[-n:-half]))

    # Bullish Divergence: Price lower low, RSI higher low, MACD hist turning up
    bullish_div = (
        cur < price_low_prev and      # Price at new low
        rsi_v > rsi_prev and          # RSI making higher low (divergence)
        rsi_v < 50 and               # RSI still in lower zone
        hist > hist_prev             # MACD histogram improving
    )
    # Bearish Divergence: Price higher high, RSI lower high, MACD hist turning down
    bearish_div = (
        cur > price_hi_prev and
        rsi_v < rsi_prev and
        rsi_v > 50 and
        hist < hist_prev
    )

    bullish_pat = any(p in patterns for p in ["Hammer", "Morning_Star", "Bullish_Engulf", "Piercing", "Doji"])
    bearish_pat = any(p in patterns for p in ["Shooting_Star", "Evening_Star", "Dark_Cloud", "Bearish_Engulf"])

    if bullish_div:
        conf = 70.0 + (12.0 if bullish_pat else 0.0)
        sl   = round(cur - atr * 2.0, digits)
        tp   = round(cur + atr * 4.0, digits)
        reason = f"دايفرجنس صاعد: سعر أدنى + RSI أعلى ({rsi_v:.0f}↑) | Hist يتحسن"
        if bullish_pat:
            reason += f" | شمعة {list(patterns.keys())[0] if patterns else ''}"
        return _build_signal("BUY", conf, "MACDDivergence", reason, cur, sl, tp, 0.78, digits)

    if bearish_div:
        conf = 70.0 + (12.0 if bearish_pat else 0.0)
        sl   = round(cur + atr * 2.0, digits)
        tp   = round(cur - atr * 4.0, digits)
        reason = f"دايفرجنس هابط: سعر أعلى + RSI أدنى ({rsi_v:.0f}↓) | Hist يتدهور"
        return _build_signal("SELL", conf, "MACDDivergence", reason, cur, sl, tp, -0.78, digits)

    # No clear divergence
    tendency = 25.0
    if abs(hist) > 0.001 * cur:
        tendency += 10.0
    if bullish_pat or bearish_pat:
        tendency += 12.0

    return _build_signal("WAIT", tendency, "MACDDivergence",
                         f"لا دايفرجنس حاسم | RSI={rsi_v:.0f} | Hist={hist:.4f}",
                         cur, 0, 0, 0, digits)


# ===== MASTER STRATEGY ENGINE =====

def get_signal(symbol: str, df: pd.DataFrame, ind: dict, sym_info: dict,
               min_confidence: float = None) -> dict:
    """
    Run all 4 strategies.
    Entry requires CONSENSUS: >= 2 strategies must agree on direction.
    Confidence boosted when 3-4 strategies agree.
    """
    if min_confidence is None:
        min_confidence = float(TRADING.get("min_confidence", 65.0))

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

    # Separate active signals
    active  = [s for s in all_list if s["action"] != "WAIT"]
    buy_sigs  = [s for s in active if s["action"] == "BUY"]
    sell_sigs = [s for s in active if s["action"] == "SELL"]

    # Build output with partial confidence even when WAITing
    best_candidate = max(all_list, key=lambda s: s["confidence"])

    # ===== CONSENSUS VOTING =====
    # Need at least 2 strategies agreeing on the SAME direction
    winner = None
    votes  = 0
    direction = None

    if len(buy_sigs) >= len(sell_sigs) and len(buy_sigs) >= 2:
        votes = len(buy_sigs)
        direction = "BUY"
        candidates = buy_sigs
    elif len(sell_sigs) >= 2:
        votes = len(sell_sigs)
        direction = "SELL"
        candidates = sell_sigs
    elif len(buy_sigs) == 1 and not sell_sigs:
        # Only 1 strategy agrees but check if it's very high confidence
        if buy_sigs[0]["confidence"] >= 85.0:
            votes = 1
            direction = "BUY"
            candidates = buy_sigs
    elif len(sell_sigs) == 1 and not buy_sigs:
        if sell_sigs[0]["confidence"] >= 85.0:
            votes = 1
            direction = "SELL"
            candidates = sell_sigs

    if direction and candidates:
        # Pick best signal (highest confidence) for SL/TP
        best_sig = max(candidates, key=lambda s: s["confidence"])
        avg_conf = sum(s["confidence"] for s in candidates) / len(candidates)

        # Boost confidence based on vote consensus
        # 2 votes → ×1.1, 3 votes → ×1.2, 4 votes → ×1.3
        consensus_boost = {1: 1.0, 2: 1.1, 3: 1.2, 4: 1.3}.get(votes, 1.0)
        final_conf = min(98.0, avg_conf * consensus_boost)

        if final_conf >= min_confidence:
            winner = {
                "action":     direction,
                "confidence": round(final_conf, 1),
                "strategy":   best_sig["strategy"],
                "reason":     best_sig["reason"],
                "entry":      best_sig["entry"],
                "sl":         best_sig["sl"],
                "tp":         best_sig["tp"],
                "score":      best_sig["score"],
                "votes":      votes,
                "strategies": all_strategies,
                "all_signals": all_list,
            }
            logger.info(
                f"[{symbol}] SIGNAL: {direction} | conf={final_conf:.1f}% | "
                f"votes={votes}/4 | strategy={best_sig['strategy']}"
            )
            return winner

    # === No consensus or below min_confidence ===
    # Still provide informative WAIT signal
    max_active_conf = max((s["confidence"] for s in active), default=0)
    partial_conf    = max(best_candidate["confidence"], max_active_conf)

    # Build detailed reason
    if active:
        buy_count  = len(buy_sigs)
        sell_count = len(sell_sigs)
        if buy_count > sell_count:
            reason = f"إشارات شراء ({buy_count}/4) لكن دون حد الثقة أو التوافق المطلوب ({final_conf if direction else '—'}% < {min_confidence}%)"
        elif sell_count > buy_count:
            reason = f"إشارات بيع ({sell_count}/4) لكن دون حد الثقة أو التوافق المطلوب"
        else:
            reason = f"إشارات متضاربة: {buy_count} شراء / {sell_count} بيع — انتظار توافق"
    else:
        reason = best_candidate["reason"]

    return {
        "action":     "WAIT",
        "confidence": round(partial_conf, 1),
        "strategy":   best_candidate["strategy"],
        "reason":     reason,
        "entry":      best_candidate["entry"],
        "sl":         0.0,
        "tp":         0.0,
        "score":      0.0,
        "votes":      max(len(buy_sigs), len(sell_sigs)),
        "strategies": all_strategies,
        "all_signals": all_list,
    }
