#!/usr/bin/env python3
"""APEX engine, v2 simulation rules on top of the verified v1 port (engine_b).

Everything that computes signals is imported unchanged from engine_b.  Only the trade kernel differs, by one
extra management rule selected with mgmt["closeStop"]:

  0  v1 behaviour: a stop raised by a fill inside a bar (breakeven after TP1, TP1 lock after TP2) is not
     looked at again on that bar; the remainder is carried to the next bar.
  1  v2 default (Pine input `closeStop`): if that bar CLOSES at or through the raised stop, the remainder
     exits at the stop on that bar.  This is the one case where the order of events inside the bar is known.
  2  pessimistic bound for research only: if the bar's LOW/HIGH reached the raised stop, assume it was hit.

The kernel below is a generated copy of engine_b._core with that rule added (do not edit by hand: regenerate
from engine_b and re-run test_v2.py, which proves that closeStop = 0 equals engine_b on every dataset).

`magnify()` replays the management of chart-timeframe trades on finer bars of the same feed (what the Pine
script does with request.security_lower_tf): signals, entries, stop distances and the chandelier come from the
chart timeframe, every stop/target decision is taken bar by bar on the finer series.
"""
from __future__ import annotations

import math

import numpy as np
from numba import njit

import engine_b as _B
from engine_b import *  # noqa: F401,F403  (Params, features, base_features, mgmt_of, cost_pct, run, simulate, ...)
from engine_b import (NAN, NOPEN, NREC, O_DIR, O_EBAR, O_ENTRY, O_HAS, O_HIT1, O_HIT2, O_HIT3, O_RISK, O_SCORE,
                      O_SL, O_SL0, O_TP1, O_TP2, O_TP3, O_TRIG, R_BE, R_REM, R_REV, R_SL, R_TP, R_TP3)

_close_trade = _B._close_trade
_stop_reason = _B._stop_reason
_pmax = _B._pmax
_pmin = _B._pmin
_f64 = _B._f64
_trig_codes = _B._trig_codes
_score_arr = _B._score_arr
HAS_CLOSE_STOP = True


@njit(cache=True, error_model="numpy")
def _core_v2(o, h, l, c, long_sig, short_sig, sl_dist_l, sl_dist_s, chand_l, chand_s,
          trig_l, trig_s, score_l, score_s,
          k1, k2, k3, w1, w2, trail_on, trail_from, be_on, costPct, mintick, close_stop):
    """engine_b._core plus the v2 rule `close_stop` (see the module docstring).  close_stop = 0 must reproduce
    engine_b._core bit for bit (test_v2.py checks that on every dataset)."""
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
                        # ── v2 rule.  In this branch the bar's low (high for shorts) stayed beyond the stop that
                        # was active when the bar began, so the bar can only end at/through the stop if one of
                        # the range fills above raised it (breakeven after TP1, TP1 lock after TP2).
                        #   1: the CLOSE is at/through the raised stop -> price crossed it after the fill for
                        #      certain (the close is the last trade of the bar): exit at the stop.   [Pine closeStop]
                        #   2: the LOW/HIGH is at/through the raised stop -> assume it was crossed after the fill
                        #      (pessimistic bound; the true order inside the bar is unknown).
                        if has and ((close_stop == 1 and ((ci <= sl) if is_long else (ci >= sl))) or
                                    (close_stop == 2 and ((li <= sl) if is_long else (hi >= sl)))):
                            _close_trade(stats, rec, k, i, d, entry_bar, trig, score, entry, sl0, risk,
                                         tp1, tp2, tp3, hit1, hit2, hit3, realized, open_w, sl,
                                         _stop_reason(sl, sl0, open_w), costPct)
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


def simulate_arrays(o, h, l, c, longSig, shortSig, slDistL, slDistS, chandL, chandS, mgmt, costPct,
                    mintick=0.01, trigCodeL=None, trigCodeS=None, scoreL=None, scoreS=None):
    """Same contract as engine_b.simulate_arrays, plus mgmt["closeStop"] in {0, 1, 2} (default 0)."""
    n = len(c)
    return _core_v2(_f64(o), _f64(h), _f64(l), _f64(c),
                    np.ascontiguousarray(longSig, dtype=np.bool_), np.ascontiguousarray(shortSig, dtype=np.bool_),
                    _f64(slDistL), _f64(slDistS), _f64(chandL), _f64(chandS),
                    _trig_codes(trigCodeL, n, None), _trig_codes(trigCodeS, n, None),
                    _score_arr(scoreL, n), _score_arr(scoreS, n),
                    float(mgmt["k1"]), float(mgmt["k2"]), float(mgmt["k3"]), float(mgmt["w1"]), float(mgmt["w2"]),
                    bool(mgmt["trailOn"]), int(mgmt["trailFrom"]), bool(mgmt["beOn"]),
                    float(costPct), float(mintick), int(mgmt.get("closeStop", 0)))


def magnify(chart: dict, feats: dict, fine: dict, mgmt: dict, costPct: float | None = None):
    """Replay the trade management on finer bars.

    chart, feats : chart-timeframe bars and engine features (signals, stop distances, chandelier)
    fine         : finer bars of the same feed (t = bar open); only the part overlapping the chart is used
    Signals act on the LAST fine bar of each chart bar (the chart bar's close); stops and targets are then
    evaluated on every fine bar with the kernel's usual rules, the trail using the chandelier of the previous
    completed CHART bar.  Both simulations start flat at the first chart bar that has fine data.
    Returns (rec_magnified, rec_chart, fine_used, first_chart_bar): trade records of the replay and of the
    plain chart-bar simulation over the same period (both with the given mgmt, e.g. closeStop).
    """
    ct = np.asarray(chart["t"])
    ft = np.asarray(fine["t"])
    di = np.searchsorted(ct, ft, side="right") - 1          # chart bar that contains each fine bar
    keep = di >= 0
    di = di[keep]
    F = {k: np.asarray(v)[keep] for k, v in fine.items()}
    nf = len(di)
    last = np.ones(nf, dtype=bool)
    last[:-1] = di[1:] != di[:-1]
    d0 = int(di[0])
    cp = feats["costPct"] if costPct is None else costPct
    long_c = np.array(feats["longSig"], dtype=bool)
    short_c = np.array(feats["shortSig"], dtype=bool)
    long_c[:d0 + 1] = False                                 # flat start for both simulations
    short_c[:d0 + 1] = False
    long_f = np.zeros(nf, dtype=bool)
    short_f = np.zeros(nf, dtype=bool)
    long_f[last] = long_c[di[last]]
    short_f[last] = short_c[di[last]]
    # the kernel trails with chand[j-1]; that must be the chandelier of the chart bar BEFORE fine bar j's chart bar
    prev = np.maximum(di - 1, 0)
    ch_l = np.asarray(feats["chandL"])[prev].astype(np.float64)
    ch_s = np.asarray(feats["chandS"])[prev].astype(np.float64)
    ch_l[di == 0] = NAN
    ch_s[di == 0] = NAN
    ch_l = np.concatenate([ch_l[1:], [NAN]])
    ch_s = np.concatenate([ch_s[1:], [NAN]])
    rec_f, _, _ = simulate_arrays(F["o"], F["h"], F["l"], F["c"], long_f, short_f,
                                  np.asarray(feats["slDistL"])[di], np.asarray(feats["slDistS"])[di], ch_l, ch_s,
                                  mgmt, cp, feats["mintick"],
                                  np.asarray(feats["trigCodeL"])[di], np.asarray(feats["trigCodeS"])[di],
                                  np.asarray(feats["scoreL"])[di], np.asarray(feats["scoreS"])[di])
    rec_c, _, _ = simulate_arrays(chart["o"], chart["h"], chart["l"], chart["c"], long_c, short_c,
                                  feats["slDistL"], feats["slDistS"], feats["chandL"], feats["chandS"], mgmt, cp,
                                  feats["mintick"], feats["trigCodeL"], feats["trigCodeS"],
                                  feats["scoreL"], feats["scoreS"])
    return rec_f, rec_c, F, d0
