"""
=============================================================
  Trading Bot - Technical Indicators Engine
  محرك المؤشرات الفنية الكامل
=============================================================
  Indicators:
    Trend    : EMA20/50/200, DEMA, TEMA, Ichimoku
    Momentum : RSI, MACD, Stochastic, CCI, Williams %R, MFI, ROC
    Volatility: Bollinger Bands, ATR, Keltner Channels, Donchian
    Volume   : OBV, Volume SMA
    Pattern  : Doji, Hammer, Engulfing, Morning/Evening Star
    Strength : ADX, Aroon
    S/R      : Dynamic Support & Resistance levels
=============================================================
"""
import logging
from typing import Optional

import numpy as np
import pandas as pd
import talib

from config import INDICATORS as CFG

logger = logging.getLogger(__name__)


# ===== HELPERS =====

def _sig(val: float, threshold_up: float = 0.5, threshold_dn: float = -0.5) -> str:
    """Convert numeric score to signal string."""
    if val >= threshold_up:
        return "BUY"
    if val <= threshold_dn:
        return "SELL"
    return "NEUTRAL"


def safe_last(arr) -> Optional[float]:
    """Return last non-NaN element of array/series."""
    if arr is None:
        return None
    if isinstance(arr, pd.Series):
        arr = arr.dropna()
        return float(arr.iloc[-1]) if len(arr) > 0 else None
    arr = np.asarray(arr, dtype=float)
    arr = arr[~np.isnan(arr)]
    return float(arr[-1]) if len(arr) > 0 else None


def safe_prev(arr, n: int = 1) -> Optional[float]:
    """Return nth-from-last non-NaN element."""
    if arr is None:
        return None
    if isinstance(arr, pd.Series):
        arr = arr.dropna()
        return float(arr.iloc[-1 - n]) if len(arr) > n else None
    arr = np.asarray(arr, dtype=float)
    arr = arr[~np.isnan(arr)]
    return float(arr[-1 - n]) if len(arr) > n else None


# ===== TREND INDICATORS =====

def calc_ema(close: np.ndarray) -> dict:
    """EMA 20, 50, 200 with trend direction."""
    ema20  = talib.EMA(close, timeperiod=CFG["ema_fast"])
    ema50  = talib.EMA(close, timeperiod=CFG["ema_slow"])
    ema200 = talib.EMA(close, timeperiod=CFG["ema_trend"])
    dema   = talib.DEMA(close, timeperiod=CFG["ema_fast"])
    tema   = talib.TEMA(close, timeperiod=CFG["ema_fast"])

    e20  = safe_last(ema20)
    e50  = safe_last(ema50)
    e200 = safe_last(ema200)
    cur  = close[-1]

    # Trend score: each condition +1 BUY / -1 SELL
    score = 0
    if e20 and e50:
        score += 1 if e20 > e50 else -1
    if e50 and e200:
        score += 1 if e50 > e200 else -1
    if e20 and cur:
        score += 1 if cur > e20 else -1
    if e50 and cur:
        score += 1 if cur > e50 else -1

    max_score = 4
    norm = score / max_score  # -1 to +1
    signal = _sig(norm, 0.25, -0.25)

    return {
        "ema20":  e20,
        "ema50":  e50,
        "ema200": e200,
        "dema":   safe_last(dema),
        "tema":   safe_last(tema),
        "score":  score,
        "signal": signal,
        "detail": f"EMA20={e20:.5f} EMA50={e50:.5f} EMA200={e200:.5f}" if e20 and e50 and e200 else "N/A",
    }


def calc_ichimoku(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> dict:
    """Ichimoku Cloud (manual calc)."""
    def midpoint(h, l, p): return (pd.Series(h).rolling(p).max() + pd.Series(l).rolling(p).min()) / 2

    tenkan   = midpoint(high, low, 9)
    kijun    = midpoint(high, low, 26)
    span_a   = ((tenkan + kijun) / 2).shift(26)
    span_b   = midpoint(high, low, 52).shift(26)
    chikou   = pd.Series(close).shift(-26)

    t  = safe_last(tenkan)
    k  = safe_last(kijun)
    sa = safe_last(span_a)
    sb = safe_last(span_b)
    cur = close[-1]

    score = 0
    if t and k:   score += 1 if t > k else -1
    if sa and sb: score += 1 if sa > sb else -1
    if cur and sa and sb:
        cloud_top = max(sa, sb)
        cloud_bot = min(sa, sb)
        if cur > cloud_top:   score += 2
        elif cur < cloud_bot: score -= 2

    signal = _sig(score / 4, 0.25, -0.25)
    return {
        "tenkan":  t,
        "kijun":   k,
        "span_a":  sa,
        "span_b":  sb,
        "score":   score,
        "signal":  signal,
    }


# ===== MOMENTUM INDICATORS =====

def calc_rsi(close: np.ndarray) -> dict:
    """RSI with divergence detection."""
    rsi = talib.RSI(close, timeperiod=CFG["rsi_period"])
    val  = safe_last(rsi)
    prev = safe_prev(rsi)

    if val is None:
        return {"value": None, "signal": "NEUTRAL", "score": 0}

    # Score: distance from neutral (50)
    if val <= CFG["rsi_oversold"]:
        score = 1.0 if val <= 20 else 0.7
        signal = "BUY"
    elif val >= CFG["rsi_overbought"]:
        score = -1.0 if val >= 80 else -0.7
        signal = "SELL"
    elif 45 <= val <= 55:
        score = 0
        signal = "NEUTRAL"
    elif val > 55:
        score = 0.3
        signal = "NEUTRAL"
    else:
        score = -0.3
        signal = "NEUTRAL"

    return {
        "value":  val,
        "prev":   prev,
        "signal": signal,
        "score":  score,
        "detail": f"RSI={val:.1f}",
    }


def calc_macd(close: np.ndarray) -> dict:
    """MACD with histogram analysis."""
    macd, signal_line, hist = talib.MACD(
        close,
        fastperiod=CFG["macd_fast"],
        slowperiod=CFG["macd_slow"],
        signalperiod=CFG["macd_signal"],
    )
    m  = safe_last(macd)
    s  = safe_last(signal_line)
    h  = safe_last(hist)
    hp = safe_prev(hist)

    if m is None or s is None:
        return {"value": None, "signal": "NEUTRAL", "score": 0}

    score = 0.0
    if m > s:        score += 0.5
    if h and h > 0:  score += 0.3
    if h and hp and h > hp:  score += 0.2  # momentum increasing
    if m < s:        score -= 0.5
    if h and h < 0:  score -= 0.3
    if h and hp and h < hp:  score -= 0.2

    signal = _sig(score, 0.4, -0.4)
    return {
        "macd":    m,
        "signal_line": s,
        "hist":    h,
        "score":   score,
        "signal":  signal,
        "detail":  f"MACD={m:.5f} Signal={s:.5f} Hist={h:.5f}" if m and s and h else "N/A",
    }


def calc_stochastic(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> dict:
    """Stochastic Oscillator."""
    slowk, slowd = talib.STOCH(
        high, low, close,
        fastk_period=CFG["stoch_k"],
        slowk_period=3,
        slowd_period=CFG["stoch_d"],
    )
    k = safe_last(slowk)
    d = safe_last(slowd)

    if k is None:
        return {"k": None, "d": None, "signal": "NEUTRAL", "score": 0}

    score = 0.0
    if k < 20:  score = 0.8
    elif k > 80: score = -0.8
    elif k > d:  score = 0.3
    else:        score = -0.3

    signal = _sig(score, 0.5, -0.5)
    return {"k": k, "d": d, "score": score, "signal": signal, "detail": f"K={k:.1f} D={d:.1f}"}


def calc_cci(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> dict:
    """Commodity Channel Index."""
    cci = talib.CCI(high, low, close, timeperiod=CFG["cci_period"])
    val = safe_last(cci)
    if val is None:
        return {"value": None, "signal": "NEUTRAL", "score": 0}

    if val < -100:   score = 0.8
    elif val > 100:  score = -0.8
    elif val < -50:  score = 0.4
    elif val > 50:   score = -0.4
    else:            score = 0.0

    signal = _sig(score, 0.5, -0.5)
    return {"value": val, "score": score, "signal": signal, "detail": f"CCI={val:.1f}"}


def calc_williams(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> dict:
    """Williams %R."""
    willr = talib.WILLR(high, low, close, timeperiod=CFG["williams_period"])
    val = safe_last(willr)
    if val is None:
        return {"value": None, "signal": "NEUTRAL", "score": 0}

    if val < -80:   score = 0.7
    elif val > -20: score = -0.7
    else:           score = 0.0

    signal = _sig(score, 0.4, -0.4)
    return {"value": val, "score": score, "signal": signal, "detail": f"Williams%R={val:.1f}"}


def calc_mfi(high: np.ndarray, low: np.ndarray, close: np.ndarray, volume: np.ndarray) -> dict:
    """Money Flow Index."""
    mfi = talib.MFI(high, low, close, volume, timeperiod=CFG["mfi_period"])
    val = safe_last(mfi)
    if val is None:
        return {"value": None, "signal": "NEUTRAL", "score": 0}

    if val < 20:   score = 0.8
    elif val > 80: score = -0.8
    elif val < 40: score = 0.3
    elif val > 60: score = -0.3
    else:          score = 0.0

    signal = _sig(score, 0.4, -0.4)
    return {"value": val, "score": score, "signal": signal, "detail": f"MFI={val:.1f}"}


def calc_roc(close: np.ndarray) -> dict:
    """Rate of Change."""
    roc = talib.ROC(close, timeperiod=10)
    val = safe_last(roc)
    if val is None:
        return {"value": None, "signal": "NEUTRAL", "score": 0}
    score = max(-1.0, min(1.0, val / 2.0))  # normalize roughly
    signal = _sig(score, 0.3, -0.3)
    return {"value": val, "score": score, "signal": signal, "detail": f"ROC={val:.2f}%"}


# ===== VOLATILITY INDICATORS =====

def calc_bollinger(close: np.ndarray) -> dict:
    """Bollinger Bands with %B and bandwidth."""
    upper, mid, lower = talib.BBANDS(
        close,
        timeperiod=CFG["bb_period"],
        nbdevup=CFG["bb_std"],
        nbdevdn=CFG["bb_std"],
    )
    u = safe_last(upper)
    m = safe_last(mid)
    l = safe_last(lower)
    cur = close[-1]

    if u is None or l is None:
        return {"upper": None, "mid": None, "lower": None, "signal": "NEUTRAL", "score": 0}

    bw = (u - l) / m * 100 if m else 0  # bandwidth %
    pct_b = (cur - l) / (u - l) if (u - l) != 0 else 0.5  # %B: 0=lower, 1=upper

    score = 0.0
    if cur < l:    score = 0.8    # below lower band
    elif cur > u:  score = -0.8   # above upper band
    elif pct_b < 0.2: score = 0.4
    elif pct_b > 0.8: score = -0.4
    else:          score = 0.0

    signal = _sig(score, 0.5, -0.5)
    return {
        "upper": u, "mid": m, "lower": l,
        "bandwidth": bw, "pct_b": pct_b,
        "score": score, "signal": signal,
        "detail": f"BB Upper={u:.5f} Mid={m:.5f} Lower={l:.5f} BW={bw:.2f}%",
    }


def calc_atr(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> dict:
    """Average True Range."""
    atr = talib.ATR(high, low, close, timeperiod=CFG["atr_period"])
    val = safe_last(atr)
    pct = (val / close[-1] * 100) if val else 0
    return {"value": val, "pct": pct, "detail": f"ATR={val:.5f} ({pct:.2f}%)"}


def calc_keltner(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> dict:
    """Keltner Channels (EMA ± 2*ATR)."""
    ema  = talib.EMA(close, timeperiod=20)
    atr  = talib.ATR(high, low, close, timeperiod=14)
    e    = safe_last(ema)
    a    = safe_last(atr)
    if e is None or a is None:
        return {"upper": None, "lower": None, "signal": "NEUTRAL", "score": 0}

    upper = e + 2 * a
    lower = e - 2 * a
    cur   = close[-1]

    score = 0.0
    if cur < lower: score = 0.7
    elif cur > upper: score = -0.7
    signal = _sig(score, 0.4, -0.4)
    return {"upper": upper, "mid": e, "lower": lower, "score": score, "signal": signal}


def calc_donchian(high: np.ndarray, low: np.ndarray) -> dict:
    """Donchian Channels (N-period high/low)."""
    period = CFG["donchian_period"]
    h_series = pd.Series(high)
    l_series = pd.Series(low)
    upper = float(h_series.rolling(period).max().iloc[-1])
    lower = float(l_series.rolling(period).min().iloc[-1])
    mid   = (upper + lower) / 2
    cur_h = high[-1]
    cur_l = low[-1]

    score = 0.0
    # Breakout signals
    if cur_h >= upper:  score = 0.8
    elif cur_l <= lower: score = -0.8
    signal = _sig(score, 0.5, -0.5)
    return {"upper": upper, "lower": lower, "mid": mid,
            "score": score, "signal": signal,
            "detail": f"Donchian H={upper:.5f} L={lower:.5f}"}


# ===== VOLUME INDICATORS =====

def calc_obv(close: np.ndarray, volume: np.ndarray) -> dict:
    """On-Balance Volume."""
    obv = talib.OBV(close, volume)
    obv_sma = talib.SMA(obv, timeperiod=CFG["obv_sma"])
    val  = safe_last(obv)
    sma  = safe_last(obv_sma)
    score = 0.3 if (val and sma and val > sma) else -0.3 if (val and sma and val < sma) else 0
    signal = _sig(score, 0.2, -0.2)
    return {"value": val, "sma": sma, "score": score, "signal": signal}


def calc_volume_sma(volume: np.ndarray) -> dict:
    """Volume vs its moving average."""
    vol_sma = talib.SMA(volume.astype(float), timeperiod=20)
    cur = volume[-1]
    avg = safe_last(vol_sma)
    ratio = (cur / avg) if avg else 1.0
    return {"current": cur, "average": avg, "ratio": ratio,
            "is_high": ratio > 1.5, "detail": f"Vol ratio={ratio:.2f}x"}


# ===== TREND STRENGTH =====

def calc_adx(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> dict:
    """ADX - Trend Strength."""
    adx    = talib.ADX(high, low, close, timeperiod=CFG["adx_period"])
    plus_di  = talib.PLUS_DI(high, low, close, timeperiod=CFG["adx_period"])
    minus_di = talib.MINUS_DI(high, low, close, timeperiod=CFG["adx_period"])

    adx_val = safe_last(adx)
    pdi     = safe_last(plus_di)
    mdi     = safe_last(minus_di)

    trending = adx_val > 25 if adx_val else False
    score = 0.0
    if trending:
        if pdi and mdi:
            score = 0.5 if pdi > mdi else -0.5
    signal = _sig(score, 0.3, -0.3)

    strength = "Strong" if adx_val and adx_val > 50 else \
               "Moderate" if adx_val and adx_val > 25 else "Weak"
    return {
        "adx": adx_val, "+di": pdi, "-di": mdi,
        "trending": trending, "strength": strength,
        "score": score, "signal": signal,
        "detail": f"ADX={adx_val:.1f} ({strength}) +DI={pdi:.1f} -DI={mdi:.1f}" if adx_val else "N/A",
    }


def calc_aroon(high: np.ndarray, low: np.ndarray) -> dict:
    """Aroon Oscillator."""
    aroon_down, aroon_up = talib.AROON(high, low, timeperiod=CFG["aroon_period"])
    osc = talib.AROONOSC(high, low, timeperiod=CFG["aroon_period"])

    up  = safe_last(aroon_up)
    dn  = safe_last(aroon_down)
    o   = safe_last(osc)

    score = (o / 100) if o else 0
    signal = _sig(score, 0.3, -0.3)
    return {"up": up, "down": dn, "osc": o, "score": score, "signal": signal,
            "detail": f"Aroon Up={up:.1f} Down={dn:.1f} Osc={o:.1f}" if up else "N/A"}


# ===== PATTERN RECOGNITION =====

def calc_patterns(open_: np.ndarray, high: np.ndarray, low: np.ndarray, close: np.ndarray) -> dict:
    """Detect candlestick patterns."""
    patterns = {}
    score = 0

    funcs = {
        "Doji":          talib.CDLDOJI,
        "Hammer":        talib.CDLHAMMER,
        "Inv_Hammer":    talib.CDLINVERTEDHAMMER,
        "Bullish_Engulf":talib.CDLENGULFING,
        "Morning_Star":  talib.CDLMORNINGSTAR,
        "Evening_Star":  talib.CDLEVENINGSTAR,
        "Shooting_Star": talib.CDLSHOOTINGSTAR,
        "Hanging_Man":   talib.CDLHANGINGMAN,
        "Piercing":      talib.CDLPIERCING,
        "Dark_Cloud":    talib.CDLDARKCLOUDCOVER,
        "Three_White":   talib.CDL3WHITESOLDIERS,
        "Three_Black":   talib.CDL3BLACKCROWS,
        "Harami":        talib.CDLHARAMI,
        "Spinning_Top":  talib.CDLSPINNINGTOP,
    }

    bullish_patterns = {"Hammer", "Inv_Hammer", "Bullish_Engulf", "Morning_Star", "Piercing", "Three_White"}
    bearish_patterns = {"Evening_Star", "Shooting_Star", "Hanging_Man", "Dark_Cloud", "Three_Black"}

    for name, fn in funcs.items():
        try:
            result = fn(open_, high, low, close)
            val = int(result[-1])
            if val != 0:
                patterns[name] = val
                if name in bullish_patterns:
                    score += 1 if val > 0 else -1
                elif name in bearish_patterns:
                    score += -1 if val > 0 else 1
        except Exception:
            pass

    norm = max(-1.0, min(1.0, score / 3.0))
    signal = _sig(norm, 0.3, -0.3)
    return {
        "patterns":  patterns,
        "count":     len(patterns),
        "score":     norm,
        "signal":    signal,
        "detail":    ", ".join(patterns.keys()) if patterns else "No patterns",
    }


# ===== SUPPORT & RESISTANCE =====

def calc_support_resistance(high: np.ndarray, low: np.ndarray, close: np.ndarray, n: int = 50) -> dict:
    """Find key S/R levels from recent price action."""
    h = pd.Series(high[-n:])
    l = pd.Series(low[-n:])
    cur = close[-1]

    # Pivot points
    pivot = (high[-2] + low[-2] + close[-2]) / 3
    r1 = 2 * pivot - low[-2]
    s1 = 2 * pivot - high[-2]
    r2 = pivot + (high[-2] - low[-2])
    s2 = pivot - (high[-2] - low[-2])

    # Key levels (local highs/lows)
    local_highs = []
    local_lows  = []
    for i in range(2, len(h) - 2):
        if h.iloc[i] > h.iloc[i-1] and h.iloc[i] > h.iloc[i+1]:
            local_highs.append(float(h.iloc[i]))
        if l.iloc[i] < l.iloc[i-1] and l.iloc[i] < l.iloc[i+1]:
            local_lows.append(float(l.iloc[i]))

    nearest_resistance = min([x for x in local_highs + [r1, r2] if x > cur], default=cur * 1.01)
    nearest_support    = max([x for x in local_lows  + [s1, s2] if x < cur], default=cur * 0.99)

    dist_to_res = (nearest_resistance - cur) / cur * 100
    dist_to_sup = (cur - nearest_support) / cur * 100

    score = 0.0
    if dist_to_sup < dist_to_res * 0.5:  # closer to support → BUY
        score = 0.5
    elif dist_to_res < dist_to_sup * 0.5:  # closer to resistance → SELL
        score = -0.5

    return {
        "pivot": pivot, "r1": r1, "r2": r2, "s1": s1, "s2": s2,
        "nearest_resistance": nearest_resistance,
        "nearest_support":    nearest_support,
        "dist_to_res_pct":    dist_to_res,
        "dist_to_sup_pct":    dist_to_sup,
        "score":  score,
        "signal": _sig(score, 0.3, -0.3),
    }


# ===== MASTER ANALYSIS FUNCTION =====

def analyze(df: pd.DataFrame) -> dict:
    """
    Run ALL indicators on OHLCV DataFrame.
    Returns comprehensive analysis dict with:
      - All indicator values
      - Individual signals
      - Overall score (-100 to +100)
      - Confidence percentage
      - Final action: 'BUY', 'SELL', 'WAIT'
    """
    if df is None or len(df) < 210:
        return {"action": "WAIT", "overall_score": 0, "confidence": 0,
                "error": f"Insufficient data: {len(df) if df is not None else 0} bars"}

    open_  = df["open"].values.astype(float)
    high   = df["high"].values.astype(float)
    low    = df["low"].values.astype(float)
    close  = df["close"].values.astype(float)
    volume = df["volume"].values.astype(float)

    # Run all indicators
    results = {}
    try: results["ema"]         = calc_ema(close)
    except Exception as e: results["ema"] = {"signal": "NEUTRAL", "score": 0, "error": str(e)}
    try: results["ichimoku"]    = calc_ichimoku(high, low, close)
    except Exception as e: results["ichimoku"] = {"signal": "NEUTRAL", "score": 0}
    try: results["rsi"]         = calc_rsi(close)
    except Exception as e: results["rsi"] = {"signal": "NEUTRAL", "score": 0}
    try: results["macd"]        = calc_macd(close)
    except Exception as e: results["macd"] = {"signal": "NEUTRAL", "score": 0}
    try: results["stochastic"]  = calc_stochastic(high, low, close)
    except Exception as e: results["stochastic"] = {"signal": "NEUTRAL", "score": 0}
    try: results["cci"]         = calc_cci(high, low, close)
    except Exception as e: results["cci"] = {"signal": "NEUTRAL", "score": 0}
    try: results["williams"]    = calc_williams(high, low, close)
    except Exception as e: results["williams"] = {"signal": "NEUTRAL", "score": 0}
    try: results["mfi"]         = calc_mfi(high, low, close, volume)
    except Exception as e: results["mfi"] = {"signal": "NEUTRAL", "score": 0}
    try: results["roc"]         = calc_roc(close)
    except Exception as e: results["roc"] = {"signal": "NEUTRAL", "score": 0}
    try: results["bollinger"]   = calc_bollinger(close)
    except Exception as e: results["bollinger"] = {"signal": "NEUTRAL", "score": 0}
    try: results["atr"]         = calc_atr(high, low, close)
    except Exception as e: results["atr"] = {"value": None}
    try: results["keltner"]     = calc_keltner(high, low, close)
    except Exception as e: results["keltner"] = {"signal": "NEUTRAL", "score": 0}
    try: results["donchian"]    = calc_donchian(high, low)
    except Exception as e: results["donchian"] = {"signal": "NEUTRAL", "score": 0}
    try: results["obv"]         = calc_obv(close, volume)
    except Exception as e: results["obv"] = {"signal": "NEUTRAL", "score": 0}
    try: results["volume"]      = calc_volume_sma(volume)
    except Exception as e: results["volume"] = {"ratio": 1.0}
    try: results["adx"]         = calc_adx(high, low, close)
    except Exception as e: results["adx"] = {"signal": "NEUTRAL", "score": 0, "trending": False}
    try: results["aroon"]       = calc_aroon(high, low)
    except Exception as e: results["aroon"] = {"signal": "NEUTRAL", "score": 0}
    try: results["patterns"]    = calc_patterns(open_, high, low, close)
    except Exception as e: results["patterns"] = {"signal": "NEUTRAL", "score": 0}
    try: results["sr"]          = calc_support_resistance(high, low, close)
    except Exception as e: results["sr"] = {"signal": "NEUTRAL", "score": 0}

    # ===== WEIGHTED SCORE AGGREGATION =====
    weights = {
        "ema":        3.0,   # Trend - high weight
        "ichimoku":   2.0,
        "rsi":        2.5,   # Momentum - high weight
        "macd":       2.5,
        "stochastic": 1.5,
        "cci":        1.0,
        "williams":   1.0,
        "mfi":        1.0,
        "roc":        0.5,
        "bollinger":  2.0,   # Volatility
        "keltner":    1.0,
        "donchian":   1.5,
        "obv":        1.0,   # Volume
        "adx":        1.5,   # Strength
        "aroon":      1.0,
        "patterns":   1.5,   # Patterns
        "sr":         1.0,   # S/R
    }

    total_weight = sum(weights.values())
    weighted_sum = 0.0
    for key, w in weights.items():
        s = results.get(key, {}).get("score", 0) or 0
        weighted_sum += s * w

    overall_score_norm = weighted_sum / total_weight  # -1 to +1
    overall_score = overall_score_norm * 100           # -100 to +100

    # Count signals
    buy_count  = sum(1 for k in weights if results.get(k, {}).get("signal") == "BUY")
    sell_count = sum(1 for k in weights if results.get(k, {}).get("signal") == "SELL")
    total_ind  = len(weights)

    # Confidence: how aligned are the signals?
    dominant = max(buy_count, sell_count)
    confidence = (dominant / total_ind) * 100

    # Trend filter: only trade WITH the trend
    trending   = results.get("adx", {}).get("trending", False)
    ema_signal = results.get("ema", {}).get("signal", "NEUTRAL")

    # Final action
    if overall_score >= 25 and confidence >= 55:
        action = "BUY"
    elif overall_score <= -25 and confidence >= 55:
        action = "SELL"
    else:
        action = "WAIT"

    # Extra filter: if no trend and not a reversal setup, wait
    if action != "WAIT" and not trending:
        rsi_v = results.get("rsi", {}).get("value", 50) or 50
        if 35 < rsi_v < 65:
            action = "WAIT"

    return {
        "action":        action,
        "overall_score": round(overall_score, 2),
        "confidence":    round(confidence, 1),
        "buy_signals":   buy_count,
        "sell_signals":  sell_count,
        "neutral_signals": total_ind - buy_count - sell_count,
        "total_indicators": total_ind,
        "current_price": float(close[-1]),
        "indicators":    results,
    }
