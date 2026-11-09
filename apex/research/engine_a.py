#!/usr/bin/env python3
"""engine_a.py - REFERENCE port of apex/APEX_Focus_original.pine (the readable oracle).

Clarity beats speed here: pure Python loops, numpy arrays only as storage, no numba.
Every block is written in the same order as the Pine source and carries the Pine line
number (L###) it mirrors, so the two files can be read side by side.

Layout
  A. na helpers            - Pine `na` is float('nan'); a comparison involving nan is False
  B. Pine built-ins        - ENGINE_SPEC section 2, implemented literally
  C. Higher-timeframe trend- ENGINE_SPEC section 3 (request.security + [1] + lookahead_on)
  D. Params / series / run - Pine L114-L218 (signals, stop distances, chandelier, profile)
  E. simulate              - Pine L221-L502 (Trade, Stats, closeTrade, openTrade, blocks 1 and 2)

Not ported (never influences signals, trades or Stats): drawings, labels, plots, alerts,
chop / Bollinger squeeze (computed but unused by the script), regression channel, pivot
trendlines / zones and the support-rebound watch.

Interpretations chosen where the Pine source / spec leave room (all documented in place):
  * runtime.error(...) conditions (L103-L110) raise ValueError.
  * Only the script's "Auto" higher-timeframe mode exists (Params has no htfMode).  The EMA
    length rule uses the EFFECTIVE timeframe after the L120 fallback to the chart timeframe.
  * ta.highest / ta.lowest return na while any value inside the window is na (only reachable
    before the 250-bar warm-up, so it cannot change a signal).
  * ta.rma / ta.ema re-seed with an SMA whenever their previous value is na (Pine's own
    reference code); identical to the spec wording for the leading-na inputs used here.
  * Division by zero follows IEEE (x/0 -> +-inf, 0/0 -> na) instead of raising.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np

# Set to True (tests do) to assert the trade-state invariants on every bar of simulate().
DEBUG_CHECKS = False

# ───────────────────────────── A. na helpers ─────────────────────────────
NAN = float("nan")


def na(x) -> bool:
    """Pine na(x).  nan is the only float that differs from itself."""
    return x != x


def nz(x, replacement=0.0):
    """Pine nz(x): 0 (or `replacement`) for na."""
    return replacement if x != x else x


def pine_max(*xs):
    """Pine math.max: na when any argument is na (Python's max() would silently drop a nan)."""
    m = xs[0]
    for x in xs:
        if x != x:
            return NAN
        if x > m:
            m = x
    return m


def pine_min(*xs):
    """Pine math.min: na when any argument is na."""
    m = xs[0]
    for x in xs:
        if x != x:
            return NAN
        if x < m:
            m = x
    return m


def pine_sign(x):
    """Pine math.sign: na for na, else -1 / 0 / +1."""
    if x != x:
        return NAN
    return 1.0 if x > 0 else -1.0 if x < 0 else 0.0


def pine_div(a, b):
    """Float division that never raises: x/0 -> +-inf, 0/0 -> na, anything with na -> na."""
    if b == 0:
        if a != a or a == 0:
            return NAN
        return math.inf if (a > 0) == (math.copysign(1.0, b) > 0) else -math.inf
    return a / b


def _floats(series) -> list:
    """A series as a list of Python floats (plain-float semantics inside the loops)."""
    return np.asarray(series, dtype=np.float64).tolist()


def _arr(values) -> np.ndarray:
    return np.asarray(values, dtype=np.float64)


# ───────────────────────────── B. Pine built-ins (ENGINE_SPEC section 2) ─────────────────────────────
def ta_tr(high, low, close, handle_na: bool) -> np.ndarray:
    """ta.tr(handle_na).
    ta.tr(true)  = na(high[1]) ? high - low : max(high - low, abs(high - close[1]), abs(low - close[1]))
    ta.tr(false) = the same max(), which is na on the first bar because close[1] is na.
    """
    hi, lo, cl = _floats(high), _floats(low), _floats(close)
    out = [NAN] * len(cl)
    for i in range(len(cl)):
        if i == 0:                                   # high[1] / close[1] are na on the first bar
            out[i] = hi[i] - lo[i] if handle_na else NAN
        else:
            out[i] = pine_max(hi[i] - lo[i], abs(hi[i] - cl[i - 1]), abs(lo[i] - cl[i - 1]))
    return _arr(out)


def _sma_at(src: list, i: int, length: int):
    """SMA of the `length` bars ending at bar i; na until that window holds `length` non-na values."""
    if i - length + 1 < 0:
        return NAN
    total = 0.0
    for k in range(i - length + 1, i + 1):
        if na(src[k]):
            return NAN
        total += src[k]
    return total / length


def _recursive_ma(source, length: int, alpha: float) -> np.ndarray:
    """Shared body of ta.rma / ta.ema (Pine reference code):
        sum := na(sum[1]) ? ta.sma(src, length) : alpha * src + (1 - alpha) * sum[1]
    i.e. the first value is the SMA on the first bar where `length` values exist, then the recursion.
    """
    src = _floats(source)
    out = [NAN] * len(src)
    for i in range(len(src)):
        prev = out[i - 1] if i > 0 else NAN
        if na(prev):
            out[i] = _sma_at(src, i, length)
        else:
            out[i] = alpha * src[i] + (1 - alpha) * prev
    return _arr(out)


def ta_rma(source, length: int) -> np.ndarray:
    """ta.rma(src, n): alpha = 1/n, SMA seed."""
    return _recursive_ma(source, length, 1.0 / length)


def ta_ema(source, length: int) -> np.ndarray:
    """ta.ema(src, n): alpha = 2/(n+1), SMA seed."""
    return _recursive_ma(source, length, 2.0 / (length + 1))


def ta_atr(high, low, close, length: int) -> np.ndarray:
    """ta.atr(n) = ta.rma(ta.tr(true), n)."""
    return ta_rma(ta_tr(high, low, close, True), length)


def ta_highest(source, length: int) -> np.ndarray:
    """ta.highest(src, n): max of the last n bars INCLUDING the current one; na until n values exist."""
    src = _floats(source)
    out = [NAN] * len(src)
    for i in range(length - 1, len(src)):
        window = src[i - length + 1:i + 1]
        out[i] = NAN if any(na(x) for x in window) else max(window)
    return _arr(out)


def ta_lowest(source, length: int) -> np.ndarray:
    """ta.lowest(src, n): min of the last n bars INCLUDING the current one; na until n values exist."""
    src = _floats(source)
    out = [NAN] * len(src)
    for i in range(length - 1, len(src)):
        window = src[i - length + 1:i + 1]
        out[i] = NAN if any(na(x) for x in window) else min(window)
    return _arr(out)


def ta_rsi(source, length: int) -> np.ndarray:
    """ta.rsi(src, n):
        u = max(change(src), 0) ; d = max(-change(src), 0) ; rs = rma(u, n) / rma(d, n)
        rsi = rma(d) == 0 ? 100 : rma(u) == 0 ? 0 : 100 - 100 / (1 + rs)
    """
    src = _floats(source)
    n = len(src)
    u = [NAN] * n
    d = [NAN] * n
    for i in range(n):
        change = src[i] - src[i - 1] if i > 0 else NAN      # ta.change(src), na on the first bar
        u[i] = pine_max(change, 0.0)
        d[i] = pine_max(-change, 0.0)
    rma_u = _floats(ta_rma(u, length))
    rma_d = _floats(ta_rma(d, length))
    out = [NAN] * n
    for i in range(n):
        if rma_d[i] == 0:
            out[i] = 100.0
        elif rma_u[i] == 0:
            out[i] = 0.0
        else:                                              # also the na path: 100 - 100/(1 + na) = na
            out[i] = 100 - 100 / (1 + rma_u[i] / rma_d[i])
    return _arr(out)


def _fixnan(values: list) -> list:
    """Pine fixnan(): replace na by the last non-na value (na while none exists yet)."""
    out = [NAN] * len(values)
    last = NAN
    for i, x in enumerate(values):
        if not na(x):
            last = x
        out[i] = last
    return out


def ta_dmi(high, low, close, diLength: int, adxSmoothing: int):
    """ta.dmi(len, sm) -> (plus, minus, adx):
        up = change(high) ; down = -change(low)
        plusDM  = na(up)   ? na : (up > down and up > 0 ? up : 0)
        minusDM = na(down) ? na : (down > up and down > 0 ? down : 0)
        trur  = rma(ta.tr(false), len)
        plus  = fixnan(100 * rma(plusDM, len) / trur)
        minus = fixnan(100 * rma(minusDM, len) / trur)
        sum   = plus + minus
        adx   = 100 * rma(abs(plus - minus) / (sum == 0 ? 1 : sum), sm)
    """
    hi, lo = _floats(high), _floats(low)
    n = len(hi)
    plusDM = [NAN] * n
    minusDM = [NAN] * n
    for i in range(n):
        up = hi[i] - hi[i - 1] if i > 0 else NAN
        down = -(lo[i] - lo[i - 1]) if i > 0 else NAN
        plusDM[i] = NAN if na(up) else (up if (up > down and up > 0) else 0.0)
        minusDM[i] = NAN if na(down) else (down if (down > up and down > 0) else 0.0)
    trur = _floats(ta_rma(ta_tr(high, low, close, False), diLength))
    rma_plus = _floats(ta_rma(plusDM, diLength))
    rma_minus = _floats(ta_rma(minusDM, diLength))
    plus = _fixnan([pine_div(100 * rma_plus[i], trur[i]) for i in range(n)])
    minus = _fixnan([pine_div(100 * rma_minus[i], trur[i]) for i in range(n)])
    dx = [NAN] * n
    for i in range(n):
        sum_ = plus[i] + minus[i]
        dx[i] = pine_div(abs(plus[i] - minus[i]), (1.0 if sum_ == 0 else sum_))
    adx = 100 * ta_rma(dx, adxSmoothing)
    return _arr(plus), _arr(minus), adx


def ta_supertrend(high, low, close, factor: float, atrPeriod: int):
    """ta.supertrend(factor, atrPeriod) -> (superTrend, direction); direction < 0 means UP-trend.

    lowerBand[1], upperBand[1] and prevSuperTrend are the FINAL (already adjusted) values of the
    previous bar.  While atr is na the comparisons are all False, so both bands settle at
    nz(previous) = 0 and direction is 1; direction is therefore never na.
    """
    hi, lo, cl = _floats(high), _floats(low), _floats(close)
    atr = _floats(ta_atr(high, low, close, atrPeriod))
    n = len(cl)
    lowerBand_s = [NAN] * n
    upperBand_s = [NAN] * n
    superTrend_s = [NAN] * n
    direction_s = [NAN] * n
    for i in range(n):
        src = (hi[i] + lo[i]) / 2                                   # hl2
        upperBand = src + factor * atr[i]
        lowerBand = src - factor * atr[i]
        prevLowerBand = nz(lowerBand_s[i - 1]) if i > 0 else 0.0    # nz(lowerBand[1])
        prevUpperBand = nz(upperBand_s[i - 1]) if i > 0 else 0.0    # nz(upperBand[1])
        prevClose = cl[i - 1] if i > 0 else NAN                     # close[1]
        prevAtr = atr[i - 1] if i > 0 else NAN                      # atr[1]
        prevSuperTrend = superTrend_s[i - 1] if i > 0 else NAN      # superTrend[1]

        lowerBand = lowerBand if (lowerBand > prevLowerBand or prevClose < prevLowerBand) else prevLowerBand
        upperBand = upperBand if (upperBand < prevUpperBand or prevClose > prevUpperBand) else prevUpperBand

        if na(prevAtr):
            direction = 1
        elif prevSuperTrend == prevUpperBand:
            direction = -1 if cl[i] > upperBand else 1
        else:
            direction = 1 if cl[i] < lowerBand else -1
        superTrend = lowerBand if direction == -1 else upperBand

        lowerBand_s[i] = lowerBand
        upperBand_s[i] = upperBand
        superTrend_s[i] = superTrend
        direction_s[i] = float(direction)
    return _arr(superTrend_s), _arr(direction_s)


# ───────────────────────────── C. Higher-timeframe trend (ENGINE_SPEC section 3) ─────────────────────────────
def htfTrendCalc(bars: dict, emaLen: int) -> np.ndarray:
    """Pine L123-L126, evaluated on the bars of the higher timeframe:
        [_, d] = ta.supertrend(3.0, 10)
        e = ta.ema(close, emaLen)
        na(e) or na(d) ? 0 : close > e and d < 0 ? 1 : close < e and d > 0 ? -1 : 0
    """
    close = _floats(bars["c"])
    _, direction = ta_supertrend(bars["h"], bars["l"], bars["c"], 3.0, 10)
    d = _floats(direction)
    e = _floats(ta_ema(bars["c"], emaLen))
    out = [0.0] * len(close)
    for i in range(len(close)):
        if na(e[i]) or na(d[i]):
            out[i] = 0.0
        elif close[i] > e[i] and d[i] < 0:
            out[i] = 1.0
        elif close[i] < e[i] and d[i] > 0:
            out[i] = -1.0
        else:
            out[i] = 0.0
    return _arr(out)


def request_security_prev(htf_t, htf_values, chart_t) -> np.ndarray:
    """request.security(tickerid, htf, expr[1], lookahead = barmerge.lookahead_on)  (Pine L136-L137).

    Every chart bar receives the value computed on the HTF bar BEFORE the HTF bar that contains it:
    j = searchsorted(htf_t, chart_t, side="right") - 1 is the containing HTF bar, the value is
    values[j - 1], and na (nan) when j - 1 < 0.
    """
    htf_t = np.asarray(htf_t)
    chart_t = np.asarray(chart_t)
    values = _floats(htf_values)
    containing = (np.searchsorted(htf_t, chart_t, side="right") - 1).tolist()
    out = [NAN] * len(chart_t)
    for i, j in enumerate(containing):
        if j - 1 >= 0:
            out[i] = values[j - 1]
    return _arr(out)


# ───────────────────────────── D. Inputs, per-bar series, run() ─────────────────────────────
@dataclass
class Params:                      # defaults == the Pine input defaults (L31-L86)
    useBrk: bool = True
    donLen: int = 20
    useFlip: bool = True
    stFactor: float = 3.0
    stLen: int = 10
    usePb: bool = True
    minScore: int = 7
    adxMin: float = 25.0
    useTsm: bool = True
    dirMode: str = "Both"          # "Both" | "Long only" | "Short only"
    profile: str = "AUTO"          # "AUTO" | "HP" | "BAL" | "RUN" | "CUS"
    swingLook: int = 10
    slBuf: float = 0.25
    slMinAtr: float = 0.8
    slMaxAtr: float = 3.5
    cTp1: float = 1.0
    cW1: float = 40.0
    cTp2: float = 2.0
    cW2: float = 30.0
    cTp3: float = 3.0
    cTrail: bool = False
    cBe: bool = True
    chLen: int = 22
    chMult: float = 3.0
    smallGuard: bool = True
    cgMaxPct: float = 7.0
    costMode: str = "Auto"         # "Auto" | "Custom"
    costCustom: float = 0.05


def _runtime_checks(p: Params) -> None:
    """Pine L103-L110 (runtime.error halts the script) plus a guard against misspelt option strings."""
    if p.dirMode not in ("Both", "Long only", "Short only"):
        raise ValueError(f"unknown dirMode {p.dirMode!r}")
    if p.profile not in ("AUTO", "HP", "BAL", "RUN", "CUS"):
        raise ValueError(f"unknown profile {p.profile!r}")
    if p.costMode not in ("Auto", "Custom"):
        raise ValueError(f"unknown costMode {p.costMode!r}")
    if p.slMinAtr > p.slMaxAtr:                                                     # L104
        raise ValueError("Stop distance min ATR must be less than or equal to max ATR.")
    if p.profile == "CUS":                                                          # L106
        if not (p.cTp1 < p.cTp2 and p.cTp2 < p.cTp3):                               # L107
            raise ValueError("Custom targets must satisfy TP1 < TP2 < TP3.")
        if p.cW1 + p.cW2 > 100:                                                     # L109
            raise ValueError("Custom TP1 and TP2 close percentages must total at most 100%; zero is allowed.")


def management_profile(p: Params, market) -> dict:
    """Pine L208-L218 -> the `mgmt` dict of simulate()."""
    is_crypto = market.sym_type == "crypto"
    profile = ("RUN" if is_crypto else "HP") if p.profile == "AUTO" else p.profile          # L208
    k1 = 0.3 if profile == "HP" else 1.0 if profile == "BAL" else 1.0 if profile == "RUN" else p.cTp1        # L209
    k2 = 1.5 if profile == "HP" else 2.0 if profile == "BAL" else 2.0 if profile == "RUN" else p.cTp2        # L210
    k3 = 4.0 if profile == "HP" else 3.0 if profile == "BAL" else 8.0 if profile == "RUN" else p.cTp3        # L211
    w1 = 0.50 if profile == "HP" else 0.40 if profile == "BAL" else 0.33 if profile == "RUN" else p.cW1 / 100  # L212
    w2 = 0.25 if profile == "HP" else 0.30 if profile == "BAL" else 0.33 if profile == "RUN" else p.cW2 / 100  # L213
    trailOn = profile == "HP" or profile == "RUN" or (profile == "CUS" and p.cTrail)        # L214
    trailFrom = 2 if profile == "RUN" else 1                                                # L217
    beOn = profile == "HP" or profile == "BAL" or (profile == "CUS" and p.cBe)              # L218
    return {"k1": float(k1), "k2": float(k2), "k3": float(k3), "w1": float(w1), "w2": float(w2),
            "trailOn": bool(trailOn), "trailFrom": int(trailFrom), "beOn": bool(beOn)}


def round_trip_cost_pct(p: Params, market) -> float:
    """Pine L194-L195: round-trip cost in PERCENT of price."""
    ticker = market.ticker
    hiCostMetal = ("XAG" in ticker) or ("SILVER" in ticker) or ("XPT" in ticker) or ("XCU" in ticker)   # L194
    if p.costMode == "Auto":                                                                           # L195
        return 0.10 if market.sym_type == "crypto" else 0.06 if hiCostMetal else 0.03
    return float(p.costCustom)


def compute_series(chart: dict, htf: dict, params: Params, market) -> dict:
    """Everything the script computes per bar BEFORE the trade model (Pine L114-L218).

    Returns the arrays simulate() needs (longSig, shortSig, slDistL, slDistS, chandL, chandS,
    trigNameL, trigNameS, scoreL, scoreS), the management profile, costPct and the diagnostic
    series (atr, htfTrend, ...).
    """
    p = params
    _runtime_checks(p)

    chart_t = np.asarray(chart["t"])
    open_s, high_s, low_s, close_s = _floats(chart["o"]), _floats(chart["h"]), _floats(chart["l"]), _floats(chart["c"])
    n = len(close_s)

    # ── Higher-timeframe trend (L114-L138, "Auto" mode) ──
    # L120: never request a timeframe lower than the chart -> the chart timeframe itself is used,
    # which with [1] is simply the previous chart bar.
    tf_seconds = int(market.tf_seconds)
    htf_seconds = int(market.htf_seconds)
    if htf_seconds <= tf_seconds:
        htf_bars, htf_effective_seconds = chart, tf_seconds
    else:
        htf_bars, htf_effective_seconds = htf, htf_seconds
    htfUse21 = htf_effective_seconds >= 86400                                   # L134 (Auto branch)
    htfEmaLen = 21 if htfUse21 else 50                                          # L135
    htfTrend_arr = request_security_prev(htf_bars["t"], htfTrendCalc(htf_bars, htfEmaLen), chart_t)  # L136-L138

    # ── Core series (L141-L147) ──
    atr_arr = ta_atr(high_s, low_s, close_s, 14)                                # L141
    ema21_arr = ta_ema(close_s, 21)                                             # L142
    ema55_arr = ta_ema(close_s, 55)                                             # L143
    ema200_arr = ta_ema(close_s, 200)                                           # L144
    stLine_arr, stDir_arr = ta_supertrend(high_s, low_s, close_s, p.stFactor, p.stLen)   # L145
    diP_arr, diM_arr, adx_arr = ta_dmi(high_s, low_s, close_s, 14, 14)          # L146
    rsi14_arr = ta_rsi(close_s, 14)                                             # L147
    # L148-L153 (rng14, chop, Bollinger/Keltner squeeze) are never read by the script: not ported.

    # Windowed built-ins that the signal lines reference (called on every bar in Pine).
    highestDon_arr = ta_highest(high_s, p.donLen)                               # ta.highest(high, donLen)   L170
    lowestDon_arr = ta_lowest(low_s, p.donLen)                                  # ta.lowest(low, donLen)     L171
    lowMinusEma_arr = ta_lowest(_arr(low_s) - ema21_arr, 5)                     # ta.lowest(low - ema21, 5)  L176
    highMinusEma_arr = ta_highest(_arr(high_s) - ema21_arr, 5)                  # ta.highest(high - ema21,5) L177
    swingLow_arr = ta_lowest(low_s, p.swingLook)                                # ta.lowest(low, swingLook)  L191
    swingHigh_arr = ta_highest(high_s, p.swingLook)                             # ta.highest(high, swingLook) L192
    chHigh_arr = ta_highest(high_s, p.chLen)                                    # ta.highest(high, chLen)    L204
    chLow_arr = ta_lowest(low_s, p.chLen)                                       # ta.lowest(low, chLen)      L205

    # Python-float views for the bar loop.
    atr_s, ema21_s, ema55_s, ema200_s = _floats(atr_arr), _floats(ema21_arr), _floats(ema55_arr), _floats(ema200_arr)
    stDir_s, diP_s, diM_s, adx_s, rsi14_s = (_floats(stDir_arr), _floats(diP_arr), _floats(diM_arr),
                                             _floats(adx_arr), _floats(rsi14_arr))
    htfTrend_s = _floats(htfTrend_arr)
    highestDon_s, lowestDon_s = _floats(highestDon_arr), _floats(lowestDon_arr)
    lowMinusEma_s, highMinusEma_s = _floats(lowMinusEma_arr), _floats(highMinusEma_arr)
    swingLow_s, swingHigh_s = _floats(swingLow_arr), _floats(swingHigh_arr)
    chHigh_s, chLow_s = _floats(chHigh_arr), _floats(chLow_arr)

    # ── Constants of the run ──
    costPct = round_trip_cost_pct(p, market)                                    # L194-L195
    smallTf = tf_seconds < 3600                                                 # L197
    mgmt = management_profile(p, market)                                        # L208-L218

    # ── Outputs ──
    scoreL_out = np.zeros(n, dtype=np.int64)
    scoreS_out = np.zeros(n, dtype=np.int64)
    longSig_out = np.zeros(n, dtype=bool)
    shortSig_out = np.zeros(n, dtype=bool)
    slDistL_out = np.full(n, NAN)
    slDistS_out = np.full(n, NAN)
    chandL_out = np.full(n, NAN)
    chandS_out = np.full(n, NAN)
    trigNameL_out = ["PB"] * n
    trigNameS_out = ["PB"] * n

    bar_index = 0

    def prev(series: list, k: int):
        """Pine history operator series[k] on the current bar: na when fewer than k previous bars exist."""
        j = bar_index - k
        return series[j] if j >= 0 else NAN

    for bar_index in range(n):
        # Current-bar values under their Pine names.
        open_, high, low, close = open_s[bar_index], high_s[bar_index], low_s[bar_index], close_s[bar_index]
        atr, ema21, ema55, ema200 = atr_s[bar_index], ema21_s[bar_index], ema55_s[bar_index], ema200_s[bar_index]
        stDir, diP, diM, adx, rsi14 = (stDir_s[bar_index], diP_s[bar_index], diM_s[bar_index],
                                       adx_s[bar_index], rsi14_s[bar_index])
        htfTrend = htfTrend_s[bar_index]

        # L150: tsm = (sign(close - close[20]) + sign(close - close[50]) + sign(close - close[100]) + sign(close - close[200])) / 4
        tsm = (pine_sign(close - prev(close_s, 20)) + pine_sign(close - prev(close_s, 50))
               + pine_sign(close - prev(close_s, 100)) + pine_sign(close - prev(close_s, 200))) / 4

        # L155-L164: scoreOf(d).  Every test is a comparison, so a na operand contributes 0.
        def scoreOf(d: int) -> int:
            s = 0
            s += 1 if htfTrend == d else 0                                      # L157
            s += 1 if (close - ema200) * d > 0 else 0                           # L158
            s += 1 if (ema21 - ema55) * d > 0 else 0                            # L159
            s += 1 if adx > p.adxMin else 0                                     # L160
            s += 1 if (adx > prev(adx_s, 3) and adx > 18) else 0                # L161
            s += 1 if (diP - diM) * d > 0 else 0                                # L162
            s += 1 if (rsi14 - 50) * d > 0 else 0                               # L163
            return s

        scoreL = scoreOf(1)                                                     # L166
        scoreS = scoreOf(-1)                                                    # L167

        # L170-L179: triggers (evaluated on bar close)
        donHi = prev(highestDon_s, 1)                                           # L170  ta.highest(high, donLen)[1]
        donLo = prev(lowestDon_s, 1)                                            # L171  ta.lowest(low, donLen)[1]
        donHi_1 = prev(highestDon_s, 2)                                         #       donHi[1]
        donLo_1 = prev(lowestDon_s, 2)                                          #       donLo[1]
        brkUp = close > donHi and prev(close_s, 1) <= donHi_1                   # L172
        brkDn = close < donLo and prev(close_s, 1) >= donLo_1                   # L173
        flipUp = stDir < 0 and prev(stDir_s, 1) > 0                             # L174
        flipDn = stDir > 0 and prev(stDir_s, 1) < 0                             # L175
        touchUp = lowMinusEma_s[bar_index] <= 0                                 # L176
        touchDn = highMinusEma_s[bar_index] >= 0                                # L177
        pbUp = stDir < 0 and touchUp and close > prev(high_s, 1) and close > ema21 and close > open_   # L178
        pbDn = stDir > 0 and touchDn and close < prev(low_s, 1) and close < ema21 and close < open_    # L179

        trigL = (p.useBrk and brkUp) or (p.useFlip and flipUp) or (p.usePb and pbUp)                   # L181
        trigS = (p.useBrk and brkDn) or (p.useFlip and flipDn) or (p.usePb and pbDn)                   # L182
        trigNameL = "BRK" if (p.useBrk and brkUp) else "FLIP" if (p.useFlip and flipUp) else "PB"      # L183
        trigNameS = "BRK" if (p.useBrk and brkDn) else "FLIP" if (p.useFlip and flipDn) else "PB"      # L184

        warm = bar_index >= 250                                                 # L186
        tsmL = (not p.useTsm) or tsm >= 1                                       # L187
        tsmS = (not p.useTsm) or tsm <= -1                                      # L188

        # L191-L192: stops - last swing beyond a buffer, clamped to [min, max] x ATR
        slDistL = pine_min(pine_max(close - (swingLow_s[bar_index] - p.slBuf * atr), p.slMinAtr * atr), p.slMaxAtr * atr)
        slDistS = pine_min(pine_max((swingHigh_s[bar_index] + p.slBuf * atr) - close, p.slMinAtr * atr), p.slMaxAtr * atr)

        # L196-L200: small-frame guard
        cgMinDist = costPct / 100 * close / (p.cgMaxPct / 100)                  # L198
        cgOkL = (not (p.smallGuard and smallTf)) or slDistL >= cgMinDist        # L199
        cgOkS = (not (p.smallGuard and smallTf)) or slDistS >= cgMinDist        # L200

        # L202-L203 (barstate.isconfirmed is always true on historical bars)
        longSig = (warm and trigL and scoreL >= p.minScore and tsmL
                   and p.dirMode != "Short only" and atr > 0 and cgOkL)
        shortSig = (warm and trigS and scoreS >= p.minScore and tsmS
                    and p.dirMode != "Long only" and atr > 0 and cgOkS)
        chandL = chHigh_s[bar_index] - p.chMult * atr                           # L204
        chandS = chLow_s[bar_index] + p.chMult * atr                            # L205

        scoreL_out[bar_index] = scoreL
        scoreS_out[bar_index] = scoreS
        longSig_out[bar_index] = bool(longSig)
        shortSig_out[bar_index] = bool(shortSig)
        slDistL_out[bar_index] = slDistL
        slDistS_out[bar_index] = slDistS
        chandL_out[bar_index] = chandL
        chandS_out[bar_index] = chandS
        trigNameL_out[bar_index] = trigNameL
        trigNameS_out[bar_index] = trigNameS

    return {
        "longSig": longSig_out, "shortSig": shortSig_out,
        "slDistL": slDistL_out, "slDistS": slDistS_out,
        "chandL": chandL_out, "chandS": chandS_out,
        "trigNameL": np.array(trigNameL_out, dtype=object), "trigNameS": np.array(trigNameS_out, dtype=object),
        "scoreL": scoreL_out, "scoreS": scoreS_out,
        "mgmt": mgmt, "costPct": costPct,
        # diagnostics
        "atr": atr_arr, "htfTrend": htfTrend_arr, "htfEmaLen": htfEmaLen,
        "ema21": ema21_arr, "ema55": ema55_arr, "ema200": ema200_arr,
        "stLine": stLine_arr, "stDir": stDir_arr,
        "diP": diP_arr, "diM": diM_arr, "adx": adx_arr, "rsi14": rsi14_arr,
    }


def run(chart: dict, htf: dict, params: Params, market) -> dict:
    """Thin wrapper: per-bar series from the chart / HTF data, then the trade simulator."""
    s = compute_series(chart, htf, params, market)
    result = simulate(chart["o"], chart["h"], chart["l"], chart["c"],
                      s["longSig"], s["shortSig"], s["slDistL"], s["slDistS"], s["chandL"], s["chandS"],
                      s["mgmt"], s["costPct"], mintick=market.mintick,
                      trigL=s["trigNameL"], trigS=s["trigNameS"], scoreL=s["scoreL"], scoreS=s["scoreS"])
    result["series"] = {"scoreL": s["scoreL"], "scoreS": s["scoreS"],
                        "longSig": s["longSig"], "shortSig": s["shortSig"],
                        "atr": s["atr"], "htfTrend": s["htfTrend"]}
    return result


# ───────────────────────────── E. Trade model (Pine L221-L502) ─────────────────────────────
@dataclass
class Trade:                       # Pine L221-L237 (line / box handles omitted)
    dir: int
    entryBar: int
    trig: str
    score: int
    entry: float
    sl: float
    sl0: float
    risk: float
    tp1: float
    tp2: float
    tp3: float                     # na -> nan
    hit1: bool = False
    hit2: bool = False
    hit3: bool = False
    realized: float = 0.0
    openW: float = 1.0


@dataclass
class Stats:                       # Pine L248-L264
    n: int = 0
    tp1: int = 0
    tp2: int = 0
    tp3: int = 0
    fullSl: int = 0
    win: int = 0
    gross: float = 0.0
    loss: float = 0.0
    net: float = 0.0
    peak: float = 0.0
    maxDd: float = 0.0
    costR: float = 0.0
    nL: int = 0
    netL: float = 0.0
    nS: int = 0
    netS: float = 0.0


def _trade_record(t: Trade, exit_fields: dict | None = None) -> dict:
    """A trade as plain Python values, keys in the order of ENGINE_SPEC section 4.
    `exit_fields` (exit_bar, exit_px, reason, gross_R, cost_R, R) is given for closed trades only."""
    x = exit_fields
    rec = {"dir": int(t.dir), "entry_bar": int(t.entryBar)}
    if x is not None:
        rec["exit_bar"] = x["exit_bar"]
    rec.update({"trig": str(t.trig), "score": int(t.score),
                "entry": float(t.entry), "sl0": float(t.sl0), "risk": float(t.risk),
                "tp1": float(t.tp1), "tp2": float(t.tp2), "tp3": None if na(t.tp3) else float(t.tp3),
                "hit1": bool(t.hit1), "hit2": bool(t.hit2), "hit3": bool(t.hit3)})
    if x is not None:
        rec.update({"exit_px": x["exit_px"], "reason": x["reason"],
                    "gross_R": x["gross_R"], "cost_R": x["cost_R"], "R": x["R"]})
    return rec


def simulate(o, h, l, c,                 # float arrays, one row per bar
             longSig, shortSig,          # bool arrays: the script's longSig / shortSig on each bar
             slDistL, slDistS,           # float arrays: stop distance used if a trade opens on that bar
             chandL, chandS,             # float arrays: chandelier values (nan = na)
             mgmt: dict,                 # {"k1","k2","k3","w1","w2","trailOn": bool,"trailFrom": 1|2,"beOn": bool}
             costPct: float,             # round-trip cost in PERCENT of price (e.g. 0.03)
             mintick: float = 0.01,
             trigL=None, trigS=None,     # optional arrays of trigger names ("BRK"/"FLIP"/"PB"); default "BRK"
             scoreL=None, scoreS=None    # optional int arrays; default 7
             ) -> dict:
    """The script's internal confirmed-close trade simulation: block `// 1)` (management), block
    `// 2)` (new signals), openTrade, closeTrade, activeStopReason and the Stats bookkeeping.

    Returns {"trades": [...closed trades in closing order...], "open_trade": None | {...}, "stats": {...}}.
    """
    open_s, high_s, low_s, close_s = _floats(o), _floats(h), _floats(l), _floats(c)
    n = len(close_s)
    longSig_s = np.asarray(longSig, dtype=bool).tolist()
    shortSig_s = np.asarray(shortSig, dtype=bool).tolist()
    slDistL_s, slDistS_s = _floats(slDistL), _floats(slDistS)
    chandL_s, chandS_s = _floats(chandL), _floats(chandS)
    trigNameL_s = ["BRK"] * n if trigL is None else [str(x) for x in trigL]
    trigNameS_s = ["BRK"] * n if trigS is None else [str(x) for x in trigS]
    scoreL_s = [7] * n if scoreL is None else [int(x) for x in scoreL]
    scoreS_s = [7] * n if scoreS is None else [int(x) for x in scoreS]

    k1, k2, k3 = float(mgmt["k1"]), float(mgmt["k2"]), float(mgmt["k3"])
    w1, w2 = float(mgmt["w1"]), float(mgmt["w2"])
    trailOn, trailFrom, beOn = bool(mgmt["trailOn"]), int(mgmt["trailFrom"]), bool(mgmt["beOn"])
    costPct = float(costPct)
    mintick = float(mintick)

    cur = None                     # L246  var Trade cur = na
    st = Stats()                   # L266  var Stats st = Stats.new()
    trades = []                    # closed trades, in closing order (output only)

    # Current-bar values; the three functions below read them exactly as the Pine functions read
    # the global `close` / `bar_index` (Python closures look the names up at call time).
    bar_index = 0
    open_ = high = low = close = NAN

    def activeStopReason(t: Trade) -> str:                                      # L321-L324
        stillInitial = t.sl == t.sl0
        fullPosition = t.openW >= 1.0 - 1e-9
        return ("SL" if fullPosition else "Remaining SL") if stillInitial else "BE/Trail"

    def closeTrade(t: Trade, px: float, reason: str) -> float:                  # L326-L356
        t.realized += pine_div(t.openW * (px - t.entry) * t.dir, t.risk)        # L327
        t.openW = 0.0                                                           # L328
        cR = pine_div(costPct / 100 * t.entry, t.risk)                          # L329
        R = t.realized - cR                                                     # L330
        st.n += 1                                                               # L331
        st.tp1 += 1 if t.hit1 else 0                                            # L332
        st.tp2 += 1 if t.hit2 else 0                                            # L333
        st.tp3 += 1 if t.hit3 else 0                                            # L334
        st.fullSl += 1 if reason == "SL" else 0                                 # L335
        st.win += 1 if R > 0 else 0                                             # L336
        st.gross += R if R > 0 else 0                                           # L337
        st.loss += -R if R < 0 else 0                                           # L338
        st.net += R                                                             # L339
        st.costR += cR                                                          # L340
        if t.dir == 1:                                                          # L341
            st.nL += 1
            st.netL += R
        else:                                                                   # L344
            st.nS += 1
            st.netS += R
        st.peak = pine_max(st.peak, st.net)                                     # L347
        st.maxDd = pine_max(st.maxDd, st.peak - st.net)                         # L348
        trades.append(_trade_record(t, {"exit_bar": int(bar_index), "exit_px": float(px), "reason": reason,
                                        "gross_R": float(t.realized), "cost_R": float(cR), "R": float(R)}))  # (output only)
        return R                                                                # L356

    def openTrade(d: int, trig: str, score: int) -> Trade:                      # L358-L381
        e = close                                                               # L359
        dist = slDistL_s[bar_index] if d == 1 else slDistS_s[bar_index]         # L360
        tp3 = e + d * k3 * dist                                                 # L361
        # L363: a far short target can fall at or below zero -> TP3 stays empty (na)
        return Trade(d, bar_index, trig, score, e, e - d * dist, e - d * dist, dist,
                     e + d * k1 * dist, e + d * k2 * dist, tp3 if tp3 > mintick else NAN)

    for bar_index in range(n):
        open_, high, low, close = open_s[bar_index], high_s[bar_index], low_s[bar_index], close_s[bar_index]
        managed = cur if DEBUG_CHECKS else None
        sl_before = cur.sl if (DEBUG_CHECKS and cur is not None) else NAN

        # ── 1) Internal confirmed-close simulation: manage only bars AFTER the entry close (L383-L486) ──
        # (evTp1 / evTp2 / evTp3 / evSl / evExit / lastR only feed alerts and are not ported.)
        if cur is not None and bar_index > cur.entryBar:                        # L390
            d = cur.dir                                                         # L391
            # L392-L396: the only trail price available at this opening is from the previous completed bar.
            if trailOn and (cur.hit1 if trailFrom == 1 else cur.hit2):          # L393
                tv = chandL_s[bar_index - 1] if d == 1 else chandS_s[bar_index - 1]      # L394  chandL[1] / chandS[1]
                if not na(tv):                                                  # L395
                    cur.sl = pine_max(cur.sl, tv) if d == 1 else pine_min(cur.sl, tv)   # L396
            # L397-L398: a pre-existing opening stop precedes every target and the unknown remaining range.
            openingStopHit = (open_ <= cur.sl) if d == 1 else (open_ >= cur.sl)          # L398
            if openingStopHit:                                                  # L399
                reason = activeStopReason(cur)                                  # L400
                closeTrade(cur, open_, reason)                                  # L403
                cur = None                                                      # L404
            else:                                                               # L405
                # L406: all targets already marketable at the opening fill at their fixed limit prices.
                if not cur.hit1 and ((open_ >= cur.tp1) if d == 1 else (open_ <= cur.tp1)):       # L407
                    cur.hit1 = True                                             # L408
                    w = pine_min(w1, cur.openW)                                 # L409
                    cur.realized += w * k1                                      # L410
                    cur.openW -= w                                              # L411
                    if beOn:                                                    # L412
                        cur.sl = pine_max(cur.sl, cur.entry) if d == 1 else pine_min(cur.sl, cur.entry)   # L413
                if (cur.openW > 1e-9 and cur.hit1 and not cur.hit2
                        and ((open_ >= cur.tp2) if d == 1 else (open_ <= cur.tp2))):              # L416
                    cur.hit2 = True                                             # L417
                    w = pine_min(w2, cur.openW)                                 # L418
                    cur.realized += w * k2                                      # L419
                    cur.openW -= w                                              # L420
                    cur.sl = pine_max(cur.sl, cur.tp1) if d == 1 else pine_min(cur.sl, cur.tp1)   # L421
                if cur.openW <= 1e-9:                                           # L424
                    closeTrade(cur, cur.tp2 if cur.hit2 else cur.tp1, "TP")     # L425
                    cur = None                                                  # L426
                if (cur is not None and cur.hit2 and not cur.hit3 and not na(cur.tp3)
                        and ((open_ >= cur.tp3) if d == 1 else (open_ <= cur.tp3))):              # L427
                    cur.hit3 = True                                             # L428
                    cur.realized += cur.openW * k3                              # L429
                    cur.openW = 0.0                                             # L430
                    closeTrade(cur, cur.tp3, "TP3")                             # L433
                    cur = None                                                  # L434
                if cur is not None:                                             # L435
                    # L436-L441: opening target fills are known events; their BE/TP2 stop is active now,
                    # an activated chandelier may use only the previous completed bar.
                    if trailOn and (cur.hit1 if trailFrom == 1 else cur.hit2):  # L438
                        tv = chandL_s[bar_index - 1] if d == 1 else chandS_s[bar_index - 1]      # L439
                        if not na(tv):                                          # L440
                            cur.sl = pine_max(cur.sl, tv) if d == 1 else pine_min(cur.sl, tv)   # L441
                    # L442-L443: unknown intrabar order remains stop-first after known opening events.
                    stopHit = (low <= cur.sl) if d == 1 else (high >= cur.sl)   # L443
                    if stopHit:                                                 # L444
                        px = open_ if ((d == 1 and open_ < cur.sl) or (d == -1 and open_ > cur.sl)) else cur.sl   # L445
                        reason = activeStopReason(cur)                          # L446
                        closeTrade(cur, px, reason)                             # L449
                        cur = None                                              # L450
                    else:                                                       # L451
                        # L452-L453: range-triggered stop changes are not rechecked on this bar; they
                        # become executable on the next bar.
                        if not cur.hit1 and ((high >= cur.tp1) if d == 1 else (low <= cur.tp1)):  # L454
                            cur.hit1 = True                                     # L455
                            w = pine_min(w1, cur.openW)                         # L456
                            cur.realized += w * k1                              # L457
                            cur.openW -= w                                      # L458
                            if beOn:                                            # L459
                                cur.sl = pine_max(cur.sl, cur.entry) if d == 1 else pine_min(cur.sl, cur.entry)   # L460
                        if (cur.openW > 1e-9 and cur.hit1 and not cur.hit2
                                and ((high >= cur.tp2) if d == 1 else (low <= cur.tp2))):         # L463
                            cur.hit2 = True                                     # L464
                            w = pine_min(w2, cur.openW)                         # L465
                            cur.realized += w * k2                              # L466
                            cur.openW -= w                                      # L467
                            cur.sl = pine_max(cur.sl, cur.tp1) if d == 1 else pine_min(cur.sl, cur.tp1)   # L468
                        if cur.openW <= 1e-9:                                   # L471
                            closeTrade(cur, cur.tp2 if cur.hit2 else cur.tp1, "TP")               # L472
                            cur = None                                          # L473
                        if (cur is not None and cur.hit2 and not cur.hit3 and not na(cur.tp3)
                                and ((high >= cur.tp3) if d == 1 else (low <= cur.tp3))):         # L474
                            cur.hit3 = True                                     # L475
                            cur.realized += cur.openW * k3                      # L476
                            cur.openW = 0.0                                     # L477
                            closeTrade(cur, cur.tp3, "TP3")                     # L480
                            cur = None                                          # L481
            # L482-L486 only extend drawings.

        if DEBUG_CHECKS and cur is not None:
            _check_live_trade(cur, sl_before if cur is managed else NAN)

        # ── 2) New signals on bar close; an opposite signal reverses an open trade (L488-L502) ──
        if longSig_s[bar_index] and (cur is None or cur.dir == -1):             # L491
            if cur is not None:                                                 # L492
                closeTrade(cur, close, "Reverse")                               # L493
            cur = openTrade(1, trigNameL_s[bar_index], scoreL_s[bar_index])     # L495
        elif shortSig_s[bar_index] and (cur is None or cur.dir == 1):           # L497
            if cur is not None:                                                 # L498
                closeTrade(cur, close, "Reverse")                               # L499
            cur = openTrade(-1, trigNameS_s[bar_index], scoreS_s[bar_index])    # L501

    return {"trades": trades,
            "open_trade": None if cur is None else _trade_record(cur),
            "stats": asdict(st)}


def _check_live_trade(t: Trade, sl_before: float) -> None:
    """Invariants of a trade that is still open after the management block (DEBUG_CHECKS only)."""
    assert 1e-9 < t.openW <= 1.0, f"openW out of range: {t.openW}"
    assert not t.hit3, "a trade with hit3 must already be closed"
    assert t.hit1 or not t.hit2, "hit2 without hit1"
    assert (t.sl - t.sl0) * t.dir >= 0, "stop looser than the initial stop"
    if not na(sl_before):
        assert (t.sl - sl_before) * t.dir >= 0, "stop moved away from price"


if __name__ == "__main__":
    import sys
    import time

    import datasets as ds

    for name in (sys.argv[1:] or ["OANDA_XAUUSD_4h"]):
        chart_ = ds.load(name)
        market_ = ds.market_of(name, chart_)
        htf_, src_ = ds.htf_bars(name, chart_)
        t0 = time.perf_counter()
        res = run(chart_, htf_, Params(), market_)
        dt_s = time.perf_counter() - t0
        print(f"{name}: bars={len(chart_['t'])} htf={src_} trades={len(res['trades'])} "
              f"open={'yes' if res['open_trade'] else 'no'} ({dt_s:.2f}s)")
        print("  ", res["stats"])
