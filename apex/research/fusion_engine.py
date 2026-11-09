#!/usr/bin/env python3
"""Python port of the APEX Fusion Pro indicator (apex/APEX_Fusion_Pro*.pine): signals, pending limit entries,
trade management and the Stats object.

Built on the verified APEX Focus port: every indicator kernel (EMA/RMA/ATR/SuperTrend/DMI/RSI, rolling
extremes, the higher-timeframe trend) is imported from engine_b, and the trade kernel below is engine_b's
kernel plus the three things Fusion adds (pending pullback limit orders, the time exit, the reverse switch)
and the optional v2 rule `closeStop` (see engine_v2).  test_fusion.py proves that, configured like APEX Focus,
this module reproduces engine_b trade for trade.

Not ported: the zone rebound setup (`useReb`, off by default in the script) and every drawing.
Single implementation: unlike the Focus engine there is no second independent port of the Fusion-only parts
(GBB setups, sessions, pending orders); they are covered by the scenario tests in test_fusion.py only.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd
from numba import njit

import datasets as ds
import engine_b as B
from engine_b import (C_COST, C_DIR, C_EBAR, C_ENTRY, C_GROSS, C_HIT1, C_HIT2, C_HIT3, C_R, C_REASON, C_RISK,
                      C_SCORE, C_SL0, C_TP1, C_TP2, C_TP3, C_TRIG, C_XBAR, C_XPX, NAN, NREC, R_BE, R_REM, R_REV,
                      R_SL, R_TP, R_TP3)

_close_trade = B._close_trade
_stop_reason = B._stop_reason
_pmax = B._pmax
_pmin = B._pmin
R_TIME = 6
REASONS = ("SL", "Remaining SL", "BE/Trail", "TP", "TP3", "Reverse", "Time")
SETUPS = ("B&R", "ORB", "BRK", "EMA", "PB", "FLIP", "VWAP", "SWEEP", "DIV", "REB")


@dataclass
class FParams:                       # defaults == the Pine input defaults
    assetIn: str = "Auto"            # "Auto" | "Metals / FX / Commodities" | "Crypto" | "Stocks / Indices"
    minScore: int = 5
    useAnchor: bool = True
    useHtfGate: bool = True
    sessIn: str = "Auto"             # "Auto" | "On" | "Off"
    sessStr: str = "0800-1700"
    sessTz: str = "America/New_York"
    dirMode: str = "Both"
    adxMin: float = 25.0
    reverseOn: bool = True
    ltfPack: bool = True
    pbFrac: float = 0.33
    pbBars: int = 3
    maxBarAtr: float = 2.5
    minStopPct: float = 0.43
    useBrt: bool = True
    useOrb: bool = True
    useBrk: bool = True
    donLen: int = 20
    useEma: bool = True
    usePb: bool = True
    useFlip: bool = True
    stFactor: float = 3.0
    stLen: int = 10
    useVwap: bool = True
    useSweep: bool = False
    useDiv: bool = False
    volMult: float = 1.0
    pvLen: int = 5
    vwapAway: int = 6
    emaWindow: int = 3
    brtTol: float = 0.3
    brtWindow: int = 20
    sweepLen: int = 20
    divGap: int = 60
    orMin: int = 15
    profile: str = "AUTO"            # "AUTO" | "MW" | "HW" | "BAL" | "HP" | "RUN" | "CUS"
    swingLook: int = 10
    slBuf: float = 0.25
    slMinAtr: float = 0.8
    slMaxAtr: float = 3.5
    cTp1: float = 1.0
    cW1: float = 50.0
    cTp2: float = 3.0
    cW2: float = 25.0
    cTp3: float = 5.0
    cTrail: bool = False
    cBe: bool = True
    chLen: int = 22
    chMult: float = 3.0
    maxBars: int = 0
    smallGuard: bool = True
    cgMaxPct: float = 7.0
    costMode: str = "Auto"
    costCustom: float = 0.05


PROFILES = {  # k1, k2, k3, w1, w2, trailOn, trailFrom, beOn  (the script's profile table; SHD / SNP are new in v2)
    "SHD": {"k1": 0.05, "k2": 1.5, "k3": 4.0, "w1": 0.50, "w2": 0.25, "trailOn": False, "trailFrom": 1, "beOn": True},
    "SNP": {"k1": 0.2, "k2": 1.5, "k3": 4.0, "w1": 0.60, "w2": 0.20, "trailOn": False, "trailFrom": 1, "beOn": True},
    "MW":  {"k1": 0.4, "k2": 1.5, "k3": 4.0, "w1": 0.60, "w2": 0.20, "trailOn": False, "trailFrom": 1, "beOn": True},
    "BAL": {"k1": 1.0, "k2": 3.0, "k3": 5.0, "w1": 0.50, "w2": 0.25, "trailOn": False, "trailFrom": 1, "beOn": True},
    "HW":  {"k1": 0.5, "k2": 2.0, "k3": 5.0, "w1": 0.50, "w2": 0.25, "trailOn": False, "trailFrom": 1, "beOn": True},
    "HP":  {"k1": 0.3, "k2": 1.5, "k3": 4.0, "w1": 0.50, "w2": 0.25, "trailOn": True, "trailFrom": 1, "beOn": True},
    "RUN": {"k1": 1.0, "k2": 2.0, "k3": 8.0, "w1": 0.33, "w2": 0.33, "trailOn": True, "trailFrom": 2, "beOn": False},
}


def asset_class(market, p: FParams) -> str:
    """-> "crypto" | "stock" | "metal" (the script's assetClass; "metal" = metals / FX / commodities)."""
    if p.assetIn == "Crypto":
        return "crypto"
    if p.assetIn == "Stocks / Indices":
        return "stock"
    if p.assetIn != "Auto":
        return "metal"
    tk = market.ticker
    metal_ticker = any(k in tk for k in ("XAU", "XAG", "PAXG", "GOLD", "SILVER"))
    if market.sym_type == "crypto" and not metal_ticker:
        return "crypto"
    if market.sym_type in ("stock", "fund", "dr", "index"):
        return "stock"
    return "metal"


def cost_pct(market, p: FParams) -> float:
    if p.costMode != "Auto":
        return p.costCustom
    tk = market.ticker
    ac = asset_class(market, p)
    hi_cost = any(k in tk for k in ("XAG", "SILVER", "XPT", "XCU"))
    is_gold = ac == "metal" and any(k in tk for k in ("XAU", "PAXG", "GOLD"))
    return 0.10 if ac == "crypto" else 0.06 if hi_cost else 0.01 if is_gold else 0.03


def mgmt_of(market, p: FParams) -> dict:
    prof = p.profile
    if prof == "AUTO":
        prof = "HW" if market.tf_seconds >= 3600 else ("MW" if p.ltfPack else "BAL")
    if prof == "CUS":
        return {"k1": p.cTp1, "k2": p.cTp2, "k3": p.cTp3, "w1": p.cW1 / 100, "w2": p.cW2 / 100,
                "trailOn": p.cTrail, "trailFrom": 1, "beOn": p.cBe}
    return dict(PROFILES[prof])


# ───────────────────────────── data context (higher timeframes, sessions) ─────────────────────────────
def _local_minutes(t: np.ndarray, tz: str) -> np.ndarray:
    idx = pd.to_datetime(np.asarray(t, dtype=np.int64), unit="s", utc=True).tz_convert(tz)
    return (idx.hour * 60 + idx.minute).to_numpy()


def _session_mask(t: np.ndarray, sess: str, tz: str) -> np.ndarray:
    """time(timeframe.period, "HHMM-HHMM", tz) is not na  <=>  the bar's open time is inside the session."""
    a, b = sess.split("-")
    start = int(a[:2]) * 60 + int(a[2:])
    end = int(b[:2]) * 60 + int(b[2:])
    m = _local_minutes(t, tz)
    return (m >= start) & (m < end) if start < end else (m >= start) | (m < end)


def _resample(bars: dict, keys) -> dict:
    return ds.resample_by_key(bars, list(keys))


def _session_keys(t: np.ndarray, anchor_hour: int, bucket_s: int) -> list:
    """(session date, bucket) keys for bars of a market whose trading day starts at anchor_hour New York time."""
    idx = pd.to_datetime(np.asarray(t, dtype=np.int64), unit="s", utc=True).tz_convert("America/New_York")
    shifted = idx - pd.Timedelta(hours=anchor_hour)
    sec = (shifted.hour * 3600 + shifted.minute * 60 + shifted.second).to_numpy()
    dates = shifted.strftime("%Y-%m-%d").to_numpy()
    return [(d, int(s) // bucket_s) for d, s in zip(dates, sec)]


def _month_keys(daily: dict, exchange: str) -> list:
    shift = 0 if exchange.startswith("BINANCE") else 12 * 3600
    idx = pd.to_datetime(np.asarray(daily["t"], dtype=np.int64) + shift, unit="s", utc=True)
    return list(zip(idx.year.to_numpy(), idx.month.to_numpy()))


_CTX: dict = {}


def context(name: str) -> dict:
    """Chart bars plus everything the script reads from other timeframes: HTF bars, anchor bars, the daily-bar
    index of every chart bar (for timeframe.change("D")) and the market description."""
    if name in _CTX:
        return _CTX[name]
    chart = ds.load(name)
    m = ds.market_of(name, chart)
    stem = f"{m.exchange}_{m.ticker}_"
    tf = m.tf_seconds

    def have(itv):
        try:
            return ds.load(stem + itv)
        except OSError:
            return None

    daily = have("1D")
    h4 = have("4h")
    h1 = have("1h")
    if m.exchange == "YF":                      # Yahoo: no 4h / 1D files; build them from its own 1h series
        anchor_hour = 17 if m.sym_type == "forex" else 18
        src = h1 if h1 is not None else chart
        h4 = _resample(src, _session_keys(src["t"], anchor_hour, 14400))
        daily = _resample(src, _session_keys(src["t"], anchor_hour, 86400))
    weekly = ds.weekly_from_daily(daily, m.exchange) if daily is not None else None
    monthly = _resample(daily, _month_keys(daily, m.exchange)) if daily is not None else None
    if tf >= 86400:
        day_idx = np.arange(len(chart["t"]))
    elif daily is not None:
        day_idx = np.searchsorted(daily["t"], chart["t"], side="right") - 1
    else:
        day_idx = np.asarray(chart["t"]) // 86400
    ctx = {"name": name, "chart": chart, "market": m, "h1": h1, "h4": h4, "daily": daily, "weekly": weekly,
           "monthly": monthly, "day_idx": day_idx}
    _CTX[name] = ctx
    return ctx


def _sec_trend(chart_t, bars, ema_len) -> np.ndarray:
    """nz(request.security(tickerid, tf, htfTrendCalc(len)[1], lookahead_on)) on every chart bar."""
    out = np.zeros(len(chart_t))
    if bars is None or len(bars["t"]) == 0:
        return out
    trend = B._htf_trend_calc(B._f64(bars["h"]), B._f64(bars["l"]), B._f64(bars["c"]), ema_len)
    k = np.searchsorted(np.asarray(bars["t"]), np.asarray(chart_t), side="right") - 2
    ok = k >= 0
    out[ok] = trend[k[ok]]
    return out


def _tf_bars(ctx, seconds):
    return {3600: ctx["h1"], 14400: ctx["h4"], 86400: ctx["daily"], 604800: ctx["weekly"], 2592000: ctx["monthly"]}.get(seconds)


def htf_seconds(tf: int, ltf_pack: bool) -> int:
    """autoHtf(): 5m uses 1H only when the execution pack is off; otherwise <=1H -> 4H, <=4H -> 1D, <=1D -> 1W."""
    if tf <= 300 and not ltf_pack:
        return 3600
    return 14400 if tf <= 3600 else 86400 if tf <= 14400 else 604800 if tf <= 86400 else 2592000


def anchor_seconds(tf: int) -> int:
    return 86400 if tf <= 3600 else 604800 if tf <= 14400 else 2592000


# ───────────────────────────── setup kernels ─────────────────────────────
@njit(cache=True, error_model="numpy")
def _pivots(x, n, high_side):
    """ta.pivothigh / ta.pivotlow(x, n, n): value reported n bars after the pivot bar (nan otherwise).
    Ties: the pivot must be strictly beyond the n bars to its left and at least equal to the n bars to its right."""
    m = len(x)
    out = np.full(m, NAN)
    for i in range(2 * n, m):
        k = i - n
        p = x[k]
        ok = not math.isnan(p)
        if ok:
            for j in range(k - n, k):
                if high_side and not (x[j] < p):
                    ok = False
                    break
                if (not high_side) and not (x[j] > p):
                    ok = False
                    break
        if ok:
            for j in range(k + 1, i + 1):
                if high_side and not (x[j] <= p):
                    ok = False
                    break
                if (not high_side) and not (x[j] >= p):
                    ok = False
                    break
        if ok:
            out[i] = p
    return out


@njit(cache=True, error_model="numpy")
def _state_setups(o, h, l, c, v, atr, rsi, vol_ok, new_day, in_or, t_s, ph, pl, pv_len, brt_tol, brt_window,
                  div_gap, or_min, use_orb, vwap_away):
    """The stateful GBB setups: session VWAP reclaim, break & retest, RSI divergence, opening-range break."""
    n = len(c)
    vwap = np.full(n, NAN)
    s_vwap_l = np.zeros(n, np.bool_)
    s_vwap_s = np.zeros(n, np.bool_)
    s_brt_l = np.zeros(n, np.bool_)
    s_brt_s = np.zeros(n, np.bool_)
    s_div_l = np.zeros(n, np.bool_)
    s_div_s = np.zeros(n, np.bool_)
    s_orb_l = np.zeros(n, np.bool_)
    s_orb_s = np.zeros(n, np.bool_)
    cpv = 0.0
    cv = 0.0
    below_run = 0
    above_run = 0
    hi_lvl = NAN
    hi_brk = False
    hi_bar = -1
    hi_pend = NAN
    lo_lvl = NAN
    lo_brk = False
    lo_bar = -1
    lo_pend = NAN
    last_pl_p = NAN
    last_pl_r = NAN
    last_pl_b = -1
    last_ph_p = NAN
    last_ph_r = NAN
    last_ph_b = -1
    or_h = NAN
    or_l = NAN
    or_done = False
    or_fired = False
    or_start = -1
    for i in range(n):
        ready = (not math.isnan(atr[i])) and atr[i] > 0.0
        bull = c[i] > o[i]
        bear = c[i] < o[i]
        # ── session VWAP (reset on a new daily bar) and the reclaim setup
        if new_day[i]:
            cpv = 0.0
            cv = 0.0
        vol = 0.0 if math.isnan(v[i]) else v[i]
        cpv += (h[i] + l[i] + c[i]) / 3.0 * vol
        cv += vol
        vw = cpv / cv if cv > 0.0 else NAN
        vwap[i] = vw
        prev_below = below_run
        prev_above = above_run
        cross_up = False
        cross_dn = False
        if i > 0 and (not math.isnan(vw)) and (not math.isnan(vwap[i - 1])):
            cross_up = c[i] > vw and c[i - 1] <= vwap[i - 1]
            cross_dn = c[i] < vw and c[i - 1] >= vwap[i - 1]
        if not math.isnan(vw):
            below_run = below_run + 1 if c[i] < vw else 0
            above_run = above_run + 1 if c[i] > vw else 0
            s_vwap_l[i] = cross_up and prev_below >= vwap_away and vol_ok[i]
            s_vwap_s[i] = cross_dn and prev_above >= vwap_away and vol_ok[i]
        # ── break & retest of a confirmed swing
        hi_busy = hi_brk and hi_bar >= 0 and i - hi_bar <= brt_window
        lo_busy = lo_brk and lo_bar >= 0 and i - lo_bar <= brt_window
        if not math.isnan(ph[i]):
            if hi_busy:
                hi_pend = ph[i]
            else:
                hi_lvl = ph[i]
                hi_brk = False
                hi_pend = NAN
        if not math.isnan(pl[i]):
            if lo_busy:
                lo_pend = pl[i]
            else:
                lo_lvl = pl[i]
                lo_brk = False
                lo_pend = NAN
        if (not math.isnan(hi_lvl)) and (not hi_brk) and c[i] > hi_lvl:
            hi_brk = True
            hi_bar = i
        if (not math.isnan(lo_lvl)) and (not lo_brk) and c[i] < lo_lvl:
            lo_brk = True
            lo_bar = i
        live_l = hi_brk and hi_bar >= 0 and i - hi_bar <= brt_window and i > hi_bar
        live_s = lo_brk and lo_bar >= 0 and i - lo_bar <= brt_window and i > lo_bar
        if live_l and ready and l[i] <= hi_lvl + atr[i] * brt_tol and c[i] > hi_lvl and bull:
            s_brt_l[i] = True
            hi_brk = False
        if live_s and ready and h[i] >= lo_lvl - atr[i] * brt_tol and c[i] < lo_lvl and bear:
            s_brt_s[i] = True
            lo_brk = False
        if (not (hi_brk and hi_bar >= 0 and i - hi_bar <= brt_window)) and (not math.isnan(hi_pend)):
            hi_lvl = hi_pend
            hi_brk = False
            hi_pend = NAN
        if (not (lo_brk and lo_bar >= 0 and i - lo_bar <= brt_window)) and (not math.isnan(lo_pend)):
            lo_lvl = lo_pend
            lo_brk = False
            lo_pend = NAN
        # ── RSI divergence (confirmed pv_len bars after the pivot)
        r_piv = rsi[i - pv_len] if i >= pv_len else NAN
        if not math.isnan(pl[i]):
            if (not math.isnan(last_pl_p)) and i - last_pl_b <= div_gap:
                s_div_l[i] = pl[i] < last_pl_p and r_piv > last_pl_r
            last_pl_p = pl[i]
            last_pl_r = r_piv
            last_pl_b = i
        if not math.isnan(ph[i]):
            if (not math.isnan(last_ph_p)) and i - last_ph_b <= div_gap:
                s_div_s[i] = ph[i] > last_ph_p and r_piv < last_ph_r
            last_ph_p = ph[i]
            last_ph_r = r_piv
            last_ph_b = i
        # ── opening-range break (one break per session)
        new_or = in_or[i] and (i == 0 or not in_or[i - 1])
        if new_or:
            or_h = h[i]
            or_l = l[i]
            or_done = False
            or_fired = False
            or_start = t_s[i]
        elif in_or[i] and not or_done:
            if or_start >= 0 and (t_s[i] - or_start) >= or_min * 60:
                or_done = True
            else:
                or_h = h[i] if math.isnan(or_h) else _pmax(or_h, h[i])
                or_l = l[i] if math.isnan(or_l) else _pmin(or_l, l[i])
        ol = in_or[i] and or_done and (not or_fired) and (not math.isnan(or_h)) and c[i] > or_h
        os_ = in_or[i] and or_done and (not or_fired) and (not math.isnan(or_l)) and c[i] < or_l
        s_orb_l[i] = ol
        s_orb_s[i] = os_
        if use_orb and (ol or os_):
            or_fired = True
    return vwap, s_vwap_l, s_vwap_s, s_brt_l, s_brt_s, s_div_l, s_div_s, s_orb_l, s_orb_s


@njit(cache=True, error_model="numpy")
def _barssince(cond):
    n = len(cond)
    out = np.full(n, NAN)
    last = -1
    for i in range(n):
        if cond[i]:
            last = i
        if last >= 0:
            out[i] = i - last
    return out


def _shift(x, k):
    out = np.full(len(x), NAN)
    if k < len(x):
        out[k:] = x[:-k] if k > 0 else x
    return out


def features(ctx: dict, p: FParams) -> dict:
    """Every per-bar series of the script up to longSig / shortSig."""
    chart, m = ctx["chart"], ctx["market"]
    o, h, l, c, v = (B._f64(chart[k]) for k in ("o", "h", "l", "c", "v"))
    t = np.asarray(chart["t"], dtype=np.int64)
    n = len(c)
    tf = int(m.tf_seconds)
    intraday = tf < 86400
    ac = asset_class(m, p)
    with np.errstate(invalid="ignore", divide="ignore"):
        tr = B._true_range(h, l, c, True)
        atr = B._rma(tr, 14)
        ema9, ema21, ema50, ema55, ema200 = (B._ema(c, k) for k in (9, 21, 50, 55, 200))
        st_atr = B._rma(tr, int(p.stLen))
        _, st_dir = B._supertrend(h, l, c, float(p.stFactor), st_atr)
        di_p, di_m, adx = B._dmi(h, l, c, 14, 14)
        rsi = B._rsi(c, 14)
        vol_ma = np.full(n, NAN)
        if n >= 20:
            cs = np.concatenate([[0.0], np.cumsum(v)])
            vol_ma[19:] = (cs[20:] - cs[:-20]) / 20.0
        vol_ok = (p.volMult <= 0) | np.isnan(v) | np.isnan(vol_ma) | (v >= vol_ma * p.volMult)
        ready = ~np.isnan(atr) & (atr > 0)
        bull, bear = c > o, c < o
        c1, h1, l1 = _shift(c, 1), _shift(h, 1), _shift(l, 1)

        # higher timeframe / anchor trends (previous completed bar of each)
        hs = htf_seconds(tf, p.ltfPack)
        if hs <= tf:
            htf_bars, hs = chart, tf
        else:
            htf_bars = _tf_bars(ctx, hs)
        htf_trend = _sec_trend(t, htf_bars, 21 if hs >= 86400 else 50)
        as_ = anchor_seconds(tf)
        anchor_bars = chart if as_ <= tf else _tf_bars(ctx, as_)
        anchor_trend = _sec_trend(t, anchor_bars, 21)

        # APEX score
        adx3 = _shift(adx, 3)

        def score(d):
            s = (htf_trend == d).astype(np.int64)
            s += ((c - ema200) * d > 0)
            s += ((ema21 - ema55) * d > 0)
            s += (adx > p.adxMin)
            s += ((adx > adx3) & (adx > 18))
            s += ((di_p - di_m) * d > 0)
            s += ((rsi - 50) * d > 0)
            return s
        score_l, score_s = score(1), score(-1)

        # APEX triggers
        don_hi = _shift(B._rolling_max(h, int(p.donLen)), 1)
        don_lo = _shift(B._rolling_min(l, int(p.donLen)), 1)
        s_brk_l = (c > don_hi) & (c1 <= _shift(don_hi, 1))
        s_brk_s = (c < don_lo) & (c1 >= _shift(don_lo, 1))
        st1 = _shift(st_dir, 1)
        s_flip_l = (st_dir < 0) & (st1 > 0)
        s_flip_s = (st_dir > 0) & (st1 < 0)
        touch_up = B._rolling_min(l - ema21, 5) <= 0
        touch_dn = B._rolling_max(h - ema21, 5) >= 0
        s_pb_l = (st_dir < 0) & touch_up & (c > h1) & (c > ema21) & bull
        s_pb_s = (st_dir > 0) & touch_dn & (c < l1) & (c < ema21) & bear
        # GBB: EMA pullback
        e50_3 = _shift(ema50, 3)
        up_g = (ema21 > ema50) & (ema50 > e50_3)
        dn_g = (ema21 < ema50) & (ema50 < e50_3)
        t_up = _barssince(l <= ema21) <= p.emaWindow
        t_dn = _barssince(h >= ema21) <= p.emaWindow
        s_ema_l = up_g & t_up & (c > ema9) & bull & (c > h1) & vol_ok
        s_ema_s = dn_g & t_dn & (c < ema9) & bear & (c < l1) & vol_ok
        # GBB: liquidity sweep
        sw_lo = _shift(B._rolling_min(l, int(p.sweepLen)), 1)
        sw_hi = _shift(B._rolling_max(h, int(p.sweepLen)), 1)
        s_sw_l = ~np.isnan(sw_lo) & (l < sw_lo) & (c > sw_lo) & bull & ((c - l) > (h - c)) & vol_ok
        s_sw_s = ~np.isnan(sw_hi) & (h > sw_hi) & (c < sw_hi) & bear & ((h - c) > (c - l)) & vol_ok
        # stateful GBB setups
        day_idx = np.asarray(ctx["day_idx"])
        new_day = np.zeros(n, np.bool_)
        new_day[1:] = day_idx[1:] != day_idx[:-1]
        or_sess, or_tz = ("0000-2300", "UTC") if ac == "crypto" else ("0930-1600", "America/New_York")
        in_or = _session_mask(t, or_sess, or_tz)
        ph = _pivots(h, int(p.pvLen), True)
        pl = _pivots(l, int(p.pvLen), False)
        (vwap, s_vw_l, s_vw_s, s_brt_l, s_brt_s, s_div_l, s_div_s, s_orb_l, s_orb_s) = _state_setups(
            o, h, l, c, v, atr, rsi, np.ascontiguousarray(vol_ok), new_day, np.ascontiguousarray(in_or), t, ph, pl,
            int(p.pvLen), float(p.brtTol), int(p.brtWindow), int(p.divGap), int(p.orMin), bool(p.useOrb),
            int(p.vwapAway))

        # fusion gate
        in_sess = _session_mask(t, p.sessStr, p.sessTz)
        sess_on = p.sessIn == "On" or (p.sessIn == "Auto" and ac != "crypto")
        sess_applies = sess_on and intraday and tf < 14400
        in_trade = in_sess if sess_applies else np.ones(n, np.bool_)
        base_l = in_trade & ((anchor_trend == 1) if p.useAnchor else True)
        base_s = in_trade & ((anchor_trend == -1) if p.useAnchor else True)
        ltf_on = bool(p.ltfPack) and intraday and tf < 3600
        ok_bar = ((h - l) <= p.maxBarAtr * atr) if ltf_on else np.ones(n, np.bool_)
        gate_l = base_l & (score_l >= p.minScore) & ((htf_trend == 1) if p.useHtfGate else True) & ok_bar
        gate_s = base_s & (score_s >= p.minScore) & ((htf_trend == -1) if p.useHtfGate else True) & ok_bar
        rev_l = base_l & (htf_trend != -1)
        rev_s = base_s & (htf_trend != 1)

        def pick(cands):
            code = np.full(n, -1, np.int64)
            for k, mask in cands:
                code = np.where((code < 0) & mask, k, code)
            return np.where(ready, code, -1)
        setup_l = pick([(0, p.useBrt & s_brt_l & gate_l), (1, p.useOrb & s_orb_l & gate_l), (2, p.useBrk & s_brk_l & gate_l),
                        (3, p.useEma & s_ema_l & gate_l), (4, p.usePb & s_pb_l & gate_l), (5, p.useFlip & s_flip_l & gate_l),
                        (6, p.useVwap & s_vw_l & gate_l), (7, p.useSweep & s_sw_l & rev_l), (8, p.useDiv & s_div_l & rev_l)])
        setup_s = pick([(0, p.useBrt & s_brt_s & gate_s), (1, p.useOrb & s_orb_s & gate_s), (2, p.useBrk & s_brk_s & gate_s),
                        (3, p.useEma & s_ema_s & gate_s), (4, p.usePb & s_pb_s & gate_s), (5, p.useFlip & s_flip_s & gate_s),
                        (6, p.useVwap & s_vw_s & gate_s), (7, p.useSweep & s_sw_s & rev_s), (8, p.useDiv & s_div_s & rev_s)])
        raw_l = (setup_l >= 0) & (p.dirMode != "Short only")
        raw_s = (setup_s >= 0) & (p.dirMode != "Long only") & ~raw_l

        # stops, cost guard, volatility floor
        sl_l = np.minimum(np.maximum(c - (B._rolling_min(l, int(p.swingLook)) - p.slBuf * atr), p.slMinAtr * atr), p.slMaxAtr * atr)
        sl_s = np.minimum(np.maximum((B._rolling_max(h, int(p.swingLook)) + p.slBuf * atr) - c, p.slMinAtr * atr), p.slMaxAtr * atr)
        cp = cost_pct(m, p)
        guard = bool(p.smallGuard) and tf < 3600
        cg_min = cp / 100 * c / (p.cgMaxPct / 100)
        cg_l = (sl_l >= cg_min) if guard else np.ones(n, np.bool_)
        cg_s = (sl_s >= cg_min) if guard else np.ones(n, np.bool_)
        fl_l = (sl_l >= p.minStopPct / 100 * c) if ltf_on else np.ones(n, np.bool_)
        fl_s = (sl_s >= p.minStopPct / 100 * c) if ltf_on else np.ones(n, np.bool_)
        warm = np.arange(n) >= 250
        long_sig = warm & raw_l & ready & cg_l & fl_l
        short_sig = warm & raw_s & ready & cg_s & fl_s
        chand_l = B._rolling_max(h, int(p.chLen)) - p.chMult * atr
        chand_s = B._rolling_min(l, int(p.chLen)) + p.chMult * atr
    return {"atr": atr, "htfTrend": htf_trend, "anchorTrend": anchor_trend, "scoreL": score_l, "scoreS": score_s,
            "setupL": setup_l, "setupS": setup_s, "longSig": long_sig, "shortSig": short_sig,
            "rawL": raw_l, "rawS": raw_s, "gateL": gate_l, "gateS": gate_s, "inSess": in_sess, "okBar": ok_bar,
            "cgL": cg_l, "cgS": cg_s, "floorL": fl_l, "floorS": fl_s,
            "slDistL": sl_l, "slDistS": sl_s, "chandL": chand_l, "chandS": chand_s, "vwap": vwap,
            "costPct": cp, "mintick": float(m.mintick), "usePullback": ltf_on, "assetClass": ac,
            "sBrtL": s_brt_l, "sBrtS": s_brt_s, "sOrbL": s_orb_l, "sOrbS": s_orb_s, "sVwapL": s_vw_l, "sVwapS": s_vw_s,
            "sEmaL": s_ema_l, "sEmaS": s_ema_s, "sBrkL": s_brk_l, "sBrkS": s_brk_s, "sPbL": s_pb_l, "sPbS": s_pb_s,
            "sFlipL": s_flip_l, "sFlipS": s_flip_s, "ph": ph, "pl": pl, "stDir": st_dir}


# ───────────────────────────── trade kernel ─────────────────────────────
@njit(cache=True, error_model="numpy")
def _core_fusion(o, h, l, c, long_sig, short_sig, sl_dist_l, sl_dist_s, chand_l, chand_s, setup_l, setup_s,
                 score_l, score_s, k1, k2, k3, w1, w2, trail_on, trail_from, be_on, costPct, mintick,
                 close_stop, use_pullback, pb_frac, pb_bars, max_bars, reverse_on):
    """engine_b._core + Fusion's pending pullback limit order, time exit and reverse switch (+ v2 close_stop).
    Returns (records, stats, n_signals, n_filled, n_unfilled)."""
    n = len(c)
    cap = 0
    for i in range(n):
        if long_sig[i] or short_sig[i]:
            cap += 1
    rec = np.empty((cap + 1, NREC))
    k = 0
    stats = np.zeros(16)
    has = False
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
    p_has = False
    p_dir = 1.0
    p_bar = 0
    p_limit = 0.0
    p_stop = 0.0
    p_setup = 0
    p_score = 0
    n_sig = 0
    n_fill = 0
    n_miss = 0
    for i in range(n):
        oi = o[i]
        hi = h[i]
        li = l[i]
        ci = c[i]
        # ── 1) manage the open trade on bars AFTER the entry bar
        if has and i > entry_bar:
            is_long = d == 1.0
            if trail_on and (hit1 if trail_from == 1 else hit2):
                tv = chand_l[i - 1] if is_long else chand_s[i - 1]
                if not math.isnan(tv):
                    sl = _pmax(sl, tv) if is_long else _pmin(sl, tv)
            if (oi <= sl) if is_long else (oi >= sl):
                _close_trade(stats, rec, k, i, d, entry_bar, trig, score, entry, sl0, risk, tp1, tp2, tp3,
                             hit1, hit2, hit3, realized, open_w, oi, _stop_reason(sl, sl0, open_w), costPct)
                k += 1
                has = False
            else:
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
                if has and hit2 and (not hit3) and (not math.isnan(tp3)) and ((oi >= tp3) if is_long else (oi <= tp3)):
                    hit3 = True
                    realized += open_w * k3
                    open_w = 0.0
                    _close_trade(stats, rec, k, i, d, entry_bar, trig, score, entry, sl0, risk, tp1, tp2, tp3,
                                 hit1, hit2, hit3, realized, open_w, tp3, R_TP3, costPct)
                    k += 1
                    has = False
                if has:
                    if trail_on and (hit1 if trail_from == 1 else hit2):
                        tv = chand_l[i - 1] if is_long else chand_s[i - 1]
                        if not math.isnan(tv):
                            sl = _pmax(sl, tv) if is_long else _pmin(sl, tv)
                    if (li <= sl) if is_long else (hi >= sl):
                        px = oi if ((is_long and oi < sl) or ((not is_long) and oi > sl)) else sl
                        _close_trade(stats, rec, k, i, d, entry_bar, trig, score, entry, sl0, risk, tp1, tp2, tp3,
                                     hit1, hit2, hit3, realized, open_w, px, _stop_reason(sl, sl0, open_w), costPct)
                        k += 1
                        has = False
                    else:
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
                            _close_trade(stats, rec, k, i, d, entry_bar, trig, score, entry, sl0, risk, tp1, tp2,
                                         tp3, hit1, hit2, hit3, realized, open_w, tp2 if hit2 else tp1, R_TP, costPct)
                            k += 1
                            has = False
                        if has and hit2 and (not hit3) and (not math.isnan(tp3)) and \
                                ((hi >= tp3) if is_long else (li <= tp3)):
                            hit3 = True
                            realized += open_w * k3
                            open_w = 0.0
                            _close_trade(stats, rec, k, i, d, entry_bar, trig, score, entry, sl0, risk, tp1, tp2,
                                         tp3, hit1, hit2, hit3, realized, open_w, tp3, R_TP3, costPct)
                            k += 1
                            has = False
                        # v2 rule (see engine_v2): a stop raised by this bar's own fill and crossed by its close (1)
                        # or touched by its range (2, pessimistic bound)
                        if has and ((close_stop == 1 and ((ci <= sl) if is_long else (ci >= sl))) or
                                    (close_stop == 2 and ((li <= sl) if is_long else (hi >= sl)))):
                            _close_trade(stats, rec, k, i, d, entry_bar, trig, score, entry, sl0, risk, tp1, tp2,
                                         tp3, hit1, hit2, hit3, realized, open_w, sl, _stop_reason(sl, sl0, open_w),
                                         costPct)
                            k += 1
                            has = False
                        if has and max_bars > 0 and i - entry_bar >= max_bars:
                            _close_trade(stats, rec, k, i, d, entry_bar, trig, score, entry, sl0, risk, tp1, tp2,
                                         tp3, hit1, hit2, hit3, realized, open_w, ci, R_TIME, costPct)
                            k += 1
                            has = False
        # ── 1b) pending pullback limit order: fill, expire or cancel (only while flat)
        if p_has:
            if has:
                p_has = False
                n_miss += 1
            elif i > p_bar:
                expired = i - p_bar > pb_bars
                invalid = (oi <= p_stop) if p_dir == 1.0 else (oi >= p_stop)
                if expired or invalid:
                    p_has = False
                    n_miss += 1
                elif (li <= p_limit) if p_dir == 1.0 else (hi >= p_limit):
                    fill = (oi if oi < p_limit else p_limit) if p_dir == 1.0 else (oi if oi > p_limit else p_limit)
                    if (fill - p_stop) * p_dir > 0.0:
                        d = p_dir
                        entry = fill
                        sl = p_stop
                        sl0 = p_stop
                        risk = (fill - p_stop) * d
                        tp1 = entry + d * k1 * risk
                        tp2 = entry + d * k2 * risk
                        t3 = entry + d * k3 * risk
                        tp3 = t3 if t3 > mintick else NAN
                        entry_bar = i
                        trig = p_setup
                        score = p_score
                        hit1 = False
                        hit2 = False
                        hit3 = False
                        realized = 0.0
                        open_w = 1.0
                        has = True
                        n_fill += 1
                        # unknown order inside the fill bar: if it also reached the stop, count the stop
                        if (li <= sl) if d == 1.0 else (hi >= sl):
                            _close_trade(stats, rec, k, i, d, entry_bar, trig, score, entry, sl0, risk, tp1, tp2,
                                         tp3, hit1, hit2, hit3, realized, open_w, sl, R_SL, costPct)
                            k += 1
                            has = False
                    else:
                        n_miss += 1
                    p_has = False
        # ── 2) new signals on bar close
        new_dir = 0.0
        if long_sig[i] and ((not has) or (reverse_on and d == -1.0)):
            new_dir = 1.0
        elif short_sig[i] and ((not has) or (reverse_on and d == 1.0)):
            new_dir = -1.0
        if new_dir != 0.0:
            n_sig += 1
            if has:
                _close_trade(stats, rec, k, i, d, entry_bar, trig, score, entry, sl0, risk, tp1, tp2, tp3,
                             hit1, hit2, hit3, realized, open_w, ci, R_REV, costPct)
                k += 1
                has = False
            dist = sl_dist_l[i] if new_dir == 1.0 else sl_dist_s[i]
            sc = score_l[i] if new_dir == 1.0 else score_s[i]
            su = setup_l[i] if new_dir == 1.0 else setup_s[i]
            if use_pullback:
                if p_has:
                    n_miss += 1
                p_has = True
                p_dir = new_dir
                p_bar = i
                p_limit = ci - new_dir * pb_frac * dist
                p_stop = ci - new_dir * dist
                p_setup = su
                p_score = sc
            else:
                d = new_dir
                entry = ci
                sl = ci - d * dist
                sl0 = sl
                risk = (entry - sl) * d
                tp1 = entry + d * k1 * risk
                tp2 = entry + d * k2 * risk
                t3 = entry + d * k3 * risk
                tp3 = t3 if t3 > mintick else NAN
                entry_bar = i
                trig = su
                score = sc
                hit1 = False
                hit2 = False
                hit3 = False
                realized = 0.0
                open_w = 1.0
                has = True
                n_fill += 1
    return rec[:k], stats, n_sig, n_fill, n_miss


def simulate(ctx: dict, f: dict, p: FParams, mgmt: dict | None = None, cost_pct_override: float | None = None,
             long_sig=None, short_sig=None, use_pullback=None):
    """Run the trade kernel on precomputed features.  -> (trades list, stats dict, info dict)."""
    ch = ctx["chart"]
    m = dict(mgmt_of(ctx["market"], p))
    if mgmt:
        m.update(mgmt)
    cp = f["costPct"] if cost_pct_override is None else cost_pct_override
    ls = f["longSig"] if long_sig is None else long_sig
    ss = f["shortSig"] if short_sig is None else short_sig
    up = f["usePullback"] if use_pullback is None else use_pullback
    rec, stats, n_sig, n_fill, n_miss = _core_fusion(
        B._f64(ch["o"]), B._f64(ch["h"]), B._f64(ch["l"]), B._f64(ch["c"]),
        np.ascontiguousarray(ls, np.bool_), np.ascontiguousarray(ss, np.bool_),
        B._f64(f["slDistL"]), B._f64(f["slDistS"]), B._f64(f["chandL"]), B._f64(f["chandS"]),
        np.ascontiguousarray(np.maximum(f["setupL"], 0), np.int64), np.ascontiguousarray(np.maximum(f["setupS"], 0), np.int64),
        np.ascontiguousarray(f["scoreL"], np.int64), np.ascontiguousarray(f["scoreS"], np.int64),
        float(m["k1"]), float(m["k2"]), float(m["k3"]), float(m["w1"]), float(m["w2"]), bool(m["trailOn"]),
        int(m["trailFrom"]), bool(m["beOn"]), float(cp), float(f["mintick"]), int(m.get("closeStop", 0)),
        bool(up), float(p.pbFrac), int(p.pbBars), int(p.maxBars), bool(p.reverseOn))
    trades = []
    for r in rec.tolist():
        tp3 = r[C_TP3]
        trades.append({"dir": int(r[C_DIR]), "entry_bar": int(r[C_EBAR]), "exit_bar": int(r[C_XBAR]),
                       "setup": SETUPS[int(r[C_TRIG])], "score": int(r[C_SCORE]), "entry": r[C_ENTRY], "sl0": r[C_SL0],
                       "risk": r[C_RISK], "tp1": r[C_TP1], "tp2": r[C_TP2], "tp3": None if tp3 != tp3 else tp3,
                       "hit1": r[C_HIT1] != 0.0, "hit2": r[C_HIT2] != 0.0, "hit3": r[C_HIT3] != 0.0,
                       "exit_px": r[C_XPX], "reason": REASONS[int(r[C_REASON])], "gross_R": r[C_GROSS],
                       "cost_R": r[C_COST], "R": r[C_R]})
    return trades, B.stats_dict(stats), {"signals": int(n_sig), "filled": int(n_fill), "unfilled": int(n_miss)}


def _trades_from(rec):
    out = []
    for r in rec.tolist():
        tp3 = r[C_TP3]
        out.append({"dir": int(r[C_DIR]), "entry_bar": int(r[C_EBAR]), "exit_bar": int(r[C_XBAR]),
                    "setup": SETUPS[int(r[C_TRIG])], "score": int(r[C_SCORE]), "entry": r[C_ENTRY], "sl0": r[C_SL0],
                    "risk": r[C_RISK], "tp1": r[C_TP1], "tp2": r[C_TP2], "tp3": None if tp3 != tp3 else tp3,
                    "hit1": r[C_HIT1] != 0.0, "hit2": r[C_HIT2] != 0.0, "hit3": r[C_HIT3] != 0.0,
                    "exit_px": r[C_XPX], "reason": REASONS[int(r[C_REASON])], "gross_R": r[C_GROSS],
                    "cost_R": r[C_COST], "R": r[C_R]})
    return out


def replay(ctx: dict, f: dict, fine: dict, p: FParams, mgmt: dict | None = None):
    """Intrabar replay (same idea as engine_v2.magnify): signals, stop distances and the chandelier come from
    the chart timeframe; fills, stops and targets are decided bar by bar on finer bars of the same feed.
    A signal acts on the last fine bar of its chart bar; a pending limit order stays valid for pbBars chart bars
    (converted to fine bars).  Both simulations start flat on the first chart bar that has fine data.
    -> (replayed trades, chart-bar trades over the same period, times of the fine bars, first chart bar)."""
    ch = ctx["chart"]
    m = dict(mgmt_of(ctx["market"], p))
    if mgmt:
        m.update(mgmt)
    ct = np.asarray(ch["t"])
    di = np.searchsorted(ct, np.asarray(fine["t"]), side="right") - 1
    keep = di >= 0
    di = di[keep]
    fb = {k: np.asarray(v)[keep] for k, v in fine.items()}
    nf = len(di)
    last = np.ones(nf, np.bool_)
    last[:-1] = di[1:] != di[:-1]
    d0 = int(di[0])
    ls_c = np.array(f["longSig"], np.bool_)
    ss_c = np.array(f["shortSig"], np.bool_)
    ls_c[:d0 + 1] = False
    ss_c[:d0 + 1] = False
    ls_f = np.zeros(nf, np.bool_)
    ss_f = np.zeros(nf, np.bool_)
    ls_f[last] = ls_c[di[last]]
    ss_f[last] = ss_c[di[last]]
    prev = np.maximum(di - 1, 0)
    ch_l = np.asarray(f["chandL"])[prev].astype(np.float64)
    ch_s = np.asarray(f["chandS"])[prev].astype(np.float64)
    ch_l[di == 0] = NAN
    ch_s[di == 0] = NAN
    ch_l = np.concatenate([ch_l[1:], [NAN]])
    ch_s = np.concatenate([ch_s[1:], [NAN]])
    per_bar = max(1, int(round(nf / max(1, len(np.unique(di))))))
    args_tail = (float(m["k1"]), float(m["k2"]), float(m["k3"]), float(m["w1"]), float(m["w2"]), bool(m["trailOn"]),
                 int(m["trailFrom"]), bool(m["beOn"]), float(f["costPct"]), float(f["mintick"]), int(m.get("closeStop", 0)))
    su_l = np.maximum(f["setupL"], 0).astype(np.int64)
    su_s = np.maximum(f["setupS"], 0).astype(np.int64)
    rec_f, _, _, _, _ = _core_fusion(
        B._f64(fb["o"]), B._f64(fb["h"]), B._f64(fb["l"]), B._f64(fb["c"]), ls_f, ss_f,
        B._f64(np.asarray(f["slDistL"])[di]), B._f64(np.asarray(f["slDistS"])[di]), ch_l, ch_s,
        np.ascontiguousarray(su_l[di]), np.ascontiguousarray(su_s[di]),
        np.ascontiguousarray(np.asarray(f["scoreL"], np.int64)[di]), np.ascontiguousarray(np.asarray(f["scoreS"], np.int64)[di]),
        *args_tail, bool(f["usePullback"]), float(p.pbFrac), int(p.pbBars) * per_bar, int(p.maxBars) * per_bar, bool(p.reverseOn))
    rec_c, _, _, _, _ = _core_fusion(
        B._f64(ch["o"]), B._f64(ch["h"]), B._f64(ch["l"]), B._f64(ch["c"]), ls_c, ss_c,
        B._f64(f["slDistL"]), B._f64(f["slDistS"]), B._f64(f["chandL"]), B._f64(f["chandS"]),
        np.ascontiguousarray(su_l), np.ascontiguousarray(su_s),
        np.ascontiguousarray(f["scoreL"], np.int64), np.ascontiguousarray(f["scoreS"], np.int64),
        *args_tail, bool(f["usePullback"]), float(p.pbFrac), int(p.pbBars), int(p.maxBars), bool(p.reverseOn))
    return _trades_from(rec_f), _trades_from(rec_c), fb["t"], d0


def run(name: str, p: FParams | None = None, mgmt: dict | None = None):
    p = p or FParams()
    ctx = context(name)
    f = features(ctx, p)
    return simulate(ctx, f, p, mgmt) + (f,)


if __name__ == "__main__":
    import sys
    for nm in (sys.argv[1:] or ["OANDA_XAUUSD_5m", "OANDA_XAUUSD_15m", "OANDA_XAUUSD_1h", "OANDA_XAUUSD_4h", "OANDA_XAUUSD_1D", "YF_GOLD_5m", "YF_GOLD_1h"]):
        tr, st, info, _ = run(nm)
        n = max(st["n"], 1)
        print(f"{nm:20s} signals={info['signals']:4d} filled={info['filled']:4d} trades={st['n']:4d} win={100*st['win']/n:5.1f}% "
              f"tp1={100*st['tp1']/n:5.1f}% net={st['net']:+7.2f}R PF={st['gross']/max(st['loss'],1e-9):5.2f}")
