#!/usr/bin/env python3
"""APEX Focus -- FAST research port (engine_b) of apex/APEX_Focus_original.pine.

Layout (see ENGINE_SPEC.md for the public interface):

  1. features(chart, htf, params, market) -> dict of per-bar numpy arrays
       (everything up to longSig / shortSig, slDist*, chand*; no trade-management parameter is used,
        except that costPct feeds the small-frame guard exactly as in the Pine script).
  2. _core(...)  numba kernel: the whole "// 1) management" + "// 2) new signals" state machine,
       openTrade / closeTrade / activeStopReason and the Stats bookkeeping.  Returns arrays.
  3. simulate(...) / run(...)  spec wrappers that turn the arrays into the result dict.
     simulate_arrays(...) is the same thing without the dict conversion (for parameter sweeps).

na handling (deliberate, not accidental):
  * na is float nan everywhere.
  * Pine: "any comparison with na is false".  All comparisons that can see a nan are done on scalars inside
    numba loops with the ordered operators  <  <=  >  >=  == , which IEEE-754 defines as False when an operand
    is nan -- i.e. exactly the Pine rule.  The operator != (True for nan under IEEE, False in Pine) is never
    applied to a float that may be nan, and `not (a > b)` is only written where the Pine source itself has
    that shape (ternary else-branches, `not cur.hit1`, `not (smallGuard and smallTf) or ...`).
  * Pine math.max / math.min return na if any argument is na -> _pmax / _pmin.
  * x[n] with fewer than n previous bars is na -> handled with explicit index guards.
  * Divisions use IEEE semantics (error_model="numpy"): they never raise inside the kernels.
  * No fastmath anywhere: expression order is the Pine order so results are bit-reproducible.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from numba import njit

NAN = float("nan")

# ───────────────────────────── public constants ─────────────────────────────
TRIG_NAMES = ("BRK", "FLIP", "PB")                       # trigger codes 0, 1, 2
REASONS = ("SL", "Remaining SL", "BE/Trail", "TP", "TP3", "Reverse")
R_SL, R_REM, R_BE, R_TP, R_TP3, R_REV = 0, 1, 2, 3, 4, 5

# columns of the closed-trade record array returned by the kernel
REC_COLS = ("dir", "entry_bar", "exit_bar", "trig", "score", "entry", "sl0", "risk", "tp1", "tp2", "tp3",
            "hit1", "hit2", "hit3", "exit_px", "reason", "gross_R", "cost_R", "R")
(C_DIR, C_EBAR, C_XBAR, C_TRIG, C_SCORE, C_ENTRY, C_SL0, C_RISK, C_TP1, C_TP2, C_TP3,
 C_HIT1, C_HIT2, C_HIT3, C_XPX, C_REASON, C_GROSS, C_COST, C_R) = range(19)
NREC = 19

# open-trade state vector returned by the kernel (O_HAS == 0 -> no open trade)
OPEN_COLS = ("has", "dir", "entry_bar", "trig", "score", "entry", "sl0", "risk", "tp1", "tp2", "tp3",
             "hit1", "hit2", "hit3", "sl", "realized", "openW")
(O_HAS, O_DIR, O_EBAR, O_TRIG, O_SCORE, O_ENTRY, O_SL0, O_RISK, O_TP1, O_TP2, O_TP3,
 O_HIT1, O_HIT2, O_HIT3, O_SL, O_REAL, O_OPENW) = range(17)
NOPEN = 17

# Stats vector (same order as the Pine `Stats` type)
STAT_KEYS = ("n", "tp1", "tp2", "tp3", "fullSl", "win", "gross", "loss", "net", "peak", "maxDd", "costR",
             "nL", "netL", "nS", "netS")
(S_N, S_TP1, S_TP2, S_TP3, S_FULLSL, S_WIN, S_GROSS, S_LOSS, S_NET, S_PEAK, S_MAXDD, S_COSTR,
 S_NL, S_NETL, S_NS, S_NETS) = range(16)
_STAT_INT = frozenset(("n", "tp1", "tp2", "tp3", "fullSl", "win", "nL", "nS"))

WARM_BARS = 250                                          # bool warm = bar_index >= 250


# ───────────────────────────── parameters ─────────────────────────────
@dataclass
class Params:                      # defaults == the Pine input defaults
    useBrk: bool = True;  donLen: int = 20
    useFlip: bool = True; stFactor: float = 3.0; stLen: int = 10
    usePb: bool = True
    minScore: int = 7;    adxMin: float = 25.0;  useTsm: bool = True
    dirMode: str = "Both"          # "Both" | "Long only" | "Short only"
    profile: str = "AUTO"          # "AUTO" | "HP" | "BAL" | "RUN" | "CUS"
    swingLook: int = 10;  slBuf: float = 0.25;   slMinAtr: float = 0.8;  slMaxAtr: float = 3.5
    cTp1: float = 1.0;    cW1: float = 40.0;     cTp2: float = 2.0;      cW2: float = 30.0;  cTp3: float = 3.0
    cTrail: bool = False; cBe: bool = True
    chLen: int = 22;      chMult: float = 3.0
    smallGuard: bool = True; cgMaxPct: float = 7.0
    costMode: str = "Auto"; costCustom: float = 0.05


def validate(params: Params) -> None:
    """The script's barstate.isfirst runtime.error() checks (the indicator would not run at all)."""
    if params.profile not in ("AUTO", "HP", "BAL", "RUN", "CUS"):
        raise ValueError(f"unknown profile {params.profile!r}")
    if params.slMinAtr > params.slMaxAtr:
        raise ValueError("Stop distance min ATR must be less than or equal to max ATR.")
    if params.profile == "CUS":
        if not (params.cTp1 < params.cTp2 and params.cTp2 < params.cTp3):
            raise ValueError("Custom targets must satisfy TP1 < TP2 < TP3.")
        if params.cW1 + params.cW2 > 100:
            raise ValueError("Custom TP1 and TP2 close percentages must total at most 100%; zero is allowed.")


def cost_pct(params: Params, market) -> float:
    """float costPct = costMode == "Auto" ? (crypto ? 0.10 : hiCostMetal ? 0.06 : 0.03) : costCustom"""
    if params.costMode == "Auto":
        if market.sym_type == "crypto":
            return 0.10
        tk = market.ticker
        hi_cost_metal = ("XAG" in tk) or ("SILVER" in tk) or ("XPT" in tk) or ("XCU" in tk)
        return 0.06 if hi_cost_metal else 0.03
    return float(params.costCustom)


def mgmt_of(params: Params, market) -> dict:
    """Management profile block of the script -> the `mgmt` dict of simulate()."""
    prof = params.profile
    if prof == "AUTO":
        prof = "RUN" if market.sym_type == "crypto" else "HP"
    if prof == "HP":
        k1, k2, k3, w1, w2 = 0.3, 1.5, 4.0, 0.50, 0.25
    elif prof == "BAL":
        k1, k2, k3, w1, w2 = 1.0, 2.0, 3.0, 0.40, 0.30
    elif prof == "RUN":
        k1, k2, k3, w1, w2 = 1.0, 2.0, 8.0, 0.33, 0.33
    else:
        k1, k2, k3, w1, w2 = params.cTp1, params.cTp2, params.cTp3, params.cW1 / 100, params.cW2 / 100
    return {
        "k1": float(k1), "k2": float(k2), "k3": float(k3), "w1": float(w1), "w2": float(w2),
        "trailOn": bool(prof == "HP" or prof == "RUN" or (prof == "CUS" and params.cTrail)),
        "trailFrom": 2 if prof == "RUN" else 1,
        "beOn": bool(prof == "HP" or prof == "BAL" or (prof == "CUS" and params.cBe)),
    }


# ───────────────────────────── na-aware scalar helpers ─────────────────────────────
@njit(cache=True, error_model="numpy")
def _pmax(a, b):
    """Pine math.max: na if any argument is na."""
    if math.isnan(a) or math.isnan(b):
        return NAN
    return a if a > b else b


@njit(cache=True, error_model="numpy")
def _pmin(a, b):
    """Pine math.min: na if any argument is na."""
    if math.isnan(a) or math.isnan(b):
        return NAN
    return a if a < b else b


@njit(cache=True, error_model="numpy")
def _psign(x):
    """Pine math.sign: na for na."""
    if math.isnan(x):
        return NAN
    if x > 0.0:
        return 1.0
    if x < 0.0:
        return -1.0
    return 0.0


# ───────────────────────────── indicator kernels ─────────────────────────────
@njit(cache=True, error_model="numpy")
def _true_range(h, l, c, handle_na):
    """ta.tr(handle_na): first bar is high-low when handle_na else na."""
    n = len(c)
    out = np.empty(n)
    for i in range(n):
        if i == 0:
            out[i] = h[i] - l[i] if handle_na else NAN
        else:
            out[i] = _pmax(_pmax(h[i] - l[i], abs(h[i] - c[i - 1])), abs(l[i] - c[i - 1]))
    return out


@njit(cache=True, error_model="numpy")
def _ema_like(src, length, alpha):
    """Shared recursion of ta.ema / ta.rma:
         sum := na(sum[1]) ? ta.sma(src, length) : alpha * src + (1 - alpha) * sum[1]
       ta.sma is na unless the last `length` values are all non-na, so the seed is the SMA of the first
       `length` consecutive non-na values (na before)."""
    n = len(src)
    out = np.full(n, NAN)
    prev = NAN
    run = 0                                   # consecutive non-na values ending at i
    for i in range(n):
        x = src[i]
        if math.isnan(x):
            run = 0
            prev = NAN
            continue
        run += 1
        if math.isnan(prev):
            if run >= length:
                s = 0.0
                for j in range(i - length + 1, i + 1):
                    s += src[j]
                prev = s / length
                out[i] = prev
        else:
            prev = alpha * x + (1.0 - alpha) * prev
            out[i] = prev
    return out


@njit(cache=True, error_model="numpy")
def _rma(src, length):
    return _ema_like(src, length, 1.0 / length)


@njit(cache=True, error_model="numpy")
def _ema(src, length):
    return _ema_like(src, length, 2.0 / (length + 1.0))


@njit(cache=True, error_model="numpy")
def _rolling_max(x, w):
    """ta.highest(x, w): last w bars including the current one; na until w non-na values fill the window."""
    n = len(x)
    out = np.full(n, NAN)
    if w < 1:
        return out
    last_nan = -1
    idx = -1                                  # index of the current window maximum (-1 = unknown)
    for i in range(n):
        xi = x[i]
        if math.isnan(xi):
            last_nan = i
            idx = -1
            continue
        start = i - w + 1
        if start < 0 or last_nan >= start:
            idx = -1
            continue
        if idx < start:
            idx = start
            m = x[start]
            for j in range(start + 1, i + 1):
                if x[j] >= m:
                    m = x[j]
                    idx = j
        elif xi >= x[idx]:
            idx = i
        out[i] = x[idx]
    return out


@njit(cache=True, error_model="numpy")
def _rolling_min(x, w):
    """ta.lowest(x, w): see _rolling_max."""
    n = len(x)
    out = np.full(n, NAN)
    if w < 1:
        return out
    last_nan = -1
    idx = -1
    for i in range(n):
        xi = x[i]
        if math.isnan(xi):
            last_nan = i
            idx = -1
            continue
        start = i - w + 1
        if start < 0 or last_nan >= start:
            idx = -1
            continue
        if idx < start:
            idx = start
            m = x[start]
            for j in range(start + 1, i + 1):
                if x[j] <= m:
                    m = x[j]
                    idx = j
        elif xi <= x[idx]:
            idx = i
        out[i] = x[idx]
    return out


@njit(cache=True, error_model="numpy")
def _supertrend(h, l, c, factor, atr):
    """ta.supertrend(factor, atrPeriod) with atr = ta.atr(atrPeriod) passed in.
       Returns (superTrend, direction); direction < 0 means up-trend.  direction is never na."""
    n = len(c)
    st = np.empty(n)
    direction = np.empty(n)
    prev_lower = NAN                          # FINAL lowerBand / upperBand / superTrend of the previous bar
    prev_upper = NAN
    prev_st = NAN
    for i in range(n):
        src = (h[i] + l[i]) / 2.0             # hl2
        a = atr[i]
        upper = src + factor * a
        lower = src - factor * a
        pl = 0.0 if math.isnan(prev_lower) else prev_lower      # nz(lowerBand[1])
        pu = 0.0 if math.isnan(prev_upper) else prev_upper      # nz(upperBand[1])
        c1 = c[i - 1] if i > 0 else NAN                         # close[1]
        a1 = atr[i - 1] if i > 0 else NAN                       # atr[1]
        # lowerBand := lowerBand > prevLowerBand or close[1] < prevLowerBand ? lowerBand : prevLowerBand
        if not (lower > pl or c1 < pl):
            lower = pl
        # upperBand := upperBand < prevUpperBand or close[1] > prevUpperBand ? upperBand : prevUpperBand
        if not (upper < pu or c1 > pu):
            upper = pu
        if math.isnan(a1):
            d = 1.0
        elif prev_st == pu:
            d = -1.0 if c[i] > upper else 1.0
        else:
            d = 1.0 if c[i] < lower else -1.0
        s = lower if d == -1.0 else upper
        st[i] = s
        direction[i] = d
        prev_lower = lower
        prev_upper = upper
        prev_st = s
    return st, direction


@njit(cache=True, error_model="numpy")
def _dmi(h, l, c, length, smooth):
    """ta.dmi(length, smooth) -> (plus, minus, adx)."""
    n = len(c)
    plus_dm = np.full(n, NAN)
    minus_dm = np.full(n, NAN)
    for i in range(1, n):
        up = h[i] - h[i - 1]                  # change(high)
        down = -(l[i] - l[i - 1])             # -change(low)
        if not math.isnan(up):
            plus_dm[i] = up if (up > down and up > 0.0) else 0.0
        if not math.isnan(down):
            minus_dm[i] = down if (down > up and down > 0.0) else 0.0
    trur = _rma(_true_range(h, l, c, False), length)
    rp = _rma(plus_dm, length)
    rm = _rma(minus_dm, length)
    plus = np.empty(n)
    minus = np.empty(n)
    dx = np.empty(n)
    last_p = NAN
    last_m = NAN
    for i in range(n):
        v = 100.0 * rp[i] / trur[i]
        if not math.isnan(v):                 # fixnan
            last_p = v
        v = 100.0 * rm[i] / trur[i]
        if not math.isnan(v):
            last_m = v
        plus[i] = last_p
        minus[i] = last_m
        s = last_p + last_m
        den = 1.0 if s == 0.0 else s          # sum == 0 ? 1 : sum   (na stays na)
        dx[i] = abs(last_p - last_m) / den
    adx = _rma(dx, smooth)
    for i in range(n):
        adx[i] = 100.0 * adx[i]
    return plus, minus, adx


@njit(cache=True, error_model="numpy")
def _rsi(c, length):
    n = len(c)
    u = np.full(n, NAN)
    d = np.full(n, NAN)
    for i in range(1, n):
        ch = c[i] - c[i - 1]
        u[i] = _pmax(ch, 0.0)
        d[i] = _pmax(-ch, 0.0)
    ru = _rma(u, length)
    rd = _rma(d, length)
    out = np.empty(n)
    for i in range(n):
        if rd[i] == 0.0:
            out[i] = 100.0
        elif ru[i] == 0.0:
            out[i] = 0.0
        else:
            out[i] = 100.0 - 100.0 / (1.0 + ru[i] / rd[i])
    return out


@njit(cache=True, error_model="numpy")
def _tsm(c):
    """(sign(c - c[20]) + sign(c - c[50]) + sign(c - c[100]) + sign(c - c[200])) / 4 ; na while c[200] is na."""
    n = len(c)
    out = np.full(n, NAN)
    for i in range(200, n):
        out[i] = (_psign(c[i] - c[i - 20]) + _psign(c[i] - c[i - 50]) + _psign(c[i] - c[i - 100])
                  + _psign(c[i] - c[i - 200])) / 4.0
    return out


@njit(cache=True, error_model="numpy")
def _htf_trend_calc(h, l, c, ema_len):
    """htfTrendCalc(emaLen) evaluated on the higher-timeframe bars (values -1 / 0 / +1, never na)."""
    n = len(c)
    atr10 = _rma(_true_range(h, l, c, True), 10)
    _, d = _supertrend(h, l, c, 3.0, atr10)
    e = _ema(c, ema_len)
    out = np.empty(n)
    for i in range(n):
        if math.isnan(e[i]) or math.isnan(d[i]):
            out[i] = 0.0
        elif c[i] > e[i] and d[i] < 0.0:
            out[i] = 1.0
        elif c[i] < e[i] and d[i] > 0.0:
            out[i] = -1.0
        else:
            out[i] = 0.0
    return out


@njit(cache=True, error_model="numpy")
def _base_kernel(h, l, c):
    """Parameter-free core series of the script."""
    tr = _true_range(h, l, c, True)
    atr = _rma(tr, 14)
    ema21 = _ema(c, 21)
    ema55 = _ema(c, 55)
    ema200 = _ema(c, 200)
    di_p, di_m, adx = _dmi(h, l, c, 14, 14)
    rsi14 = _rsi(c, 14)
    tsm = _tsm(c)
    return tr, atr, ema21, ema55, ema200, di_p, di_m, adx, rsi14, tsm


@njit(cache=True, error_model="numpy")
def _param_kernel(o, h, l, c, tr, atr, ema21, ema55, ema200, di_p, di_m, adx, rsi14, tsm, htf_trend,
                  use_brk, don_len, use_flip, st_factor, st_len, use_pb, min_score, adx_min, use_tsm,
                  allow_long, allow_short, swing_look, sl_buf, sl_min_atr, sl_max_atr, ch_len, ch_mult,
                  guard_on, costPct, cg_max_pct):
    """Everything between "Core series" and "Management profile" that depends on the inputs."""
    n = len(c)
    st_atr = atr if st_len == 14 else _rma(tr, st_len)
    st_line, st_dir = _supertrend(h, l, c, st_factor, st_atr)

    don_hi_raw = _rolling_max(h, don_len)     # ta.highest(high, donLen)   (shifted by [1] below)
    don_lo_raw = _rolling_min(l, don_len)
    lo_ema = np.empty(n)
    hi_ema = np.empty(n)
    for i in range(n):
        lo_ema[i] = l[i] - ema21[i]
        hi_ema[i] = h[i] - ema21[i]
    touch_lo = _rolling_min(lo_ema, 5)        # ta.lowest(low - ema21, 5)
    touch_hi = _rolling_max(hi_ema, 5)        # ta.highest(high - ema21, 5)
    swing_lo = _rolling_min(l, swing_look)
    swing_hi = _rolling_max(h, swing_look)
    ch_hi = _rolling_max(h, ch_len)
    ch_lo = _rolling_min(l, ch_len)

    score_l = np.zeros(n, dtype=np.int64)
    score_s = np.zeros(n, dtype=np.int64)
    brk_up = np.zeros(n, dtype=np.bool_)
    brk_dn = np.zeros(n, dtype=np.bool_)
    flip_up = np.zeros(n, dtype=np.bool_)
    flip_dn = np.zeros(n, dtype=np.bool_)
    pb_up = np.zeros(n, dtype=np.bool_)
    pb_dn = np.zeros(n, dtype=np.bool_)
    trig_l = np.zeros(n, dtype=np.bool_)
    trig_s = np.zeros(n, dtype=np.bool_)
    trig_code_l = np.empty(n, dtype=np.int64)
    trig_code_s = np.empty(n, dtype=np.int64)
    sl_dist_l = np.empty(n)
    sl_dist_s = np.empty(n)
    chand_l = np.empty(n)
    chand_s = np.empty(n)
    cg_ok_l = np.zeros(n, dtype=np.bool_)
    cg_ok_s = np.zeros(n, dtype=np.bool_)
    long_sig = np.zeros(n, dtype=np.bool_)
    short_sig = np.zeros(n, dtype=np.bool_)
    don_hi = np.full(n, NAN)
    don_lo = np.full(n, NAN)

    for i in range(n):
        ci = c[i]
        a = atr[i]
        # ── scoreOf(+1) / scoreOf(-1); every comparison is False when an operand is na
        common = 0
        if adx[i] > adx_min:
            common += 1
        if i >= 3 and adx[i] > adx[i - 3] and adx[i] > 18.0:
            common += 1
        sl_ = common
        ss_ = common
        ht = htf_trend[i]
        if ht == 1.0:
            sl_ += 1
        if ht == -1.0:
            ss_ += 1
        v = ci - ema200[i]
        if v * 1.0 > 0.0:
            sl_ += 1
        if v * -1.0 > 0.0:
            ss_ += 1
        v = ema21[i] - ema55[i]
        if v * 1.0 > 0.0:
            sl_ += 1
        if v * -1.0 > 0.0:
            ss_ += 1
        v = di_p[i] - di_m[i]
        if v * 1.0 > 0.0:
            sl_ += 1
        if v * -1.0 > 0.0:
            ss_ += 1
        v = rsi14[i] - 50.0
        if v * 1.0 > 0.0:
            sl_ += 1
        if v * -1.0 > 0.0:
            ss_ += 1
        score_l[i] = sl_
        score_s[i] = ss_

        # ── triggers
        if i >= 1:
            don_hi[i] = don_hi_raw[i - 1]
            don_lo[i] = don_lo_raw[i - 1]
        b_up = False
        b_dn = False
        if i >= 2:                            # close[1] <= donHi[1] needs two previous bars
            b_up = ci > don_hi[i] and c[i - 1] <= don_hi[i - 1]
            b_dn = ci < don_lo[i] and c[i - 1] >= don_lo[i - 1]
        f_up = False
        f_dn = False
        p_up = False
        p_dn = False
        sd = st_dir[i]
        if i >= 1:
            f_up = sd < 0.0 and st_dir[i - 1] > 0.0
            f_dn = sd > 0.0 and st_dir[i - 1] < 0.0
            p_up = sd < 0.0 and touch_lo[i] <= 0.0 and ci > h[i - 1] and ci > ema21[i] and ci > o[i]
            p_dn = sd > 0.0 and touch_hi[i] >= 0.0 and ci < l[i - 1] and ci < ema21[i] and ci < o[i]
        brk_up[i] = b_up
        brk_dn[i] = b_dn
        flip_up[i] = f_up
        flip_dn[i] = f_dn
        pb_up[i] = p_up
        pb_dn[i] = p_dn
        t_l = (use_brk and b_up) or (use_flip and f_up) or (use_pb and p_up)
        t_s = (use_brk and b_dn) or (use_flip and f_dn) or (use_pb and p_dn)
        trig_l[i] = t_l
        trig_s[i] = t_s
        trig_code_l[i] = 0 if (use_brk and b_up) else (1 if (use_flip and f_up) else 2)
        trig_code_s[i] = 0 if (use_brk and b_dn) else (1 if (use_flip and f_dn) else 2)

        # ── stops, chandelier, cost guard
        d_l = _pmin(_pmax(ci - (swing_lo[i] - sl_buf * a), sl_min_atr * a), sl_max_atr * a)
        d_s = _pmin(_pmax((swing_hi[i] + sl_buf * a) - ci, sl_min_atr * a), sl_max_atr * a)
        sl_dist_l[i] = d_l
        sl_dist_s[i] = d_s
        chand_l[i] = ch_hi[i] - ch_mult * a
        chand_s[i] = ch_lo[i] + ch_mult * a
        cg_min = costPct / 100.0 * ci / (cg_max_pct / 100.0)
        ok_l = (not guard_on) or d_l >= cg_min
        ok_s = (not guard_on) or d_s >= cg_min
        cg_ok_l[i] = ok_l
        cg_ok_s[i] = ok_s

        # ── signals
        warm = i >= WARM_BARS
        tsm_l = (not use_tsm) or tsm[i] >= 1.0
        tsm_s = (not use_tsm) or tsm[i] <= -1.0
        long_sig[i] = warm and t_l and sl_ >= min_score and tsm_l and allow_long and a > 0.0 and ok_l
        short_sig[i] = warm and t_s and ss_ >= min_score and tsm_s and allow_short and a > 0.0 and ok_s

    return (st_line, st_dir, don_hi, don_lo, score_l, score_s, brk_up, brk_dn, flip_up, flip_dn, pb_up, pb_dn,
            trig_l, trig_s, trig_code_l, trig_code_s, sl_dist_l, sl_dist_s, chand_l, chand_s,
            cg_ok_l, cg_ok_s, long_sig, short_sig)


# ───────────────────────────── features ─────────────────────────────
def _f64(x):
    return np.ascontiguousarray(x, dtype=np.float64)


def htf_trend(chart: dict, htf: dict, market) -> np.ndarray:
    """request.security(tickerid, htf, htfTrendCalc(len)[1], lookahead_on) on every chart bar (nan = na)."""
    tf_s = int(market.tf_seconds)
    htf_s = int(market.htf_seconds)
    if htf_s <= tf_s:                         # script never requests a lower timeframe: chart tf itself
        bars, htf_s = chart, tf_s
    elif htf is None:
        raise ValueError("htf bars are required when the higher timeframe is longer than the chart timeframe")
    else:
        bars = htf
    ema_len = 21 if htf_s >= 86400 else 50
    trend = _htf_trend_calc(_f64(bars["h"]), _f64(bars["l"]), _f64(bars["c"]), ema_len)
    j = np.searchsorted(np.asarray(bars["t"]), np.asarray(chart["t"]), side="right") - 1   # containing HTF bar
    k = j - 1                                 # the HTF bar before it ([1])
    out = np.full(len(chart["t"]), NAN)
    ok = k >= 0
    out[ok] = trend[k[ok]]
    return out


def base_features(chart: dict, htf: dict, market) -> dict:
    """Series that do not depend on Params (cache this per dataset in parameter sweeps)."""
    h, l, c = _f64(chart["h"]), _f64(chart["l"]), _f64(chart["c"])
    tr, atr, ema21, ema55, ema200, di_p, di_m, adx, rsi14, tsm = _base_kernel(h, l, c)
    return {"tr": tr, "atr": atr, "ema21": ema21, "ema55": ema55, "ema200": ema200, "diP": di_p, "diM": di_m,
            "adx": adx, "rsi14": rsi14, "tsm": tsm, "htfTrend": htf_trend(chart, htf, market)}


def features(chart: dict, htf: dict, params: Params, market, base: dict | None = None) -> dict:
    """All per-bar series of the script up to longSig / shortSig (no trade management).

    `base` may be a previous base_features() result for the same dataset.  The returned dict also carries the
    scalars costPct (Auto/Custom cost, also used by the small-frame guard) and mintick."""
    o, h, l, c = _f64(chart["o"]), _f64(chart["h"]), _f64(chart["l"]), _f64(chart["c"])
    if base is None:
        base = base_features(chart, htf, market)
    p = params
    cp = cost_pct(p, market)
    guard_on = bool(p.smallGuard) and int(market.tf_seconds) < 3600
    (st_line, st_dir, don_hi, don_lo, score_l, score_s, brk_up, brk_dn, flip_up, flip_dn, pb_up, pb_dn,
     trig_l, trig_s, trig_code_l, trig_code_s, sl_dist_l, sl_dist_s, chand_l, chand_s,
     cg_ok_l, cg_ok_s, long_sig, short_sig) = _param_kernel(
        o, h, l, c, base["tr"], base["atr"], base["ema21"], base["ema55"], base["ema200"],
        base["diP"], base["diM"], base["adx"], base["rsi14"], base["tsm"], base["htfTrend"],
        bool(p.useBrk), int(p.donLen), bool(p.useFlip), float(p.stFactor), int(p.stLen), bool(p.usePb),
        int(p.minScore), float(p.adxMin), bool(p.useTsm),
        p.dirMode != "Short only", p.dirMode != "Long only",
        int(p.swingLook), float(p.slBuf), float(p.slMinAtr), float(p.slMaxAtr), int(p.chLen), float(p.chMult),
        guard_on, float(cp), float(p.cgMaxPct))
    f = dict(base)
    f.update({
        "stLine": st_line, "stDir": st_dir, "donHi": don_hi, "donLo": don_lo,
        "scoreL": score_l, "scoreS": score_s,
        "brkUp": brk_up, "brkDn": brk_dn, "flipUp": flip_up, "flipDn": flip_dn, "pbUp": pb_up, "pbDn": pb_dn,
        "trigL": trig_l, "trigS": trig_s, "trigCodeL": trig_code_l, "trigCodeS": trig_code_s,
        "slDistL": sl_dist_l, "slDistS": sl_dist_s, "chandL": chand_l, "chandS": chand_s,
        "cgOkL": cg_ok_l, "cgOkS": cg_ok_s, "longSig": long_sig, "shortSig": short_sig,
        "costPct": cp, "mintick": float(market.mintick),
    })
    return f


# ───────────────────────────── trade kernel ─────────────────────────────
@njit(cache=True, error_model="numpy")
def _close_trade(stats, rec, k, bar, d, entry_bar, trig, score, entry, sl0, risk, tp1, tp2, tp3,
                 hit1, hit2, hit3, realized, open_w, px, reason, costPct):
    """closeTrade(t, px, reason): books the remaining weight, the cost and every Stats field."""
    realized = realized + open_w * (px - entry) * d / risk
    c_r = costPct / 100.0 * entry / risk
    r = realized - c_r
    stats[S_N] += 1.0
    if hit1:
        stats[S_TP1] += 1.0
    if hit2:
        stats[S_TP2] += 1.0
    if hit3:
        stats[S_TP3] += 1.0
    if reason == R_SL:
        stats[S_FULLSL] += 1.0
    if r > 0.0:
        stats[S_WIN] += 1.0
        stats[S_GROSS] += r
    if r < 0.0:
        stats[S_LOSS] += -r
    stats[S_NET] += r
    stats[S_COSTR] += c_r
    if d == 1.0:
        stats[S_NL] += 1.0
        stats[S_NETL] += r
    else:
        stats[S_NS] += 1.0
        stats[S_NETS] += r
    stats[S_PEAK] = _pmax(stats[S_PEAK], stats[S_NET])
    stats[S_MAXDD] = _pmax(stats[S_MAXDD], stats[S_PEAK] - stats[S_NET])
    rec[k, C_DIR] = d
    rec[k, C_EBAR] = entry_bar
    rec[k, C_XBAR] = bar
    rec[k, C_TRIG] = trig
    rec[k, C_SCORE] = score
    rec[k, C_ENTRY] = entry
    rec[k, C_SL0] = sl0
    rec[k, C_RISK] = risk
    rec[k, C_TP1] = tp1
    rec[k, C_TP2] = tp2
    rec[k, C_TP3] = tp3
    rec[k, C_HIT1] = 1.0 if hit1 else 0.0
    rec[k, C_HIT2] = 1.0 if hit2 else 0.0
    rec[k, C_HIT3] = 1.0 if hit3 else 0.0
    rec[k, C_XPX] = px
    rec[k, C_REASON] = reason
    rec[k, C_GROSS] = realized
    rec[k, C_COST] = c_r
    rec[k, C_R] = r


@njit(cache=True, error_model="numpy")
def _stop_reason(sl, sl0, open_w):
    """activeStopReason(t)"""
    if sl == sl0:
        return R_SL if open_w >= 1.0 - 1e-9 else R_REM
    return R_BE


@njit(cache=True, error_model="numpy")
def _core(o, h, l, c, long_sig, short_sig, sl_dist_l, sl_dist_s, chand_l, chand_s,
          trig_l, trig_s, score_l, score_s,
          k1, k2, k3, w1, w2, trail_on, trail_from, be_on, costPct, mintick):
    """Bar loop of the script's trade model.  Returns (closed-trade records, open-trade state, Stats vector)."""
    n = len(c)
    cap = 0
    for i in range(n):
        if long_sig[i] or short_sig[i]:
            cap += 1                           # every trade is opened on a signal bar
    rec = np.empty((cap, NREC))
    k = 0
    stats = np.zeros(16)

    has = False                                # not na(cur)
    d = 1.0
    entry_bar = 0
    trig = 0
    score = 0
    entry = 0.0
    sl = 0.0
    sl0 = 0.0
    risk = 0.0
    tp1 = 0.0
    tp2 = 0.0
    tp3 = 0.0
    hit1 = False
    hit2 = False
    hit3 = False
    realized = 0.0
    open_w = 1.0

    for i in range(n):
        oi = o[i]
        hi = h[i]
        li = l[i]
        ci = c[i]

        # ── 1) manage only bars AFTER the entry close
        if has and i > entry_bar:
            is_long = d == 1.0
            # trail from the previous completed bar
            if trail_on and (hit1 if trail_from == 1 else hit2):
                tv = chand_l[i - 1] if is_long else chand_s[i - 1]
                if not math.isnan(tv):
                    sl = _pmax(sl, tv) if is_long else _pmin(sl, tv)
            opening_stop_hit = (oi <= sl) if is_long else (oi >= sl)
            if opening_stop_hit:
                _close_trade(stats, rec, k, i, d, entry_bar, trig, score, entry, sl0, risk, tp1, tp2, tp3,
                             hit1, hit2, hit3, realized, open_w, oi, _stop_reason(sl, sl0, open_w), costPct)
                k += 1
                has = False
            else:
                # targets already marketable at the opening
                if (not hit1) and ((oi >= tp1) if is_long else (oi <= tp1)):
                    hit1 = True
                    w = w1 if w1 < open_w else open_w
                    realized += w * k1
                    open_w -= w
                    if be_on:
                        sl = _pmax(sl, entry) if is_long else _pmin(sl, entry)
                if open_w > 1e-9 and hit1 and (not hit2) and ((oi >= tp2) if is_long else (oi <= tp2)):
                    hit2 = True
                    w = w2 if w2 < open_w else open_w
                    realized += w * k2
                    open_w -= w
                    sl = _pmax(sl, tp1) if is_long else _pmin(sl, tp1)
                if open_w <= 1e-9:
                    _close_trade(stats, rec, k, i, d, entry_bar, trig, score, entry, sl0, risk, tp1, tp2, tp3,
                                 hit1, hit2, hit3, realized, open_w, tp2 if hit2 else tp1, R_TP, costPct)
                    k += 1
                    has = False
                if has and hit2 and (not hit3) and (not math.isnan(tp3)) and \
                        ((oi >= tp3) if is_long else (oi <= tp3)):
                    hit3 = True
                    realized += open_w * k3
                    open_w = 0.0
                    _close_trade(stats, rec, k, i, d, entry_bar, trig, score, entry, sl0, risk, tp1, tp2, tp3,
                                 hit1, hit2, hit3, realized, open_w, tp3, R_TP3, costPct)
                    k += 1
                    has = False
                if has:
                    # trail again: opening fills may have activated it (still the previous bar's value)
                    if trail_on and (hit1 if trail_from == 1 else hit2):
                        tv = chand_l[i - 1] if is_long else chand_s[i - 1]
                        if not math.isnan(tv):
                            sl = _pmax(sl, tv) if is_long else _pmin(sl, tv)
                    stop_hit = (li <= sl) if is_long else (hi >= sl)
                    if stop_hit:
                        px = oi if ((is_long and oi < sl) or ((not is_long) and oi > sl)) else sl
                        _close_trade(stats, rec, k, i, d, entry_bar, trig, score, entry, sl0, risk, tp1, tp2, tp3,
                                     hit1, hit2, hit3, realized, open_w, px, _stop_reason(sl, sl0, open_w),
                                     costPct)
                        k += 1
                        has = False
                    else:
                        # range targets; the moved stop is not re-checked on this bar
                        if (not hit1) and ((hi >= tp1) if is_long else (li <= tp1)):
                            hit1 = True
                            w = w1 if w1 < open_w else open_w
                            realized += w * k1
                            open_w -= w
                            if be_on:
                                sl = _pmax(sl, entry) if is_long else _pmin(sl, entry)
                        if open_w > 1e-9 and hit1 and (not hit2) and ((hi >= tp2) if is_long else (li <= tp2)):
                            hit2 = True
                            w = w2 if w2 < open_w else open_w
                            realized += w * k2
                            open_w -= w
                            sl = _pmax(sl, tp1) if is_long else _pmin(sl, tp1)
                        if open_w <= 1e-9:
                            _close_trade(stats, rec, k, i, d, entry_bar, trig, score, entry, sl0, risk,
                                         tp1, tp2, tp3, hit1, hit2, hit3, realized, open_w,
                                         tp2 if hit2 else tp1, R_TP, costPct)
                            k += 1
                            has = False
                        if has and hit2 and (not hit3) and (not math.isnan(tp3)) and \
                                ((hi >= tp3) if is_long else (li <= tp3)):
                            hit3 = True
                            realized += open_w * k3
                            open_w = 0.0
                            _close_trade(stats, rec, k, i, d, entry_bar, trig, score, entry, sl0, risk,
                                         tp1, tp2, tp3, hit1, hit2, hit3, realized, open_w, tp3, R_TP3, costPct)
                            k += 1
                            has = False

        # ── 2) new signals on bar close (opposite signal reverses an open trade)
        new_dir = 0.0
        if long_sig[i] and ((not has) or d == -1.0):
            new_dir = 1.0
        elif short_sig[i] and ((not has) or d == 1.0):
            new_dir = -1.0
        if new_dir != 0.0:
            if has:
                _close_trade(stats, rec, k, i, d, entry_bar, trig, score, entry, sl0, risk, tp1, tp2, tp3,
                             hit1, hit2, hit3, realized, open_w, ci, R_REV, costPct)
                k += 1
            # openTrade(d, trig, score)
            d = new_dir
            if d == 1.0:
                dist = sl_dist_l[i]
                trig = trig_l[i]
                score = score_l[i]
            else:
                dist = sl_dist_s[i]
                trig = trig_s[i]
                score = score_s[i]
            entry = ci
            t3 = entry + d * k3 * dist
            sl = entry - d * dist
            sl0 = sl
            risk = dist
            tp1 = entry + d * k1 * dist
            tp2 = entry + d * k2 * dist
            tp3 = t3 if t3 > mintick else NAN      # a far short target at/below zero: no TP3
            entry_bar = i
            hit1 = False
            hit2 = False
            hit3 = False
            realized = 0.0
            open_w = 1.0
            has = True

    op = np.zeros(NOPEN)
    if has:
        op[O_HAS] = 1.0
        op[O_DIR] = d
        op[O_EBAR] = entry_bar
        op[O_TRIG] = trig
        op[O_SCORE] = score
        op[O_ENTRY] = entry
        op[O_SL0] = sl0
        op[O_RISK] = risk
        op[O_TP1] = tp1
        op[O_TP2] = tp2
        op[O_TP3] = tp3
        op[O_HIT1] = 1.0 if hit1 else 0.0
        op[O_HIT2] = 1.0 if hit2 else 0.0
        op[O_HIT3] = 1.0 if hit3 else 0.0
        op[O_SL] = sl
        op[O_REAL] = realized
        op[O_OPENW] = open_w
    return rec[:k], op, stats


# ───────────────────────────── wrappers ─────────────────────────────
def _trig_codes(arr, n, names):
    """None -> all "BRK"; integer array -> trigger codes; anything else -> array of names."""
    if arr is None:
        return np.zeros(n, dtype=np.int64)
    a = np.asarray(arr)
    if a.dtype.kind in "iu":
        return np.ascontiguousarray(a, dtype=np.int64)
    out = np.empty(len(a), dtype=np.int64)
    lookup = {nm: i for i, nm in enumerate(names)}
    for i, nm in enumerate(a.tolist()):
        nm = str(nm)
        code = lookup.get(nm)
        if code is None:
            code = lookup[nm] = len(names)
            names.append(nm)
        out[i] = code
    return out


def _score_arr(arr, n):
    if arr is None:
        return np.full(n, 7, dtype=np.int64)
    return np.ascontiguousarray(arr, dtype=np.int64)


def simulate_arrays(o, h, l, c, longSig, shortSig, slDistL, slDistS, chandL, chandS, mgmt, costPct,
                    mintick=0.01, trigCodeL=None, trigCodeS=None, scoreL=None, scoreS=None):
    """simulate() without the dict conversion -> (rec[n_trades, len(REC_COLS)], open_state[len(OPEN_COLS)],
    stats[len(STAT_KEYS)]).  Trigger arguments are integer codes (index into TRIG_NAMES)."""
    n = len(c)
    return _core(_f64(o), _f64(h), _f64(l), _f64(c),
                 np.ascontiguousarray(longSig, dtype=np.bool_), np.ascontiguousarray(shortSig, dtype=np.bool_),
                 _f64(slDistL), _f64(slDistS), _f64(chandL), _f64(chandS),
                 _trig_codes(trigCodeL, n, None), _trig_codes(trigCodeS, n, None),
                 _score_arr(scoreL, n), _score_arr(scoreS, n),
                 float(mgmt["k1"]), float(mgmt["k2"]), float(mgmt["k3"]), float(mgmt["w1"]), float(mgmt["w2"]),
                 bool(mgmt["trailOn"]), int(mgmt["trailFrom"]), bool(mgmt["beOn"]),
                 float(costPct), float(mintick))


def stats_dict(stats) -> dict:
    vals = np.asarray(stats).tolist()
    return {key: (int(v) if key in _STAT_INT else v) for key, v in zip(STAT_KEYS, vals)}


def trades_list(rec, names=TRIG_NAMES) -> list:
    out = []
    for r in np.asarray(rec).tolist():
        tp3 = r[C_TP3]
        out.append({
            "dir": int(r[C_DIR]), "entry_bar": int(r[C_EBAR]), "exit_bar": int(r[C_XBAR]),
            "trig": names[int(r[C_TRIG])], "score": int(r[C_SCORE]),
            "entry": r[C_ENTRY], "sl0": r[C_SL0], "risk": r[C_RISK],
            "tp1": r[C_TP1], "tp2": r[C_TP2], "tp3": None if tp3 != tp3 else tp3,
            "hit1": r[C_HIT1] != 0.0, "hit2": r[C_HIT2] != 0.0, "hit3": r[C_HIT3] != 0.0,
            "exit_px": r[C_XPX], "reason": REASONS[int(r[C_REASON])],
            "gross_R": r[C_GROSS], "cost_R": r[C_COST], "R": r[C_R],
        })
    return out


def open_trade_dict(op, names=TRIG_NAMES):
    r = np.asarray(op).tolist()
    if r[O_HAS] == 0.0:
        return None
    tp3 = r[O_TP3]
    return {
        "dir": int(r[O_DIR]), "entry_bar": int(r[O_EBAR]), "trig": names[int(r[O_TRIG])], "score": int(r[O_SCORE]),
        "entry": r[O_ENTRY], "sl0": r[O_SL0], "risk": r[O_RISK],
        "tp1": r[O_TP1], "tp2": r[O_TP2], "tp3": None if tp3 != tp3 else tp3,
        "hit1": r[O_HIT1] != 0.0, "hit2": r[O_HIT2] != 0.0, "hit3": r[O_HIT3] != 0.0,
    }


def simulate(o, h, l, c,                 # float arrays, one row per bar
             longSig, shortSig,          # bool arrays: the script's longSig / shortSig on each bar
             slDistL, slDistS,           # float arrays: stop distance used if a trade opens on that bar
             chandL, chandS,             # float arrays: chandelier values (nan = na)
             mgmt: dict,                 # {"k1","k2","k3","w1","w2","trailOn": bool,"trailFrom": 1|2,"beOn": bool}
             costPct: float,             # round-trip cost in PERCENT of price (e.g. 0.03)
             mintick: float = 0.01,
             trigL=None, trigS=None,     # optional arrays of trigger names (or integer codes); default "BRK"
             scoreL=None, scoreS=None    # optional int arrays; default 7
             ) -> dict:                  # {"trades": [...], "open_trade": ..., "stats": {...}}
    """Low-level trade simulator (ENGINE_SPEC section 6)."""
    n = len(c)
    names = list(TRIG_NAMES)
    tl = _trig_codes(trigL, n, names)
    ts = _trig_codes(trigS, n, names)
    rec, op, stats = simulate_arrays(o, h, l, c, longSig, shortSig, slDistL, slDistS, chandL, chandS, mgmt,
                                     costPct, mintick, tl, ts, scoreL, scoreS)
    return {"trades": trades_list(rec, names), "open_trade": open_trade_dict(op, names),
            "stats": stats_dict(stats)}


def run(chart: dict, htf: dict, params: Params, market) -> dict:
    """Full port: per-bar series from the chart / HTF data, then simulate()."""
    validate(params)
    f = features(chart, htf, params, market)
    res = simulate(chart["o"], chart["h"], chart["l"], chart["c"], f["longSig"], f["shortSig"],
                   f["slDistL"], f["slDistS"], f["chandL"], f["chandS"], mgmt_of(params, market),
                   f["costPct"], f["mintick"], f["trigCodeL"], f["trigCodeS"], f["scoreL"], f["scoreS"])
    res["series"] = {"scoreL": f["scoreL"], "scoreS": f["scoreS"], "longSig": f["longSig"],
                     "shortSig": f["shortSig"], "atr": f["atr"], "htfTrend": f["htfTrend"]}
    return res


def run_fast(chart: dict, feats: dict, mgmt: dict, costPct: float | None = None):
    """Sweep helper: re-run only the trade kernel on precomputed features() with other management settings.
    -> (rec, open_state, stats) arrays; see REC_COLS / OPEN_COLS / STAT_KEYS."""
    return simulate_arrays(chart["o"], chart["h"], chart["l"], chart["c"], feats["longSig"], feats["shortSig"],
                           feats["slDistL"], feats["slDistS"], feats["chandL"], feats["chandS"], mgmt,
                           feats["costPct"] if costPct is None else costPct, feats["mintick"],
                           feats["trigCodeL"], feats["trigCodeS"], feats["scoreL"], feats["scoreS"])


def check_invariants(res: dict, chart: dict, tol: float = 1e-9) -> None:
    """Assert the bookkeeping invariants that follow from the Pine source (raises AssertionError).

    Stop invariant for reason "SL" (activeStopReason: stop still at sl0 AND full position, so nothing was
    realized before): R == (exit_px - entry) * dir / risk - cost_R, where exit_px == sl0 (R = -1 - cost_R up to
    rounding) when the exit bar opened inside the stop, and exit_px == open (R <= -1 - cost_R) when the bar
    opened at/beyond sl0 (long: open <= sl0, short: open >= sl0)."""
    o, c = chart["o"], chart["c"]
    tr, st = res["trades"], res["stats"]
    assert st["n"] == len(tr) and st["nL"] + st["nS"] == st["n"]
    net = peak = dd = 0.0
    for i, t in enumerate(tr):
        d = t["dir"]
        net += t["R"]
        peak = max(peak, net)
        dd = max(dd, peak - net)
        assert t["exit_bar"] > t["entry_bar"] and t["entry"] == c[t["entry_bar"]], (i, t)
        assert (not t["hit2"] or t["hit1"]) and (not t["hit3"] or t["hit2"]), (i, t)
        assert t["R"] == t["gross_R"] - t["cost_R"], (i, t)
        assert (t["reason"] == "TP3") == t["hit3"], (i, t)
        if t["reason"] == "SL":
            ob = o[t["exit_bar"]]
            gapped = (ob <= t["sl0"]) if d == 1 else (ob >= t["sl0"])
            assert t["exit_px"] == (ob if gapped else t["sl0"]), (i, t)
            assert abs(t["gross_R"] - (t["exit_px"] - t["entry"]) * d / t["risk"]) <= tol, (i, t)
            assert (t["gross_R"] <= -1 + tol) if gapped else (abs(t["gross_R"] + 1) <= tol), (i, t)
        elif t["reason"] == "Reverse":
            nxt = tr[i + 1] if i + 1 < len(tr) else res["open_trade"]
            assert t["exit_px"] == c[t["exit_bar"]] and nxt is not None, (i, t)
            assert nxt["entry_bar"] == t["exit_bar"] and nxt["dir"] == -d, (i, t)
    assert abs(net - st["net"]) <= tol and abs(peak - st["peak"]) <= tol and abs(dd - st["maxDd"]) <= tol
    assert abs(st["gross"] - st["loss"] - st["net"]) <= tol and abs(st["netL"] + st["netS"] - st["net"]) <= tol
    assert st["tp1"] == sum(t["hit1"] for t in tr) and st["tp2"] == sum(t["hit2"] for t in tr)
    assert st["tp3"] == sum(t["hit3"] for t in tr) and st["fullSl"] == sum(t["reason"] == "SL" for t in tr)
    assert st["win"] == sum(t["R"] > 0 for t in tr) and st["nL"] == sum(t["dir"] == 1 for t in tr)


if __name__ == "__main__":
    import sys
    import time

    import datasets as ds

    for name in (sys.argv[1:] or ["OANDA_XAUUSD_4h", "BINANCE_BTCUSDT_4h", "NASDAQ_AAPL_1D", "OANDA_EURUSD_1h"]):
        chart_ = ds.load(name)
        market_ = ds.market_of(name, chart_)
        htf_, src_ = ds.htf_bars(name, chart_)
        run(chart_, htf_, Params(), market_)                  # JIT warm-up
        t0 = time.perf_counter()
        res_ = run(chart_, htf_, Params(), market_)
        dt_ = time.perf_counter() - t0
        check_invariants(res_, chart_)
        print(f"{name}: bars={len(chart_['c'])} htf={src_} trades={len(res_['trades'])} "
              f"open={res_['open_trade'] is not None} time={dt_ * 1e3:.2f} ms")
        print("  ", res_["stats"])
