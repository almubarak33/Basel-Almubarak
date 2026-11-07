"""APEX Fusion research engine.

Bar-by-bar Python mirror of the Pine Script logic in indicators/APEX_Fusion_Pro.pine
(and of the two original indicators it merges: APEX Focus and Setup Scanner [GBB]).

Conventions (identical to the Pine code):
- Signals are evaluated on confirmed bars; entry is the close of the signal bar.
- Trade management starts on the bar AFTER the entry bar.
- An opening gap through the stop fills at the open; if the stop and a target are both
  inside one bar's range the stop is assumed to come first (conservative).
- Higher-timeframe values use the previous completed HTF bar (no repainting).
- Costs are a round-trip percentage of the entry price, converted to R and subtracted
  from every trade.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(__file__).resolve().parent / "data"
NAN = float("nan")

# ───────────────────────────── data ─────────────────────────────


def load(name: str, spot_hours: bool = True) -> pd.DataFrame:
    """Load a dataset. spot_hours drops bars when spot metals are closed
    (Fri 17:00 ET → Sun 18:00 ET and the daily 17:00–18:00 ET break), so a 24/7
    perpetual or tokenised-gold feed has the same bar sequence as a spot XAUUSD chart."""
    df = pd.read_csv(DATA / f"{name}.csv.gz")
    df["ts"] = pd.to_datetime(df["t"], unit="s", utc=True)
    ny = df["ts"].dt.tz_convert("America/New_York")
    df["ny"] = ny
    if spot_hours:
        wd = ny.dt.weekday  # Mon=0 … Sun=6
        hr = ny.dt.hour
        closed = (wd == 5) | ((wd == 4) & (hr >= 17)) | ((wd == 6) & (hr < 18)) | (hr == 17)
        df = df[~closed]
    df = df.reset_index(drop=True)
    return df


# ───────────────────────────── Pine ta.* replicas ─────────────────────────────


def _seeded(x: np.ndarray, n: int, alpha: float) -> np.ndarray:
    """Pine ta.rma / ta.ema: seeded with the SMA of the first n non-na values."""
    out = np.full(len(x), NAN)
    prev = NAN
    run = []
    for i, v in enumerate(x):
        if math.isnan(prev):
            if math.isnan(v):
                run = []
                continue
            run.append(v)
            if len(run) > n:
                run.pop(0)
            if len(run) == n:
                prev = sum(run) / n
                out[i] = prev
        else:
            if not math.isnan(v):
                prev = alpha * v + (1 - alpha) * prev
            out[i] = prev
    return out


def rma(x, n):
    return _seeded(np.asarray(x, float), n, 1.0 / n)


def ema(x, n):
    return _seeded(np.asarray(x, float), n, 2.0 / (n + 1))


def sma(x, n):
    return pd.Series(x).rolling(n, min_periods=n).mean().to_numpy()


def highest(x, n):
    return pd.Series(x).rolling(n, min_periods=n).max().to_numpy()


def lowest(x, n):
    return pd.Series(x).rolling(n, min_periods=n).min().to_numpy()


def shift(x, k=1):
    x = np.asarray(x, float)
    out = np.full(len(x), NAN)
    if k < len(x):
        out[k:] = x[:-k] if k > 0 else x
    return out


def true_range(h, l, c, handle_na=True):
    pc = shift(c)
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    if handle_na:
        tr[0] = h[0] - l[0]
    else:
        tr[0] = NAN
    return tr


def atr(h, l, c, n):
    return rma(true_range(h, l, c, True), n)


def rsi(x, n):
    ch = x - shift(x)
    up = np.where(np.isnan(ch), NAN, np.maximum(ch, 0))
    dn = np.where(np.isnan(ch), NAN, np.maximum(-ch, 0))
    ru, rd = rma(up, n), rma(dn, n)
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.where(rd == 0, 100.0, np.where(ru == 0, 0.0, 100 - 100 / (1 + ru / rd)))
    r[np.isnan(ru) | np.isnan(rd)] = NAN
    return r


def dmi(h, l, c, di_len, adx_len):
    up = h - shift(h)
    down = -(l - shift(l))
    plus_dm = np.where(np.isnan(up), NAN, np.where((up > down) & (up > 0), up, 0.0))
    minus_dm = np.where(np.isnan(down), NAN, np.where((down > up) & (down > 0), down, 0.0))
    trur = rma(true_range(h, l, c, False), di_len)
    with np.errstate(divide="ignore", invalid="ignore"):
        plus = pd.Series(100 * rma(plus_dm, di_len) / trur).ffill().to_numpy()
        minus = pd.Series(100 * rma(minus_dm, di_len) / trur).ffill().to_numpy()
        s = plus + minus
        adx = 100 * rma(np.abs(plus - minus) / np.where(s == 0, 1, s), adx_len)
    return plus, minus, adx


def supertrend(h, l, c, factor, n):
    a = atr(h, l, c, n)
    src = (h + l) / 2
    N = len(c)
    st = np.full(N, NAN)
    d = np.full(N, NAN)
    pub = plb = NAN
    prev_st = NAN
    for i in range(N):
        ub = src[i] + factor * a[i]
        lb = src[i] - factor * a[i]
        ppl = 0.0 if math.isnan(plb) else plb
        ppu = 0.0 if math.isnan(pub) else pub
        pc = c[i - 1] if i > 0 else NAN
        if not math.isnan(lb):
            lb = lb if (lb > ppl or (not math.isnan(pc) and pc < ppl)) else ppl
        if not math.isnan(ub):
            ub = ub if (ub < ppu or (not math.isnan(pc) and pc > ppu)) else ppu
        if i == 0 or math.isnan(a[i - 1]):
            di = 1
        elif prev_st == ppu:
            di = -1 if c[i] > ub else 1
        else:
            di = 1 if c[i] < lb else -1
        s = lb if di == -1 else ub
        st[i], d[i] = s, di
        prev_st, pub, plb = s, ub, lb
    return st, d


def pivots(x, left, right, high=True):
    """ta.pivothigh / ta.pivotlow: value reported at the confirmation bar (pivot + right)."""
    x = np.asarray(x, float)
    N = len(x)
    out = np.full(N, NAN)
    for i in range(left + right, N):
        p = i - right
        v = x[p]
        win_l = x[p - left:p]
        win_r = x[p + 1:i + 1]
        if high:
            if v > win_l.max() and v >= win_r.max():
                out[i] = v
        else:
            if v < win_l.min() and v <= win_r.min():
                out[i] = v
    return out


def barssince(cond):
    out = np.full(len(cond), NAN)
    last = -1
    for i, c in enumerate(cond):
        if c:
            last = i
        if last >= 0:
            out[i] = i - last
    return out


# ───────────────────────────── sessions / HTF ─────────────────────────────


def session_day(ny: pd.Series, start_hour: int = 18) -> np.ndarray:
    """Trading-day id: a new day starts at start_hour New York time (CME/OANDA metals)."""
    shifted = ny - pd.Timedelta(hours=start_hour)
    return (shifted.dt.year * 10000 + shifted.dt.month * 100 + shifted.dt.day).to_numpy()


def vwap_session(df, src, day_id):
    v = df["v"].to_numpy(float)
    out = np.full(len(df), NAN)
    cpv = cv = 0.0
    prev = None
    for i in range(len(df)):
        if day_id[i] != prev:
            cpv = cv = 0.0
            prev = day_id[i]
        cpv += src[i] * v[i]
        cv += v[i]
        out[i] = cpv / cv if cv > 0 else NAN
    return out


HTF_START_HOUR = 18  # New York hour where HTF (4H/D) bars are anchored; OANDA-style feeds use 17


def htf_bucket(df, htf_minutes: int, start_hour: int = None) -> np.ndarray:
    """HTF bar id aligned to the session start (as TradingView aligns 4H/1D bars)."""
    start_hour = HTF_START_HOUR if start_hour is None else start_hour
    shifted = df["ny"] - pd.Timedelta(hours=start_hour)
    day = (shifted.dt.year * 10000 + shifted.dt.month * 100 + shifted.dt.day).to_numpy().astype(np.int64)
    if htf_minutes >= 43200:   # monthly
        return (shifted.dt.year * 100 + shifted.dt.month).to_numpy().astype(np.int64)
    if htf_minutes >= 10080:   # weekly (session week starts Sunday 18:00 NY)
        iso = (shifted + pd.Timedelta(days=1)).dt.isocalendar()
        return (iso.year.astype(np.int64) * 100 + iso.week.astype(np.int64)).to_numpy()
    if htf_minutes >= 1440:
        return day
    mins = (shifted.dt.hour * 60 + shifted.dt.minute).to_numpy()
    return day * 100 + mins // htf_minutes


def htf_trend(df, htf_minutes, ema_len):
    """APEX htfTrendCalc on the HTF series, previous completed HTF bar mapped to chart bars."""
    b = htf_bucket(df, htf_minutes)
    g = pd.DataFrame({"b": b, "o": df.o, "h": df.h, "l": df.l, "c": df.c}).groupby("b", sort=False)
    H = g.agg(o=("o", "first"), h=("h", "max"), l=("l", "min"), c=("c", "last"))
    hc, hh, hl = H.c.to_numpy(), H.h.to_numpy(), H.l.to_numpy()
    _, d = supertrend(hh, hl, hc, 3.0, 10)
    e = ema(hc, ema_len)
    tr_ = np.where(np.isnan(e) | np.isnan(d), 0, np.where((hc > e) & (d < 0), 1, np.where((hc < e) & (d > 0), -1, 0)))
    prev = np.concatenate([[0], tr_[:-1]])  # expression[1]
    m = pd.Series(prev, index=H.index)
    return m.reindex(b).to_numpy().astype(int)


def auto_htf_minutes(tf_minutes):
    s = tf_minutes * 60
    return 60 if s <= 300 else 240 if s <= 3600 else 1440 if s <= 14400 else 10080 if s <= 86400 else 43200


def resample(df, minutes):
    """Session-aligned resample (e.g. 1h -> 4h), keeping the first bar's timestamp."""
    b = htf_bucket(df, minutes)
    g = df.assign(b=b).groupby("b", sort=False)
    out = g.agg(t=("t", "first"), o=("o", "first"), h=("h", "max"), l=("l", "min"), c=("c", "last"), v=("v", "sum")).reset_index(drop=True)
    out["ts"] = pd.to_datetime(out["t"], unit="s", utc=True)
    out["ny"] = out["ts"].dt.tz_convert("America/New_York")
    return out


# ───────────────────────────── parameters ─────────────────────────────

SETUPS = ["BRK", "FLIP", "PB", "EMA", "BRT", "VWAP", "ORB", "SWEEP", "DIV", "REB", "ASWP", "ABRK"]
TREND_SETUPS = {"BRK", "FLIP", "PB", "EMA", "BRT", "VWAP", "ORB", "ABRK"}
REVERSAL_SETUPS = {"SWEEP", "DIV", "REB", "ASWP"}


@dataclass
class Params:
    tf_minutes: int = 15
    htf_minutes: int = 0            # 0 = APEX auto (5m->1H, 15m/1H->4H ...); v2 uses 240 for every chart <= 1H
    # APEX context
    adx_min: float = 25.0
    don_len: int = 20
    st_factor: float = 3.0
    st_len: int = 10
    piv_len: int = 10
    zone_count: int = 3
    # GBB setups
    vol_mult: float = 1.0
    pv_len: int = 5
    vwap_away: int = 6
    ema_window: int = 3
    brt_tol: float = 0.3
    brt_window: int = 20
    sweep_len: int = 20
    div_gap: int = 60
    orb_start_ny: tuple = (9, 30)   # opening-range session start (New York time)
    orb_end_ny: tuple = (16, 0)
    orb_minutes: int = 15
    # rebound
    bounce_window: int = 3
    # stops / targets / management
    stop_mode: str = "swing"        # swing (APEX) | atr (GBB)
    stop_atr: float = 1.2           # GBB fixed stop
    swing_look: int = 10
    sl_buf: float = 0.25
    sl_min_atr: float = 0.8
    sl_max_atr: float = 3.5
    k1: float = 0.3
    k2: float = 1.5
    k3: float = 4.0
    w1: float = 0.5
    w2: float = 0.25
    be_on: bool = True
    lock_tp2: bool = True           # move stop to TP1 after TP2 (APEX)
    trail_on: bool = True
    trail_from: int = 1
    ch_len: int = 22
    ch_mult: float = 3.0
    max_bars: int = 0               # 0 = no time exit
    reverse: bool = True            # opposite signal reverses (APEX) vs ignored (GBB)
    cost_pct: float = 0.03
    small_guard: bool = True
    cg_max_pct: float = 7.0
    mr_exit: float = 0.0            # >0: MR trades exit the remaining position at the close when RSI(2) > mr_exit (long) / < 100-mr_exit (short)
    min_stop_pct: float = 0.0       # v2 volatility floor: skip signals whose stop is < this % of price (charts < 1H)
    warm: int = 250
    # v2: professional-technique options
    entry_mode: str = "close"       # close = market at signal close | pullback = limit order on a retracement
    pb_frac: float = 0.33           # limit price = close - dir * pb_frac * stop distance
    pb_bars: int = 3                # limit order validity (bars after the signal)
    asia_start: int = 20            # Asian range: 20:00 -> 02:00 New York
    asia_end: int = 2
    sweep_end: int = 11             # sweeps / breakouts of the Asian range count until 11:00 New York
    asia_min_pct: float = 0.15      # skip days whose Asian range is narrower / wider than this % of price
    asia_max_pct: float = 1.60


# ───────────────────────────── features ─────────────────────────────


def features(df: pd.DataFrame, P: Params) -> dict:
    o, h, l, c, v = (df[k].to_numpy(float) for k in ["o", "h", "l", "c", "v"])
    N = len(c)
    F = {"o": o, "h": h, "l": l, "c": c, "v": v, "N": N}
    F["atr"] = atr(h, l, c, 14)
    F["ema9"], F["ema21"], F["ema50"] = ema(c, 9), ema(c, 21), ema(c, 50)
    F["ema55"], F["ema200"] = ema(c, 55), ema(c, 200)
    F["st"], F["stDir"] = supertrend(h, l, c, P.st_factor, P.st_len)
    F["diP"], F["diM"], F["adx"] = dmi(h, l, c, 14, 14)
    F["rsi"] = rsi(c, 14)
    F["rsi2"] = rsi(c, 2)
    tsm = np.zeros(N)
    for k in (20, 50, 100, 200):
        tsm += np.sign(c - shift(c, k))
    F["tsm"] = tsm / 4  # nan for the first 200 bars
    rng14 = highest(h, 14) - lowest(l, 14)
    trs = pd.Series(true_range(h, l, c, True)).rolling(14).sum().to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        F["chop"] = np.where(rng14 > 0, 100 * np.log10(trs / rng14) / np.log10(14), 50.0)
    F["volMa"] = sma(v, 20)
    day = session_day(df["ny"])
    F["day"] = day
    F["vwap"] = vwap_session(df, (h + l + c) / 3, day)
    htf_min = P.htf_minutes or auto_htf_minutes(P.tf_minutes)
    use21 = htf_min >= 1440
    F["htf"] = htf_trend(df, htf_min, 21 if use21 else 50)
    F["hour_ny"] = df["ny"].dt.hour.to_numpy()
    F["min_ny"] = df["ny"].dt.minute.to_numpy()
    F["ts"] = df["t"].to_numpy()
    # APEX confluence score
    sc = {}
    adx, a3 = F["adx"], shift(F["adx"], 3)
    for d in (1, -1):
        s = np.zeros(N)
        s += F["htf"] == d
        s += (c - F["ema200"]) * d > 0
        s += (F["ema21"] - F["ema55"]) * d > 0
        s += adx > P.adx_min
        s += (adx > a3) & (adx > 18)
        s += (F["diP"] - F["diM"]) * d > 0
        s += (F["rsi"] - 50) * d > 0
        sc[d] = s
    F["scoreL"], F["scoreS"] = sc[1], sc[-1]
    # stops
    a = F["atr"]
    lo_sw = lowest(l, P.swing_look) - P.sl_buf * a
    hi_sw = highest(h, P.swing_look) + P.sl_buf * a
    if P.stop_mode == "swing":
        F["slL"] = np.minimum(np.maximum(c - lo_sw, P.sl_min_atr * a), P.sl_max_atr * a)
        F["slS"] = np.minimum(np.maximum(hi_sw - c, P.sl_min_atr * a), P.sl_max_atr * a)
    else:
        F["slL"] = F["slS"] = P.stop_atr * a
    F["chandL"] = highest(h, P.ch_len) - P.ch_mult * a
    F["chandS"] = lowest(l, P.ch_len) + P.ch_mult * a
    F["ph10"], F["pl10"] = pivots(h, P.piv_len, P.piv_len, True), pivots(l, P.piv_len, P.piv_len, False)
    F["ph5"], F["pl5"] = pivots(h, P.pv_len, P.pv_len, True), pivots(l, P.pv_len, P.pv_len, False)
    return F


# ───────────────────────────── raw setups ─────────────────────────────


def setups(F: dict, P: Params) -> dict:
    """Raw long/short trigger arrays for every setup (before any quality gate)."""
    o, h, l, c, v, N = F["o"], F["h"], F["l"], F["c"], F["v"], F["N"]
    a = F["atr"]
    ready = ~np.isnan(a) & (a > 0)
    bull, bear = c > o, c < o
    vm = F["volMa"]
    volOk = (P.vol_mult <= 0) | np.isnan(vm) | (v >= vm * P.vol_mult)
    S = {}
    # APEX: Donchian breakout
    donHi, donLo = shift(highest(h, P.don_len)), shift(lowest(l, P.don_len))
    S["BRK"] = ((c > donHi) & (shift(c) <= shift(donHi)), (c < donLo) & (shift(c) >= shift(donLo)))
    # APEX: SuperTrend flip
    d, d1 = F["stDir"], shift(F["stDir"])
    S["FLIP"] = ((d < 0) & (d1 > 0), (d > 0) & (d1 < 0))
    # APEX: trend pullback resume
    e21 = F["ema21"]
    touchUp = lowest(l - e21, 5) <= 0
    touchDn = highest(h - e21, 5) >= 0
    h1, l1 = shift(h), shift(l)
    S["PB"] = ((d < 0) & touchUp & (c > h1) & (c > e21) & bull, (d > 0) & touchDn & (c < l1) & (c < e21) & bear)
    # GBB: EMA pullback
    e9, e50 = F["ema9"], F["ema50"]
    trendUp = (e21 > e50) & (e50 > shift(e50, 3))
    trendDn = (e21 < e50) & (e50 < shift(e50, 3))
    tU = barssince(l <= e21) <= P.ema_window
    tD = barssince(h >= e21) <= P.ema_window
    S["EMA"] = (trendUp & tU & (c > e9) & bull & (c > h1) & volOk, trendDn & tD & (c < e9) & bear & (c < l1) & volOk)
    # GBB: VWAP reclaim
    vw = F["vwap"]
    below = np.zeros(N)
    above = np.zeros(N)
    br = ar = 0
    for i in range(N):
        if not math.isnan(vw[i]):
            br = br + 1 if c[i] < vw[i] else 0
            ar = ar + 1 if c[i] > vw[i] else 0
        below[i], above[i] = br, ar
    xUp = (c > vw) & (shift(c) <= shift(vw))
    xDn = (c < vw) & (shift(c) >= shift(vw))
    S["VWAP"] = (xUp & (shift(below) >= P.vwap_away) & volOk, xDn & (shift(above) >= P.vwap_away) & volOk)
    # GBB: break and retest
    S["BRT"] = _break_retest(F, P)
    # GBB: liquidity sweep
    swLo, swHi = shift(lowest(l, P.sweep_len)), shift(highest(h, P.sweep_len))
    S["SWEEP"] = ((l < swLo) & (c > swLo) & bull & ((c - l) > (h - c)) & volOk,
                  (h > swHi) & (c < swHi) & bear & ((h - c) > (c - l)) & volOk)
    # GBB: RSI divergence
    S["DIV"] = _divergence(F, P)
    # GBB: opening range break
    S["ORB"] = _orb(F, P)
    # APEX: support rebound (+ symmetric resistance rejection for shorts)
    S["REB"] = _rebound(F, P)
    # v2: Asian-range liquidity sweep (Judas swing) and London/NY breakout of the Asian range
    S["ASWP"], S["ABRK"] = _asian_range(F, P)
    return {k: (np.nan_to_num(L, nan=0).astype(bool) & ready, np.nan_to_num(Sx, nan=0).astype(bool) & ready) for k, (L, Sx) in S.items()}


def _break_retest(F, P):
    h, l, c, o, a, N = F["h"], F["l"], F["c"], F["o"], F["atr"], F["N"]
    ph, pl = F["ph5"], F["pl5"]
    L = np.zeros(N, bool)
    S = np.zeros(N, bool)
    hiLvl = loLvl = NAN
    hiBrk = loBrk = False
    hiBar = loBar = None
    hiPend = loPend = NAN

    def busy(brk, bar, i):
        return brk and bar is not None and i - bar <= P.brt_window

    for i in range(N):
        if not math.isnan(ph[i]):
            if busy(hiBrk, hiBar, i):
                hiPend = ph[i]
            else:
                hiLvl, hiBrk, hiPend = ph[i], False, NAN
        if not math.isnan(pl[i]):
            if busy(loBrk, loBar, i):
                loPend = pl[i]
            else:
                loLvl, loBrk, loPend = pl[i], False, NAN
        if not math.isnan(hiLvl) and not hiBrk and c[i] > hiLvl:
            hiBrk, hiBar = True, i
        if not math.isnan(loLvl) and not loBrk and c[i] < loLvl:
            loBrk, loBar = True, i
        liveL = busy(hiBrk, hiBar, i) and i > hiBar
        liveS = busy(loBrk, loBar, i) and i > loBar
        ok = not math.isnan(a[i]) and a[i] > 0
        sL = liveL and ok and l[i] <= hiLvl + a[i] * P.brt_tol and c[i] > hiLvl and c[i] > o[i]
        sS = liveS and ok and h[i] >= loLvl - a[i] * P.brt_tol and c[i] < loLvl and c[i] < o[i]
        if sL:
            hiBrk = False
        if sS:
            loBrk = False
        if not busy(hiBrk, hiBar, i) and not math.isnan(hiPend):
            hiLvl, hiBrk, hiPend = hiPend, False, NAN
        if not busy(loBrk, loBar, i) and not math.isnan(loPend):
            loLvl, loBrk, loPend = loPend, False, NAN
        L[i], S[i] = sL, sS
    return L, S


def _divergence(F, P):
    r, N = F["rsi"], F["N"]
    ph, pl = F["ph5"], F["pl5"]
    L = np.zeros(N, bool)
    S = np.zeros(N, bool)
    lpP = lpR = hpP = hpR = NAN
    lpB = hpB = None
    for i in range(N):
        if not math.isnan(pl[i]):
            curR = r[i - P.pv_len]
            if not math.isnan(lpP) and i - lpB <= P.div_gap:
                L[i] = pl[i] < lpP and curR > lpR
            lpP, lpR, lpB = pl[i], curR, i
        if not math.isnan(ph[i]):
            curR = r[i - P.pv_len]
            if not math.isnan(hpP) and i - hpB <= P.div_gap:
                S[i] = ph[i] > hpP and curR < hpR
            hpP, hpR, hpB = ph[i], curR, i
    return L, S


def _orb(F, P):
    h, l, c, N = F["h"], F["l"], F["c"], F["N"]
    hm = F["hour_ny"] * 60 + F["min_ny"]
    s0 = P.orb_start_ny[0] * 60 + P.orb_start_ny[1]
    s1 = P.orb_end_ny[0] * 60 + P.orb_end_ny[1]
    inS = (hm >= s0) & (hm < s1)
    ts = F["ts"]
    L = np.zeros(N, bool)
    S = np.zeros(N, bool)
    orH = orL = NAN
    done = fired = False
    start = None
    for i in range(N):
        new = inS[i] and (i == 0 or not inS[i - 1])
        if new:
            orH, orL, done, fired, start = h[i], l[i], False, False, ts[i]
        elif inS[i] and not done:
            if start is not None and ts[i] - start >= P.orb_minutes * 60:
                done = True
            else:
                orH = h[i] if math.isnan(orH) else max(orH, h[i])
                orL = l[i] if math.isnan(orL) else min(orL, l[i])
        sL = inS[i] and done and not fired and not math.isnan(orH) and c[i] > orH
        sS = inS[i] and done and not fired and not math.isnan(orL) and c[i] < orL
        if sL or sS:
            fired = True
        L[i], S[i] = sL, sS
    return L, S


def _rebound(F, P):
    """APEX support-rebound state machine; the short side mirrors it on resistance."""
    h, l, c, o, a, N = F["h"], F["l"], F["c"], F["o"], F["atr"], F["N"]
    out = []
    for side in (1, -1):
        piv = F["pl10"] if side == 1 else F["ph10"]
        zones = []  # dict(top,bottom,born,state,tb,th,tl)
        sig = np.zeros(N, bool)
        last_evt = None
        for i in range(N):
            ev = False
            for z in reversed(zones):
                broken = c[i] < z["bottom"] if side == 1 else c[i] > z["top"]
                if broken:
                    z["state"] = 4
                elif z["state"] == 0:
                    touch = l[i] <= z["top"] and h[i] >= z["bottom"]
                    if z["born"] < i and touch:
                        z.update(state=1, tb=i, th=h[i], tl=l[i])
                elif z["state"] == 1:
                    age = i - z["tb"]
                    if age > P.bounce_window:
                        z["state"] = 2
                    elif age >= 1 and (
                        (side == 1 and c[i] > o[i] and c[i] > z["th"] and c[i] > z["top"])
                        or (side == -1 and c[i] < o[i] and c[i] < z["tl"] and c[i] < z["bottom"])
                    ):
                        if not ev:  # cooldown 5 bars
                            if last_evt is None or i - last_evt >= 5:
                                z["state"] = 3
                                ev = True
                                last_evt = i
                elif z["state"] == 2:
                    rec = c[i] > z["top"] + 0.5 * a[i] if side == 1 else c[i] < z["bottom"] - 0.5 * a[i]
                    if rec:
                        z["state"] = 0
            if ev:
                for z in zones:
                    if z["state"] == 1:
                        z["state"] = 2
            if not math.isnan(piv[i]) and not math.isnan(a[i]) and a[i] > 0:
                zones.append(dict(top=piv[i] + 0.15 * a[i], bottom=piv[i] - 0.15 * a[i], born=i, state=0, tb=None, th=NAN, tl=NAN))
                while len(zones) > P.zone_count:
                    zones.pop(0)
            sig[i] = ev
        out.append(sig)
    return out[0], out[1]


def _asian_range(F, P):
    """Asian range = high/low of bars from asia_start to asia_end New York (one range per trading day).
    ASWP: after the range is complete and before sweep_end, a bar trades beyond one side and closes back
          inside with a body in the reversal direction -> trade back into the range (one per side per day).
    ABRK: first close beyond the range in that window -> trade the breakout (one per day).
    Also fills F["aswpStopL"/"aswpStopS"]: stop distance beyond the sweep extreme (last 3 bars) + 0.25 ATR."""
    h, l, c, o, a, N = F["h"], F["l"], F["c"], F["o"], F["atr"], F["N"]
    hr, day = F["hour_ny"], F["day"]
    inAsia = (hr >= P.asia_start) | (hr < P.asia_end)
    inWin = (hr >= P.asia_end) & (hr < P.sweep_end)
    swL = np.zeros(N, bool); swS = np.zeros(N, bool); bkL = np.zeros(N, bool); bkS = np.zeros(N, bool)
    stopL = np.full(N, NAN); stopS = np.full(N, NAN)
    aH = aL = NAN
    cur_day = None
    usedL = usedS = usedB = False
    for i in range(N):
        if day[i] != cur_day:
            cur_day = day[i]
            aH = aL = NAN
            usedL = usedS = usedB = False
        if inAsia[i]:
            aH = h[i] if math.isnan(aH) else max(aH, h[i])
            aL = l[i] if math.isnan(aL) else min(aL, l[i])
            continue
        if not inWin[i] or math.isnan(aH) or math.isnan(a[i]):
            continue
        width = (aH - aL) / c[i] * 100
        if width < P.asia_min_pct or width > P.asia_max_pct:
            continue
        lo3 = min(l[max(0, i - 2):i + 1])
        hi3 = max(h[max(0, i - 2):i + 1])
        if not usedL and lo3 < aL and c[i] > aL and c[i] > o[i]:
            swL[i] = True; usedL = True
            stopL[i] = c[i] - (lo3 - 0.25 * a[i])
        if not usedS and hi3 > aH and c[i] < aH and c[i] < o[i]:
            swS[i] = True; usedS = True
            stopS[i] = (hi3 + 0.25 * a[i]) - c[i]
        if not usedB and i > 0 and c[i] > aH and c[i - 1] <= aH:
            bkL[i] = True; usedB = True
        elif not usedB and i > 0 and c[i] < aL and c[i - 1] >= aL:
            bkS[i] = True; usedB = True
    F["aswpStopL"], F["aswpStopS"] = stopL, stopS
    return (swL, swS), (bkL, bkS)


# ───────────────────────────── trade simulator ─────────────────────────────


@dataclass
class Trade:
    dir: int
    bar: int
    setup: str
    entry: float
    sl: float
    sl0: float
    risk: float
    tp1: float
    tp2: float
    tp3: float
    hit1: bool = False
    hit2: bool = False
    hit3: bool = False
    realized: float = 0.0
    openW: float = 1.0
    exit_bar: int = -1
    exit_px: float = NAN
    reason: str = ""
    R: float = NAN
    costR: float = NAN


def simulate(F: dict, P: Params, longSig: np.ndarray, shortSig: np.ndarray, label=None, start=0, end=None,
             distL=None, distS=None) -> list:
    """APEX trade engine. longSig/shortSig are final (gated) entry arrays; label[i] names the setup.
    distL/distS optionally override the stop distance per bar (setup-specific structural stops)."""
    o, h, l, c, a, N = F["o"], F["h"], F["l"], F["c"], F["atr"], F["N"]
    end = N if end is None else end
    slL = F["slL"] if distL is None else distL
    slS = F["slS"] if distS is None else distS
    chL, chS = F["chandL"], F["chandS"]
    pend = None  # pending limit order: dict(dir, bar, limit, stop, setup)
    fills = {"signals": 0, "filled": 0}
    k1, k2, k3, w1, w2 = P.k1, P.k2, P.k3, P.w1, P.w2
    trades = []
    cur = None
    smallTf = P.tf_minutes < 60

    def close(t, i, px, reason):
        t.realized += t.openW * (px - t.entry) * t.dir / t.risk
        t.openW = 0.0
        t.costR = P.cost_pct / 100 * t.entry / t.risk
        t.R = t.realized - t.costR
        t.exit_bar, t.exit_px, t.reason = i, px, reason
        trades.append(t)

    def stop_reason(t):
        initial = t.sl == t.sl0
        full = t.openW >= 1 - 1e-9
        return ("SL" if full else "Remaining SL") if initial else "BE/Trail"

    def hit_tp1(t):
        t.hit1 = True
        w = min(w1, t.openW)
        t.realized += w * k1
        t.openW -= w
        if P.be_on:
            t.sl = max(t.sl, t.entry) if t.dir == 1 else min(t.sl, t.entry)

    def hit_tp2(t):
        t.hit2 = True
        w = min(w2, t.openW)
        t.realized += w * k2
        t.openW -= w
        if P.lock_tp2:
            t.sl = max(t.sl, t.tp1) if t.dir == 1 else min(t.sl, t.tp1)

    def trail(t, i):
        if P.trail_on and (t.hit1 if P.trail_from == 1 else t.hit2):
            tv = chL[i - 1] if t.dir == 1 else chS[i - 1]
            if not math.isnan(tv):
                t.sl = max(t.sl, tv) if t.dir == 1 else min(t.sl, tv)

    for i in range(start, end):
        # 1) manage the open trade on bars after the entry bar
        if cur is not None and i > cur.bar:
            t, d = cur, cur.dir
            trail(t, i)
            if (o[i] <= t.sl) if d == 1 else (o[i] >= t.sl):
                close(t, i, o[i], stop_reason(t))
                cur = None
            else:
                if not t.hit1 and ((o[i] >= t.tp1) if d == 1 else (o[i] <= t.tp1)):
                    hit_tp1(t)
                if t.openW > 1e-9 and t.hit1 and not t.hit2 and ((o[i] >= t.tp2) if d == 1 else (o[i] <= t.tp2)):
                    hit_tp2(t)
                if t.openW <= 1e-9:
                    close(t, i, t.tp2 if t.hit2 else t.tp1, "TP")
                    cur = None
                if cur is not None and t.hit2 and not t.hit3 and not math.isnan(t.tp3) and ((o[i] >= t.tp3) if d == 1 else (o[i] <= t.tp3)):
                    t.hit3 = True
                    t.realized += t.openW * k3
                    t.openW = 0.0
                    close(t, i, t.tp3, "TP3")
                    cur = None
                if cur is not None:
                    trail(t, i)
                    if (l[i] <= t.sl) if d == 1 else (h[i] >= t.sl):
                        px = o[i] if ((d == 1 and o[i] < t.sl) or (d == -1 and o[i] > t.sl)) else t.sl
                        close(t, i, px, stop_reason(t))
                        cur = None
                    else:
                        if not t.hit1 and ((h[i] >= t.tp1) if d == 1 else (l[i] <= t.tp1)):
                            hit_tp1(t)
                        if t.openW > 1e-9 and t.hit1 and not t.hit2 and ((h[i] >= t.tp2) if d == 1 else (l[i] <= t.tp2)):
                            hit_tp2(t)
                        if t.openW <= 1e-9:
                            close(t, i, t.tp2 if t.hit2 else t.tp1, "TP")
                            cur = None
                        if cur is not None and t.hit2 and not t.hit3 and not math.isnan(t.tp3) and ((h[i] >= t.tp3) if d == 1 else (l[i] <= t.tp3)):
                            t.hit3 = True
                            t.realized += t.openW * k3
                            t.openW = 0.0
                            close(t, i, t.tp3, "TP3")
                            cur = None
                        if cur is not None and P.mr_exit > 0 and t.setup == "MR" and (
                                (d == 1 and F["rsi2"][i] > P.mr_exit) or (d == -1 and F["rsi2"][i] < 100 - P.mr_exit)):
                            close(t, i, c[i], "MR exit")
                            cur = None
                        if cur is not None and P.max_bars > 0 and i - t.bar >= P.max_bars:
                            close(t, i, c[i], "Time")
                            cur = None
        # 1b) pending pullback limit order (only exists while flat)
        if pend is not None and cur is None and i > pend["bar"]:
            pd_ = pend["dir"]
            if i - pend["bar"] > P.pb_bars or ((o[i] <= pend["stop"]) if pd_ == 1 else (o[i] >= pend["stop"])):
                pend = None
            elif (l[i] <= pend["limit"]) if pd_ == 1 else (h[i] >= pend["limit"]):
                fill = min(o[i], pend["limit"]) if pd_ == 1 else max(o[i], pend["limit"])
                risk = (fill - pend["stop"]) * pd_
                if risk > 0:
                    tp3 = fill + pd_ * k3 * risk
                    cur = Trade(pd_, i, pend["setup"], fill, pend["stop"], pend["stop"], risk,
                                fill + pd_ * k1 * risk, fill + pd_ * k2 * risk, tp3 if tp3 > 0 else NAN)
                    fills["filled"] += 1
                    # unknown order inside the fill bar: if the bar also reached the stop, assume it was hit
                    if (l[i] <= cur.sl) if pd_ == 1 else (h[i] >= cur.sl):
                        close(cur, i, cur.sl, "SL")
                        cur = None
                pend = None
        elif pend is not None and cur is not None:
            pend = None
        # 2) new signals at the close
        if i < P.warm or math.isnan(a[i]) or a[i] <= 0:
            continue
        for d, sig, sl in ((1, longSig, slL), (-1, shortSig, slS)):
            if not sig[i]:
                continue
            if cur is not None and (cur.dir == d or not P.reverse):
                continue
            dist = sl[i]
            if smallTf and P.small_guard and dist < P.cost_pct / 100 * c[i] / (P.cg_max_pct / 100):
                continue
            if smallTf and P.min_stop_pct > 0 and dist < P.min_stop_pct / 100 * c[i]:
                continue
            if np.isnan(dist) or dist <= 0:
                continue
            if cur is not None:
                close(cur, i, c[i], "Reverse")
                cur = None
            if P.entry_mode == "pullback":
                fills["signals"] += 1
                pend = dict(dir=d, bar=i, limit=c[i] - d * P.pb_frac * dist, stop=c[i] - d * dist,
                            setup=label[i] if label is not None else "")
                break
            e = c[i]
            tp3 = e + d * k3 * dist
            cur = Trade(d, i, label[i] if label is not None else "", e, e - d * dist, e - d * dist, dist,
                        e + d * k1 * dist, e + d * k2 * dist, tp3 if tp3 > 0 else NAN)
            break
    if cur is not None:
        cur.reason = "Open"
        cur.R = NAN
    simulate.last_fills = fills
    return trades


# ───────────────────────────── statistics ─────────────────────────────


def stats(trades: list) -> dict:
    R = np.array([t.R for t in trades], float)
    n = len(R)
    if n == 0:
        return dict(n=0)
    wins = R[R > 0].sum()
    loss = -R[R < 0].sum()
    eq = np.cumsum(R)
    dd = (np.maximum.accumulate(np.concatenate([[0], eq]))[1:] - eq).max()
    return dict(
        n=n,
        win=float((R > 0).mean()),
        tp1=float(np.mean([t.hit1 for t in trades])),
        tp2=float(np.mean([t.hit2 for t in trades])),
        tp3=float(np.mean([t.hit3 for t in trades])),
        fullSL=float(np.mean([t.reason == "SL" for t in trades])),
        avgR=float(R.mean()),
        netR=float(R.sum()),
        pf=float(wins / loss) if loss > 0 else float("inf"),
        maxDD=float(dd),
        costR=float(np.mean([t.costR for t in trades])),
        long_n=int(sum(t.dir == 1 for t in trades)),
        long_avgR=float(np.mean([t.R for t in trades if t.dir == 1])) if any(t.dir == 1 for t in trades) else NAN,
        short_n=int(sum(t.dir == -1 for t in trades)),
        short_avgR=float(np.mean([t.R for t in trades if t.dir == -1])) if any(t.dir == -1 for t in trades) else NAN,
    )


def fmt_stats(s: dict) -> str:
    if s.get("n", 0) == 0:
        return "n=0"
    return (f"n={s['n']:4d} win={s['win']*100:5.1f}% TP1={s['tp1']*100:5.1f}% TP2={s['tp2']*100:5.1f}% "
            f"TP3={s['tp3']*100:4.1f}% SL={s['fullSL']*100:5.1f}% avgR={s['avgR']:+.3f} net={s['netR']:+7.1f}R "
            f"PF={s['pf']:.2f} DD={s['maxDD']:.1f}R")
