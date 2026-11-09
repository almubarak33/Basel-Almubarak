#!/usr/bin/env python3
"""test_parity.py - differential reconciliation of the two independent ports of APEX_Focus_original.pine.

    engine_a.py   readable pure-Python reference
    engine_b.py   fast numpy / numba engine

Neither port is trusted: this test only proves that they AGREE.  Every disagreement has to be settled against
the Pine source (see the report that accompanies this file), never by copying one port into the other.

What is compared for every (dataset, Params) case
  * series    scoreL, scoreS, longSig, shortSig exactly; atr and htfTrend within 1e-9 relative with identical
              nan positions
  * extra     the inputs both engines hand to their simulators (slDistL/S, chandL/S, trigger names) and the core
              indicators (ema21/55/200, stDir, stLine, diP, diM, adx, rsi14) - captured from inside run(), so
              a divergence is caught even on bars where no trade happens to look at it
  * trades    field by field (ints / bools / strings / None exactly, floats within 1e-9)
  * open_trade, stats (ints exactly, floats within 1e-9)
plus four engine-level sections
  * errors    the script's runtime.error() input checks raise ValueError in both ports
  * edge      run() on charts of 1 .. 300 bars, on the script's "HTF not longer than the chart" fallback
              (L120), and on HTF histories that start late / end early / are too short for the EMA
  * synth     run() on synthetic integer-tick charts (exact ties, flat stretches, zero ATR, gaps) with random
              Params and random market descriptions - indicator corner cases real data rarely contains
  * fuzz      random hand-built simulate() scenarios (gaps through stops and targets, na chandelier, w1 + w2 = 1,
              w1 = 0, both signals on one bar, short TP3 below mintick, zero / na stop distance, negative
              prices, na prices, list / int inputs, custom trigger names) - branches real data never reaches

Datasets: every name returned by datasets.list_datasets(), full length (no slicing unless --max-bars is given;
with --max-bars N the LAST N chart bars are used for BOTH engines, the HTF bars stay complete).
Parameter matrix: the full matrix (FULL_VARIANTS, ~75 Params) on a representative subset (FULL_DATASETS) and
the CORE_VARIANTS (default, the 4 profiles, 2 loose-filter stress sets) on every other dataset.

Usage:  python3 test_parity.py [--jobs N] [--max-bars N] [--datasets a,b] [--variants x,y] [--all-full]
                               [--no-fuzz] [--fuzz N] [--synth N] [-v]
Exit status 0 = zero mismatches, 1 = at least one mismatch (or an engine raised).
"""
from __future__ import annotations

import argparse
import math
import os
import sys
import time
import traceback
from dataclasses import fields, replace
from multiprocessing import Pool

import numpy as np

import datasets as ds
import engine_a as A
import engine_b as B

TOL = 1e-9
NAN = float("nan")

# ───────────────────────────── parameter matrix ─────────────────────────────
LOOSE = dict(minScore=3, useTsm=False)          # many more trades -> stresses the trade state machine


def _variants() -> list[tuple[str, dict]]:
    v: list[tuple[str, dict]] = [("default", {})]
    # management profiles
    for prof in ("HP", "BAL", "RUN", "CUS"):
        v.append((f"profile={prof}", dict(profile=prof)))
    for trail in (True, False):
        for be in (True, False):
            v.append((f"CUS trail={int(trail)} be={int(be)}", dict(profile="CUS", cTrail=trail, cBe=be)))
    # custom weights: cW1 + cW2 = 100 (TP2 closes the trade), all-out at TP1, nothing at TP1, nothing at all
    v += [
        ("CUS w=60/40", dict(profile="CUS", cW1=60.0, cW2=40.0)),
        ("CUS w=60/40 trail", dict(profile="CUS", cW1=60.0, cW2=40.0, cTrail=True)),
        ("CUS w=100/0", dict(profile="CUS", cW1=100.0, cW2=0.0)),
        ("CUS w=0/100 trail", dict(profile="CUS", cW1=0.0, cW2=100.0, cTrail=True)),
        ("CUS w=0/0 trail nobe", dict(profile="CUS", cW1=0.0, cW2=0.0, cTrail=True, cBe=False)),
        ("CUS w=33.3/33.3", dict(profile="CUS", cW1=33.3, cW2=33.3)),
        ("CUS tp=0.5/1/1.5", dict(profile="CUS", cTp1=0.5, cTp2=1.0, cTp3=1.5)),
        ("CUS tp=0.2/0.4/0.6 trail", dict(profile="CUS", cTp1=0.2, cTp2=0.4, cTp3=0.6, cTrail=True)),
        ("CUS tp3=500 (short TP3 na)", dict(profile="CUS", cTp1=1.0, cTp2=2.0, cTp3=500.0)),
    ]
    # signal filters
    for ms in (7, 6, 5, 3, 0):
        v.append((f"minScore={ms}", dict(minScore=ms)))
    v.append(("useTsm=False", dict(useTsm=False)))
    v.append(("dirMode=Long only", dict(dirMode="Long only")))
    v.append(("dirMode=Short only", dict(dirMode="Short only")))
    v.append(("useBrk=False", dict(useBrk=False)))
    v.append(("useFlip=False", dict(useFlip=False)))
    v.append(("usePb=False", dict(usePb=False)))
    v.append(("only BRK", dict(useFlip=False, usePb=False)))
    v.append(("only FLIP", dict(useBrk=False, usePb=False)))
    v.append(("only PB", dict(useBrk=False, useFlip=False)))
    v.append(("no trigger", dict(useBrk=False, useFlip=False, usePb=False)))
    # cost / small-frame guard
    v.append(("smallGuard=False", dict(smallGuard=False)))
    v.append(("cgMaxPct=1", dict(cgMaxPct=1.0)))
    v.append(("cgMaxPct=25", dict(cgMaxPct=25.0)))
    v.append(("cost Custom 0", dict(costMode="Custom", costCustom=0.0)))
    v.append(("cost Custom 0.2", dict(costMode="Custom", costCustom=0.2)))
    v.append(("cost Custom 0.2 noGuard", dict(costMode="Custom", costCustom=0.2, smallGuard=False)))
    # numeric inputs (two values around each default, plus edge values)
    for key, vals in (("stFactor", (0.5, 2.0, 4.5)), ("stLen", (1, 7, 14, 21)), ("donLen", (5, 10, 55)),
                      ("swingLook", (2, 5, 30)), ("slBuf", (0.0, 0.6)), ("slMinAtr", (0.3, 1.5)),
                      ("slMaxAtr", (0.8, 2.0, 6.0)), ("chLen", (2, 10, 44)), ("chMult", (0.5, 1.5, 4.5)),
                      ("adxMin", (15.0, 35.0))):
        for x in vals:
            v.append((f"{key}={x}", {key: x}))
    # windows longer than the 250-bar warm-up: the na paths of ta.highest / ta.lowest / ta.atr reach live bars
    v.append(("swingLook=300 (na stop before bar 299)", dict(swingLook=300, **LOOSE)))
    v.append(("donLen=300 loose", dict(donLen=300, **LOOSE)))
    v.append(("stLen=300 loose (na ATR inside SuperTrend)", dict(stLen=300, **LOOSE)))
    v.append(("chLen=400 loose (na chandelier)", dict(chLen=400, profile="HP", **LOOSE)))
    # loose filters x management: thousands of trades through every management branch
    v.append(("loose", dict(**LOOSE)))
    v.append(("loose minScore=0", dict(minScore=0, useTsm=False)))
    for prof in ("HP", "BAL", "RUN"):
        v.append((f"loose {prof}", dict(profile=prof, **LOOSE)))
    v += [
        ("loose CUS trail be", dict(profile="CUS", cTrail=True, cBe=True, **LOOSE)),
        ("loose CUS trail nobe", dict(profile="CUS", cTrail=True, cBe=False, **LOOSE)),
        ("loose CUS w=60/40 trail", dict(profile="CUS", cW1=60.0, cW2=40.0, cTrail=True, **LOOSE)),
        ("loose CUS w=100/0", dict(profile="CUS", cW1=100.0, cW2=0.0, **LOOSE)),
        ("loose CUS w=0/0 trail", dict(profile="CUS", cW1=0.0, cW2=0.0, cTrail=True, **LOOSE)),
        ("loose CUS tp=0.2/0.4/0.6", dict(profile="CUS", cTp1=0.2, cTp2=0.4, cTp3=0.6, **LOOSE)),
        ("loose CUS tp3=500", dict(profile="CUS", cTp1=1.0, cTp2=2.0, cTp3=500.0, cTrail=True, **LOOSE)),
        ("loose tight stop", dict(slMinAtr=0.1, slMaxAtr=0.4, swingLook=2, slBuf=0.0, **LOOSE)),
        ("loose wide stop chLen=5", dict(slMinAtr=2.0, slMaxAtr=8.0, chLen=5, chMult=1.0, **LOOSE)),
        ("loose Long only RUN", dict(dirMode="Long only", profile="RUN", **LOOSE)),
        ("loose Short only HP", dict(dirMode="Short only", profile="HP", **LOOSE)),
        ("loose cost 0.5 noGuard", dict(costMode="Custom", costCustom=0.5, smallGuard=False, **LOOSE)),
    ]
    return v


FULL_VARIANTS = _variants()
CORE_LABELS = ("default", "profile=HP", "profile=BAL", "profile=RUN", "profile=CUS", "loose",
               "loose CUS trail nobe")
CORE_VARIANTS = [x for x in FULL_VARIANTS if x[0] in CORE_LABELS]

# Representative subset for the full matrix: every asset class, every timeframe, both HTF sources
# (real HTF file / resampled), hi-cost metals, crypto (Trend Runner by default), small frames (cost guard).
FULL_DATASETS = (
    "OANDA_XAUUSD_4h", "OANDA_XAUUSD_15m", "OANDA_XAGUSD_1h", "OANDA_XPTUSD_1D",      # metals
    "OANDA_WTICOUSD_4h", "YF_WTI_15m", "OANDA_NATGASUSD_1D",                           # energy
    "OANDA_EURUSD_1h", "OANDA_USDJPY_1D", "YF_GBPUSD_5m",                              # FX
    "OANDA_SPX500USD_15m", "OANDA_NAS100USD_4h", "TADAWUL_TASI_1D",                    # indices
    "BINANCE_BTCUSDT_4h", "BINANCE_BTCUSDT_15m", "BINANCE_ETHUSDT_1h", "BINANCE_BTCUSDT_5m",
    "BINANCEX_XRPUSDT_1D",                                                             # crypto
    "NASDAQ_AAPL_1D", "NASDAQ_NVDA_1h", "NASDAQ_AAPL_5m",                              # US stocks
    "TADAWUL_1120_1D", "TADAWUL_2222_1D",                                              # Saudi stocks
)


# ───────────────────────────── comparison helpers ─────────────────────────────
def _isnan(x) -> bool:
    return isinstance(x, float) and x != x


def feq(a, b, tol: float = TOL) -> bool:
    """floats within tol (relative, absolute below 1); nan only equals nan; inf only equals the same inf."""
    if a is None or b is None:
        return a is None and b is None
    a = float(a)
    b = float(b)
    if a != a or b != b:
        return a != a and b != b
    if a == b:
        return True
    if math.isinf(a) or math.isinf(b):
        return False
    return abs(a - b) <= tol * max(1.0, abs(a), abs(b))


def first_diff_exact(a: np.ndarray, b: np.ndarray):
    a = np.asarray(a)
    b = np.asarray(b)
    if a.shape != b.shape:
        return -1
    bad = np.flatnonzero(a != b)
    return int(bad[0]) if len(bad) else None


def first_diff_float(a: np.ndarray, b: np.ndarray, tol: float = TOL):
    """First index where two float series differ: nan positions must be identical, values within tol RELATIVE.
    Returns (index | None, max relative difference over the comparable values)."""
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    if a.shape != b.shape:
        return -1, NAN
    na_, nb_ = np.isnan(a), np.isnan(b)
    with np.errstate(invalid="ignore", divide="ignore"):
        scale = np.maximum(np.abs(a), np.abs(b))
        diff = np.abs(a - b)
        rel = np.where(scale > 0, diff / scale, 0.0)
    same = (a == b) | (na_ & nb_)
    rel = np.where(same, 0.0, rel)
    bad = (na_ != nb_) | (~same & ~(rel <= tol))
    idx = np.flatnonzero(bad)
    finite = rel[np.isfinite(rel)]
    return (int(idx[0]) if len(idx) else None), (float(finite.max()) if len(finite) else 0.0)


TRADE_KEYS = ("dir", "entry_bar", "exit_bar", "trig", "score", "entry", "sl0", "risk", "tp1", "tp2", "tp3",
              "hit1", "hit2", "hit3", "exit_px", "reason", "gross_R", "cost_R", "R")
OPEN_KEYS = ("dir", "entry_bar", "trig", "score", "entry", "sl0", "risk", "tp1", "tp2", "tp3",
             "hit1", "hit2", "hit3")
_EXACT = {"dir": int, "entry_bar": int, "exit_bar": int, "score": int, "trig": str, "reason": str,
          "hit1": bool, "hit2": bool, "hit3": bool}
STAT_INT = ("n", "tp1", "tp2", "tp3", "fullSl", "win", "nL", "nS")
STAT_FLOAT = ("gross", "loss", "net", "peak", "maxDd", "costR", "netL", "netS")


def diff_trade(ta: dict, tb: dict, keys) -> list[str]:
    """Names of the fields in which two trade dicts differ (also key set / type differences)."""
    bad = []
    if tuple(ta.keys()) != tuple(keys):
        bad.append(f"<keys A={list(ta.keys())}>")
    if tuple(tb.keys()) != tuple(keys):
        bad.append(f"<keys B={list(tb.keys())}>")
    for k in keys:
        if k not in ta or k not in tb:
            continue
        x, y = ta[k], tb[k]
        if k in _EXACT:
            typ = _EXACT[k]
            # bool is an int subclass: demand the exact python type so 1.0 / np.bool_ / "1" never pass silently
            if type(x) is not typ or type(y) is not typ or x != y:
                bad.append(k)
        elif k == "tp3":
            if (x is None) != (y is None) or (x is not None and not feq(x, y)):
                bad.append(k)
            elif x is not None and (type(x) is not float or type(y) is not float):
                bad.append(k + "<type>")
        else:
            if type(x) is not float or type(y) is not float or not feq(x, y):
                bad.append(k)
    return bad


def compare_results(ra: dict, rb: dict) -> list[dict]:
    """-> list of mismatch records {"what", "bar", "msg"} (empty when the two results agree)."""
    out = []
    # ---- trades
    ta, tb = ra["trades"], rb["trades"]
    for i in range(min(len(ta), len(tb))):
        bad = diff_trade(ta[i], tb[i], TRADE_KEYS)
        if bad:
            bar = min(ta[i].get("entry_bar", 0), tb[i].get("entry_bar", 0)) if "entry_bar" in bad or "dir" in bad \
                else min(ta[i].get("exit_bar", 0), tb[i].get("exit_bar", 0))
            out.append({"what": "trade", "bar": int(bar),
                        "msg": f"trade #{i} differs in {bad}\n      A: {ta[i]}\n      B: {tb[i]}"})
            break
    else:
        if len(ta) != len(tb):
            longer, tag = (ta, "A") if len(ta) > len(tb) else (tb, "B")
            extra = longer[min(len(ta), len(tb))]
            out.append({"what": "trade", "bar": int(extra["entry_bar"]),
                        "msg": f"trade count A={len(ta)} B={len(tb)}; first extra trade (engine {tag}): {extra}"})
    # ---- open trade
    oa, ob = ra["open_trade"], rb["open_trade"]
    if (oa is None) != (ob is None):
        out.append({"what": "open_trade", "bar": int((oa or ob)["entry_bar"]),
                    "msg": f"open_trade A={oa} B={ob}"})
    elif oa is not None:
        bad = diff_trade(oa, ob, OPEN_KEYS)
        if bad:
            out.append({"what": "open_trade", "bar": int(min(oa["entry_bar"], ob["entry_bar"])),
                        "msg": f"open_trade differs in {bad}\n      A: {oa}\n      B: {ob}"})
    # ---- stats
    sa, sb = ra["stats"], rb["stats"]
    bad = []
    if tuple(sa.keys()) != tuple(sb.keys()) or set(sa.keys()) != set(STAT_INT + STAT_FLOAT):
        bad.append(f"<keys A={list(sa.keys())} B={list(sb.keys())}>")
    for k in STAT_INT:
        if k in sa and k in sb and (type(sa[k]) is not int or type(sb[k]) is not int or sa[k] != sb[k]):
            bad.append(k)
    for k in STAT_FLOAT:
        if k in sa and k in sb and (type(sa[k]) is not float or type(sb[k]) is not float or not feq(sa[k], sb[k])):
            bad.append(k)
    if bad:
        out.append({"what": "stats", "bar": None, "msg": f"stats differ in {bad}\n      A: {sa}\n      B: {sb}"})
    return out


def compare_series(sa: dict, sb: dict) -> tuple[list[dict], float]:
    out = []
    maxrel = 0.0
    if set(sa.keys()) != set(sb.keys()):
        out.append({"what": "series", "bar": None, "msg": f"series keys A={sorted(sa)} B={sorted(sb)}"})
    for k, kind in (("scoreL", "i"), ("scoreS", "i"), ("longSig", "b"), ("shortSig", "b")):
        xa, xb = np.asarray(sa[k]), np.asarray(sb[k])
        if xa.dtype.kind != kind or xb.dtype.kind != kind:
            out.append({"what": "series", "bar": None, "msg": f"series[{k}] dtype A={xa.dtype} B={xb.dtype}"})
        i = first_diff_exact(xa, xb)
        if i is not None:
            n_bad = int((xa != xb).sum()) if xa.shape == xb.shape else -1
            out.append({"what": f"series.{k}", "bar": i,
                        "msg": f"series[{k}] first differs at bar {i}: A={xa[i] if i >= 0 else xa.shape} "
                               f"B={xb[i] if i >= 0 else xb.shape} ({n_bad} bars differ)"})
    for k in ("atr", "htfTrend"):
        i, mr = first_diff_float(sa[k], sb[k])
        maxrel = max(maxrel, mr if mr == mr else 0.0)
        if i is not None:
            xa, xb = np.asarray(sa[k]), np.asarray(sb[k])
            out.append({"what": f"series.{k}", "bar": i,
                        "msg": f"series[{k}] first differs at bar {i}: A={xa[i] if i >= 0 else xa.shape!r} "
                               f"B={xb[i] if i >= 0 else xb.shape!r}"})
    return out, maxrel


# engine_a.compute_series key -> engine_b.features key, for the intermediate ("extra") comparison
EXTRA_FLOAT = (("slDistL", "slDistL"), ("slDistS", "slDistS"), ("chandL", "chandL"), ("chandS", "chandS"),
               ("ema21", "ema21"), ("ema55", "ema55"), ("ema200", "ema200"), ("stLine", "stLine"),
               ("stDir", "stDir"), ("diP", "diP"), ("diM", "diM"), ("adx", "adx"), ("rsi14", "rsi14"))


def compare_extra(ca: dict, cb: dict) -> tuple[list[dict], float]:
    out = []
    maxrel = 0.0
    for ka, kb in EXTRA_FLOAT:
        i, mr = first_diff_float(ca[ka], cb[kb])
        maxrel = max(maxrel, mr if mr == mr else 0.0)
        if i is not None:
            out.append({"what": f"extra.{ka}", "bar": i,
                        "msg": f"intermediate {ka} first differs at bar {i}: A={np.asarray(ca[ka])[i]!r} "
                               f"B={np.asarray(cb[kb])[i]!r}"})
    for side in ("L", "S"):
        na_ = np.asarray(ca["trigName" + side], dtype=object)
        nb_ = np.asarray(B.TRIG_NAMES, dtype=object)[np.asarray(cb["trigCode" + side])]
        i = first_diff_exact(na_, nb_)
        if i is not None:
            out.append({"what": f"extra.trigName{side}", "bar": i,
                        "msg": f"trigName{side} first differs at bar {i}: A={na_[i]} B={nb_[i]}"})
    if not feq(ca["costPct"], cb["costPct"]):
        out.append({"what": "extra.costPct", "bar": None, "msg": f"costPct A={ca['costPct']} B={cb['costPct']}"})
    return out, maxrel


def dump_bar(ca: dict | None, cb: dict | None, chart: dict, bar: int) -> str:
    """Both engines' intermediate values around `bar` (the first diverging bar)."""
    if ca is None or cb is None or bar is None or bar < 0:
        return ""
    n = len(chart["c"])
    rows = []
    bars = [b for b in (bar - 2, bar - 1, bar) if 0 <= b < n]
    rows.append("      bar            " + "".join(f"{b:>24d}" for b in bars))
    for k in ("o", "h", "l", "c"):
        rows.append(f"      {k:14s} " + "".join(f"{float(chart[k][b]):>24.12g}" for b in bars))
    pairs = (("atr", "atr"), ("htfTrend", "htfTrend"), ("ema21", "ema21"), ("ema55", "ema55"), ("ema200", "ema200"),
             ("stLine", "stLine"), ("stDir", "stDir"), ("diP", "diP"), ("diM", "diM"), ("adx", "adx"),
             ("rsi14", "rsi14"), ("scoreL", "scoreL"), ("scoreS", "scoreS"), ("longSig", "longSig"),
             ("shortSig", "shortSig"), ("slDistL", "slDistL"), ("slDistS", "slDistS"),
             ("chandL", "chandL"), ("chandS", "chandS"))
    for ka, kb in pairs:
        va = [np.asarray(ca[ka])[b] for b in bars]
        vb = [np.asarray(cb[kb])[b] for b in bars]
        flag = "" if all((x == y) or (x != x and y != y) for x, y in zip(va, vb)) else "   <-- differs"
        rows.append(f"      A.{ka:12s} " + "".join(f"{x!s:>24.24s}" for x in va) + flag)
        rows.append(f"      B.{kb:12s} " + "".join(f"{x!s:>24.24s}" for x in vb))
    for side in ("L", "S"):
        va = [str(ca["trigName" + side][b]) for b in bars]
        vb = [B.TRIG_NAMES[int(cb["trigCode" + side][b])] for b in bars]
        rows.append(f"      A.trigName{side}    " + "".join(f"{x:>24s}" for x in va) + ("" if va == vb else "   <-- differs"))
        rows.append(f"      B.trigName{side}    " + "".join(f"{x:>24s}" for x in vb))
    for kb in ("tsm", "donHi", "donLo", "brkUp", "brkDn", "flipUp", "flipDn", "pbUp", "pbDn", "cgOkL", "cgOkS"):
        rows.append(f"      B.{kb:12s} " + "".join(f"{np.asarray(cb[kb])[b]!s:>24.24s}" for b in bars))
    return "\n".join(rows)


# ───────────────────────────── per-dataset worker ─────────────────────────────
_CAP: dict = {}
_orig_a_series = A.compute_series
_orig_b_features = B.features


def _cap_a(*args, **kw):
    out = _orig_a_series(*args, **kw)
    _CAP["a"] = out
    return out


def _cap_b(*args, **kw):
    out = _orig_b_features(*args, **kw)
    _CAP["b"] = out
    return out


def _coverage(cov: dict, res: dict, chart: dict) -> None:
    """Which branches of the trade model the case went through (from engine A's trades)."""
    o = chart["o"]
    prev_exit = -1
    prev_reason = ""
    for t in res["trades"]:
        cov["trades"] = cov.get("trades", 0) + 1
        key = "reason:" + t["reason"]
        cov[key] = cov.get(key, 0) + 1
        hits = "hits:" + "".join(str(int(t[h])) for h in ("hit1", "hit2", "hit3"))
        cov[hits] = cov.get(hits, 0) + 1
        if t["tp3"] is None:
            cov["tp3 na"] = cov.get("tp3 na", 0) + 1
        if t["reason"] in ("SL", "Remaining SL", "BE/Trail") and t["exit_px"] == o[t["exit_bar"]]:
            cov["stop filled at open (gap)"] = cov.get("stop filled at open (gap)", 0) + 1
        if t["reason"] == "SL" and t["hit1"]:
            cov["SL with hit1 (w1=0)"] = cov.get("SL with hit1 (w1=0)", 0) + 1
        if t["entry_bar"] == prev_exit and prev_reason != "Reverse":
            cov["re-entry on exit bar"] = cov.get("re-entry on exit bar", 0) + 1
        if t["R"] != t["R"]:
            cov["nan R"] = cov.get("nan R", 0) + 1
        prev_exit, prev_reason = t["exit_bar"], t["reason"]
    if res["open_trade"] is not None:
        cov["open at end"] = cov.get("open at end", 0) + 1


def _same(x, y) -> bool:
    if type(x) is not type(y):
        return False
    if isinstance(x, float):
        return x == y or (x != x and y != y)
    if isinstance(x, dict):
        return list(x.keys()) == list(y.keys()) and all(_same(x[k], y[k]) for k in x)
    if isinstance(x, list):
        return len(x) == len(y) and all(_same(u, v) for u, v in zip(x, y))
    return x == y


def results_identical(ra: dict, rb: dict) -> bool:
    """Bit-for-bit equality of trades / open_trade / stats (nan equals nan)."""
    return _same(ra["trades"], rb["trades"]) and _same(ra["open_trade"], rb["open_trade"]) \
        and _same(ra["stats"], rb["stats"])


def compare_case(tag: str, chart: dict, htf, market, kw: dict, verbose: bool = False) -> dict:
    """Run both engines on one (chart, htf, market, Params) case and compare everything.
    -> {"message": None | str, "ra", "maxrel", "ta", "tb", "identical"}"""
    A.compute_series = _cap_a
    B.features = _cap_b
    _CAP.clear()
    res = {"message": None, "ra": None, "maxrel": 0.0, "ta": 0.0, "tb": 0.0, "identical": False}
    ea = eb = None
    ra = rb = None
    t0 = time.perf_counter()
    try:
        ra = A.run(chart, htf, A.Params(**kw), market)
    except Exception as e:
        ea = e
    t1 = time.perf_counter()
    try:
        rb = B.run(chart, htf, B.Params(**kw), market)
    except Exception as e:
        eb = e
    t2 = time.perf_counter()
    res["ta"], res["tb"] = t1 - t0, t2 - t1
    if ea is not None or eb is not None:
        res["message"] = (f"[{tag}] an engine raised: A: {type(ea).__name__ if ea else 'ok'}"
                          f"{(' ' + str(ea)) if ea else ''} | B: {type(eb).__name__ if eb else 'ok'}"
                          f"{(' ' + str(eb)) if eb else ''}")
        return res
    ca, cb = _CAP.get("a"), _CAP.get("b")
    mism, mr1 = compare_series(ra["series"], rb["series"])
    mr2 = 0.0
    if ca is not None and cb is not None:
        m2, mr2 = compare_extra(ca, cb)
        mism += m2
    else:
        mism.append({"what": "extra", "bar": None, "msg": "could not capture the engines' intermediates"})
    mism += compare_results(ra, rb)
    res["ra"] = ra
    res["maxrel"] = max(mr1, mr2)
    res["identical"] = not mism and mr1 == 0.0 and mr2 == 0.0 and results_identical(ra, rb)
    if mism:
        bars = [m["bar"] for m in mism if m["bar"] is not None and m["bar"] >= 0]
        first = min(bars) if bars else None
        lines = [f"[{tag}] {len(mism)} mismatch(es); first diverging bar: {first}"]
        for m in mism[: (None if verbose else 6)]:
            lines.append(f"   - {m['what']}: {m['msg']}")
        if first is not None:
            lines.append(f"   intermediates around bar {first} (Params: {kw or 'default'}):")
            lines.append(dump_bar(ca, cb, chart, first))
        res["message"] = "\n".join(lines)
    return res


def _new_out(name: str = "") -> dict:
    return {"name": name, "cases": 0, "failed": 0, "messages": [], "cov": {}, "ta": 0.0, "tb": 0.0,
            "maxrel": 0.0, "bars": 0, "trades": 0, "bit_identical": 0}


def _book(out: dict, r: dict, chart: dict) -> None:
    out["cases"] += 1
    out["ta"] += r["ta"]
    out["tb"] += r["tb"]
    out["maxrel"] = max(out["maxrel"], r["maxrel"])
    if r["identical"]:
        out["bit_identical"] += 1
    if r["ra"] is not None:
        out["trades"] += len(r["ra"]["trades"])
        _coverage(out["cov"], r["ra"], chart)
    if r["message"] is not None:
        out["failed"] += 1
        out["messages"].append(r["message"])


def run_dataset(job: tuple) -> dict:
    name, variant_labels, max_bars, verbose = job
    out = _new_out(name)
    try:
        chart = ds.load(name)
        market = ds.market_of(name, chart)
        htf, _src = ds.htf_bars(name, chart)
        if max_bars and len(chart["t"]) > max_bars:
            chart = {k: v[-max_bars:] for k, v in chart.items()}          # same slice for both engines
            market = replace(market, mintick=ds._mintick(chart["c"]))
        out["bars"] = len(chart["t"])
        wanted = dict(FULL_VARIANTS)
        B.run(chart, htf, B.Params(), market)                             # JIT warm-up outside the timing
        for label in variant_labels:
            _book(out, compare_case(f"{name} | {label}", chart, htf, market, wanted[label], verbose), chart)
    except Exception:
        out["failed"] += 1
        out["messages"].append(f"[{name}] worker crashed:\n{traceback.format_exc()}")
    return out


# ───────────────────────────── engine-level sections ─────────────────────────────
def check_errors() -> tuple[int, list[str]]:
    """The script's runtime.error() input checks (Pine L103-L110) and misspelt option strings -> ValueError in
    both ports; valid boundary inputs must not raise in either."""
    name = "OANDA_XAUUSD_4h" if "OANDA_XAUUSD_4h" in ds.list_datasets() else ds.list_datasets()[0]
    chart = ds.load(name)
    chart = {k: v[:600] for k, v in chart.items()}
    market = ds.market_of(name, chart)
    htf, _ = ds.htf_bars(name, chart)
    cases = [
        ("slMinAtr > slMaxAtr", dict(slMinAtr=2.0, slMaxAtr=1.0), True),
        ("slMinAtr == slMaxAtr", dict(slMinAtr=1.0, slMaxAtr=1.0), False),
        ("CUS TP1 >= TP2", dict(profile="CUS", cTp1=2.0, cTp2=2.0, cTp3=3.0), True),
        ("CUS TP2 >= TP3", dict(profile="CUS", cTp1=1.0, cTp2=3.0, cTp3=3.0), True),
        ("CUS weights > 100", dict(profile="CUS", cW1=60.0, cW2=40.5), True),
        ("CUS weights == 100", dict(profile="CUS", cW1=60.0, cW2=40.0), False),
        ("bad custom inputs ignored outside CUS", dict(profile="HP", cTp1=5.0, cTp2=2.0, cW1=90.0, cW2=90.0), False),
        ("unknown profile", dict(profile="Balanced"), True),
        ("unknown dirMode", dict(dirMode="Long Only"), True),
        ("unknown costMode", dict(costMode="custom"), True),
    ]
    msgs = []
    for label, kw, should_raise in cases:
        got = []
        for eng in (A, B):
            try:
                eng.run(chart, htf, eng.Params(**kw), market)
                got.append(False)
            except ValueError:
                got.append(True)
            except Exception as e:                               # any other exception type is a mismatch
                got.append(f"{type(e).__name__}: {e}")
        if got != [should_raise, should_raise]:
            msgs.append(f"[errors | {label}] expected raise={should_raise}; A raised={got[0]} B raised={got[1]}")
    return len(cases), msgs


def run_edge(job: tuple) -> dict:
    """run() on degenerate inputs: very short charts, the L120 fallback (HTF not longer than the chart
    timeframe -> the chart's own previous bar, EMA length from the chart timeframe) and incomplete HTF history."""
    (verbose,) = job
    out = _new_out("edge")
    try:
        avail = ds.list_datasets()
        picks = [n for n in ("OANDA_XAUUSD_4h", "NASDAQ_AAPL_1D", "BINANCE_BTCUSDT_15m") if n in avail] or avail[:3]
        loose = dict(LOOSE)
        for name in picks:
            chart = ds.load(name)
            market = ds.market_of(name, chart)
            htf, _ = ds.htf_bars(name, chart)
            chart = {k: v[-3000:] for k, v in chart.items()}
            for n in (1, 2, 3, 5, 14, 15, 28, 29, 60, 250, 251, 252, 300):       # short charts
                sub = {k: v[:n] for k, v in chart.items()}
                for lab, kw in (("default", {}), ("loose", loose)):
                    _book(out, compare_case(f"edge {name} first {n} bars | {lab}", sub, htf, market, kw, verbose), sub)
            # L120: requested HTF not longer than the chart timeframe -> timeframe.period itself
            for lab, hs, h in (("htf == tf, htf=None", market.tf_seconds, None),
                               ("htf == tf, htf given (must be ignored)", market.tf_seconds, htf),
                               ("htf < tf", max(1, market.tf_seconds // 4), None)):
                mk = replace(market, htf_seconds=hs)
                for vl, kw in (("default", {}), ("loose", loose), ("loose BAL", dict(profile="BAL", **loose))):
                    _book(out, compare_case(f"edge {name} {lab} | {vl}", chart, h, mk, kw, verbose), chart)
            # the same fallback on a daily clock (EMA 21) and an intraday clock (EMA 50)
            for tf_s in (86400, 3600):
                mk = replace(market, tf_seconds=tf_s, htf_seconds=tf_s)
                _book(out, compare_case(f"edge {name} fallback tf={tf_s} | loose", chart, None, mk, loose, verbose), chart)
            # incomplete higher-timeframe history
            m = len(htf["t"])
            for lab, sl in (("HTF last 40%", slice(int(m * 0.6), None)), ("HTF first 60%", slice(0, int(m * 0.6))),
                            ("HTF last 30 bars", slice(m - 30, None)), ("HTF last 1 bar", slice(m - 1, None)),
                            ("HTF empty", slice(0, 0))):
                sub_h = {k: v[sl] for k, v in htf.items()}
                _book(out, compare_case(f"edge {name} {lab} | loose", chart, sub_h, market, loose, verbose), chart)
    except Exception:
        out["failed"] += 1
        out["messages"].append(f"[edge] worker crashed:\n{traceback.format_exc()}")
    return out


def _synth_case(rng: np.random.Generator):
    """A synthetic chart on an integer tick grid (many exact ties), with flat stretches (zero true range, ATR
    decaying to exactly 0 when the chart starts flat), trending regimes and occasional gaps."""
    n = int(rng.integers(260, 1100))
    pre = int(rng.choice([0, 0, 400]))                         # extra history only the HTF sees
    total = n + pre
    tick = float(rng.choice([1.0, 0.25, 0.01, 1e-5]))
    level = int(rng.choice([40, 400, 30000]))
    step_max = int(rng.choice([1, 2, 6, 40]))
    flat_p = float(rng.choice([0.0, 0.002, 0.02]))
    gap_p = float(rng.choice([0.0, 0.02, 0.3]))
    o = np.empty(total)
    h = np.empty(total)
    l = np.empty(total)
    c = np.empty(total)
    px = level
    drift = 0.0
    flat_left = int(rng.choice([0, 0, 0, 30, 320])) + (pre if rng.random() < 0.2 else 0)
    for i in range(total):
        if rng.random() < 0.01:
            drift = float(rng.choice([-0.6, -0.25, 0.0, 0.25, 0.6])) * step_max
        if flat_left == 0 and rng.random() < flat_p:
            flat_left = int(rng.integers(3, 80))
        if flat_left > 0:
            flat_left -= 1
            op = cl = hi = lo = px
        else:
            op = px + (int(rng.integers(-4 * step_max, 4 * step_max + 1)) if rng.random() < gap_p else 0)
            cl = op + int(round(rng.normal(drift, step_max)))
            hi = max(op, cl) + int(rng.integers(0, step_max + 1))
            lo = min(op, cl) - int(rng.integers(0, step_max + 1))
        lo_floor = 1
        op, cl, hi, lo = max(op, lo_floor), max(cl, lo_floor), max(hi, lo_floor), max(lo, lo_floor)
        o[i], c[i], h[i], l[i] = op * tick, cl * tick, max(hi, op, cl) * tick, min(lo, op, cl) * tick
        px = cl
    tf_s = int(rng.choice([300, 900, 3600, 14400, 86400]))
    t = 1_600_000_000 // tf_s * tf_s + tf_s * np.arange(total, dtype=np.int64)
    full = {"t": t, "o": o, "h": h, "l": l, "c": c, "v": np.ones(total)}
    chart = {k: v[pre:] for k, v in full.items()}
    mode = int(rng.integers(0, 6))
    htf_s = ds.auto_htf_seconds(tf_s)
    if mode == 0:                                              # L120 fallback
        htf_s, htf = tf_s, None
    else:
        htf = ds.resample_by_key(full, [int(x) // htf_s for x in full["t"]])
        if mode == 1:                                          # HTF history starts after the chart
            cut = int(len(htf["t"]) * rng.uniform(0.1, 0.6))
            htf = {k: v[cut:] for k, v in htf.items()}
    market = ds.Market(name="SYNTH", exchange="SYNTH", ticker=str(rng.choice(["SYNUSD", "XAGSYN", "XPTSYN", "BTCSYN"])),
                       sym_type=str(rng.choice(["crypto", "forex", "cfd", "stock"])), interval="synth",
                       tf_seconds=tf_s, htf_seconds=int(htf_s), mintick=tick)
    label, kw = FULL_VARIANTS[int(rng.integers(0, len(FULL_VARIANTS)))]
    kw = dict(kw)
    if rng.random() < 0.75:                                    # mostly loose filters so trades actually happen
        kw.update(minScore=int(rng.integers(0, 6)), useTsm=bool(rng.random() < 0.3))
        label += f" + minScore={kw['minScore']} useTsm={kw['useTsm']}"
    return chart, htf, market, kw, f"tf={tf_s} htf_mode={mode} tick={tick} {market.sym_type} {market.ticker} | {label}"


def run_synth(job: tuple) -> dict:
    seed, count, verbose = job
    rng = np.random.default_rng(seed)
    out = _new_out("synth")
    try:
        for k in range(count):
            chart, htf, market, kw, label = _synth_case(rng)
            _book(out, compare_case(f"synth seed={seed} #{k} {label}", chart, htf, market, kw, verbose), chart)
    except Exception:
        out["failed"] += 1
        out["messages"].append(f"[synth seed={seed}] worker crashed:\n{traceback.format_exc()}")
    return out


def _fuzz_scenario(rng: np.random.Generator) -> tuple[dict, str]:
    """One hand-built simulate() scenario.  `flavour` adds inputs the script itself can never produce (zero / na
    stop distance, negative or na prices): there the two ports must still agree on the Pine na / IEEE rules."""
    flavour = str(rng.choice(["plain"] * 12 + ["zero-dist", "na-dist", "negative", "na-price", "lists"]))
    n = int(rng.integers(30, 160))
    base = float(rng.choice([0.03, 1.0, 50.0, 2000.0, 60000.0]))
    vol = base * float(rng.choice([0.002, 0.01, 0.05]))
    gap_p = float(rng.choice([0.0, 0.1, 0.5]))
    grid = float(rng.choice([0.0, 0.0, vol / 4]))               # price grid -> exact ties with stops / targets
    c = np.empty(n)
    o = np.empty(n)
    h = np.empty(n)
    l = np.empty(n)
    px = base
    floor = base * 1e-3
    for i in range(n):
        op = px + (rng.normal(0, 3 * vol) if rng.random() < gap_p else 0.0)
        cl = op + rng.normal(0, vol)
        hi = max(op, cl) + abs(rng.normal(0, 0.7 * vol))
        lo = min(op, cl) - abs(rng.normal(0, 0.7 * vol))
        if grid:
            op, cl, hi, lo = (round(x / grid) * grid for x in (op, cl, hi, lo))
        op, cl, hi, lo = max(op, floor), max(cl, floor), max(hi, floor), max(lo, floor)
        o[i], c[i], h[i], l[i] = op, cl, max(hi, op, cl), min(lo, op, cl)
        px = cl
    if flavour == "negative":                                   # prices crossing zero (e.g. WTI in April 2020)
        shift = base * float(rng.choice([1.0, 1.5]))
        o, h, l, c = o - shift, h - shift, l - shift, c - shift
    sig_p = float(rng.choice([0.03, 0.15, 0.5]))
    long_sig = rng.random(n) < sig_p
    short_sig = rng.random(n) < sig_p
    if rng.random() < 0.3:                                      # both signals on the same bars
        short_sig = short_sig | (long_sig & (rng.random(n) < 0.5))
    dist_scale = vol * float(rng.choice([0.3, 1.0, 3.0, 12.0]))
    sl_l = dist_scale * rng.uniform(0.5, 1.5, n)
    sl_s = dist_scale * rng.uniform(0.5, 1.5, n)
    if grid:                                                    # stops / targets exactly on the price grid
        sl_l = np.maximum(np.round(sl_l / grid), 1.0) * grid
        sl_s = np.maximum(np.round(sl_s / grid), 1.0) * grid
    if flavour == "na-dist":                                    # na stop distance (math.min / max propagate na)
        sl_l[rng.random(n) < 0.3] = NAN
        sl_s[rng.random(n) < 0.3] = NAN
    if flavour == "zero-dist":                                  # risk == 0: IEEE division, never an exception
        sl_l[rng.random(n) < 0.3] = 0.0
        sl_s[rng.random(n) < 0.3] = 0.0
    hh = np.maximum.accumulate(h) if rng.random() < 0.3 else h
    ll = np.minimum.accumulate(l) if rng.random() < 0.3 else l
    ch_mult = float(rng.choice([0.2, 1.0, 3.0]))
    chand_l = hh - ch_mult * vol * rng.uniform(0.5, 1.5, n)
    chand_s = ll + ch_mult * vol * rng.uniform(0.5, 1.5, n)
    nan_p = float(rng.choice([0.0, 0.0, 0.2, 1.0]))
    chand_l[rng.random(n) < nan_p] = NAN
    chand_s[rng.random(n) < nan_p] = NAN
    if flavour == "na-price":                                   # every comparison with na is false
        for arr in (o, h, l, c):
            arr[rng.random(n) < 0.05] = NAN
    kind = int(rng.integers(0, 8))
    if kind == 0:
        mg = dict(k1=0.3, k2=1.5, k3=4.0, w1=0.50, w2=0.25, trailOn=True, trailFrom=1, beOn=True)       # HP
    elif kind == 1:
        mg = dict(k1=1.0, k2=2.0, k3=3.0, w1=0.40, w2=0.30, trailOn=False, trailFrom=1, beOn=True)      # BAL
    elif kind == 2:
        mg = dict(k1=1.0, k2=2.0, k3=8.0, w1=0.33, w2=0.33, trailOn=True, trailFrom=2, beOn=False)      # RUN
    else:
        k1 = float(rng.choice([0.1, 0.3, 0.5, 1.0]))
        k2 = k1 + float(rng.choice([0.1, 0.5, 1.0]))
        k3 = k2 + float(rng.choice([0.1, 1.0, 5.0, 400.0]))
        w1, w2 = [(0.4, 0.3), (0.6, 0.4), (1.0, 0.0), (0.0, 1.0), (0.0, 0.0), (0.5, 0.5), (0.333, 0.333),
                  (0.7, 0.3), (0.1, 0.9), (0.25, 0.0), (0.9, 0.1), (1e-10, 0.5)][int(rng.integers(0, 12))]
        mg = dict(k1=k1, k2=k2, k3=k3, w1=w1, w2=w2, trailOn=bool(rng.random() < 0.6),
                  trailFrom=int(rng.choice([1, 2])), beOn=bool(rng.random() < 0.5))
    names = np.array(["BRK", "FLIP", "PB"] + (["RETEST", "x"] if rng.random() < 0.15 else []), dtype=object)
    use_names = rng.random() < 0.7
    sc = dict(
        o=o, h=h, l=l, c=c, longSig=long_sig, shortSig=short_sig, slDistL=sl_l, slDistS=sl_s,
        chandL=chand_l, chandS=chand_s, mgmt=mg, costPct=float(rng.choice([0.0, 0.03, 0.1, 0.5])),
        mintick=float(rng.choice([0.01, 1e-5, 1.0])),
        trigL=names[rng.integers(0, len(names), n)] if use_names else None,
        trigS=names[rng.integers(0, len(names), n)] if use_names else None,
        scoreL=rng.integers(0, 8, n) if use_names else None,
        scoreS=rng.integers(0, 8, n) if use_names else None)
    if flavour == "lists":                                      # plain Python lists / 0-1 ints instead of arrays
        for k in ("o", "h", "l", "c", "slDistL", "slDistS", "chandL", "chandS"):
            sc[k] = sc[k].tolist()
        sc["longSig"] = sc["longSig"].astype(np.int8)
        sc["shortSig"] = sc["shortSig"].tolist()
        for k in ("trigL", "trigS", "scoreL", "scoreS"):
            if sc[k] is not None:
                sc[k] = sc[k].tolist()
    return sc, flavour


def run_fuzz(job: tuple) -> dict:
    seed, count = job
    rng = np.random.default_rng(seed)
    out = {"cases": 0, "failed": 0, "messages": [], "cov": {}, "trades": 0, "flavours": {}}
    for k in range(count):
        sc, flavour = _fuzz_scenario(rng)
        out["cases"] += 1
        out["flavours"][flavour] = out["flavours"].get(flavour, 0) + 1
        try:
            ra = A.simulate(**sc)
            rb = B.simulate(**sc)
        except Exception:
            out["failed"] += 1
            out["messages"].append(f"[fuzz seed={seed} #{k} {flavour}] an engine raised:\n{traceback.format_exc()}")
            continue
        mism = compare_results(ra, rb)
        out["trades"] += len(ra["trades"])
        _coverage(out["cov"], ra, sc)
        if mism:
            out["failed"] += 1
            if len(out["messages"]) < 5:
                lines = [f"[fuzz seed={seed} #{k} {flavour}] mgmt={sc['mgmt']} costPct={sc['costPct']} "
                         f"mintick={sc['mintick']}"]
                for m in mism[:4]:
                    lines.append(f"   - {m['what']} (bar {m['bar']}): {m['msg']}")
                    b = m["bar"]
                    if b is not None:
                        for j in range(max(0, b - 1), min(len(sc["c"]), b + 1)):
                            lines.append(f"       bar {j}: o={sc['o'][j]!r} h={sc['h'][j]!r} l={sc['l'][j]!r} "
                                         f"c={sc['c'][j]!r} L={sc['longSig'][j]} S={sc['shortSig'][j]} "
                                         f"slL={sc['slDistL'][j]!r} slS={sc['slDistS'][j]!r} "
                                         f"chL={sc['chandL'][j]!r} chS={sc['chandS'][j]!r}")
                out["messages"].append("\n".join(lines))
    return out


# ───────────────────────────── main ─────────────────────────────
def _merge(dicts) -> dict:
    tot: dict = {}
    for d in dicts:
        for k, v in d.items():
            tot[k] = tot.get(k, 0) + v
    return tot


def _fmt(c: dict) -> str:
    return "  ".join(f"{k}={c[k]}" for k in sorted(c)) or "-"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 1)
    ap.add_argument("--max-bars", type=int, default=0, help="use only the last N chart bars (both engines)")
    ap.add_argument("--datasets", default="", help="comma separated dataset names (default: all)")
    ap.add_argument("--variants", default="", help="comma separated variant labels (default: matrix as documented)")
    ap.add_argument("--all-full", action="store_true", help="full parameter matrix on every dataset (slow)")
    ap.add_argument("--no-fuzz", action="store_true", help="skip the edge / synth / fuzz sections")
    ap.add_argument("--fuzz", type=int, default=6000, help="number of random simulate() scenarios")
    ap.add_argument("--synth", type=int, default=800, help="number of synthetic run() cases")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    t_start = time.perf_counter()
    labels = [x[0] for x in FULL_VARIANTS]
    assert len(set(labels)) == len(labels), "duplicate variant label"
    # the two Params dataclasses must expose the same inputs with the same defaults (= Pine input defaults)
    pa = [(f.name, f.default) for f in fields(A.Params)]
    pb = [(f.name, f.default) for f in fields(B.Params)]
    param_msgs = [] if pa == pb else [f"[Params] field/default mismatch:\n   A: {pa}\n   B: {pb}"]

    names = ds.list_datasets()
    if args.datasets:
        names = [n for n in args.datasets.split(",") if n]
    full_set = set(names) if args.all_full else {n for n in FULL_DATASETS if n in names}
    core_labels = [x[0] for x in CORE_VARIANTS]
    jobs = []
    for n in names:
        if args.variants:
            lab = [x for x in args.variants.split(",") if x]
        else:
            lab = labels if n in full_set else core_labels
        jobs.append((n, lab, args.max_bars, args.verbose))
    # biggest jobs first so the pool stays balanced
    sizes = {n: os.path.getsize(os.path.join(ds.DATA, n + ".csv")) for n in names}
    jobs.sort(key=lambda j: -sizes[j[0]] * len(j[1]))

    n_err_cases, err_msgs = check_errors()
    parts = 8
    extra = not args.no_fuzz
    fuzz_jobs = [(1000 + i, args.fuzz // parts + (1 if i < args.fuzz % parts else 0)) for i in range(parts)] \
        if extra and args.fuzz > 0 else []
    synth_jobs = [(2000 + i, args.synth // parts + (1 if i < args.synth % parts else 0), args.verbose)
                  for i in range(parts)] if extra and args.synth > 0 else []
    edge_jobs = [(args.verbose,)] if extra else []

    with Pool(max(1, args.jobs)) as pool:
        fuzz_async = pool.map_async(run_fuzz, fuzz_jobs, chunksize=1)
        synth_async = pool.map_async(run_synth, synth_jobs, chunksize=1)
        edge_async = pool.map_async(run_edge, edge_jobs, chunksize=1)
        results = []
        for r in pool.imap_unordered(run_dataset, jobs, chunksize=1):
            results.append(r)
            if args.verbose:
                print(f"  {r['name']:26s} bars={r['bars']:6d} cases={r['cases']:3d} failed={r['failed']:3d} "
                      f"A={r['ta']:6.1f}s B={r['tb'] * 1e3:7.1f}ms", flush=True)
        fuzz_results = fuzz_async.get()
        synth_results = synth_async.get()
        edge_results = edge_async.get()

    results.sort(key=lambda r: r["name"])
    cases = sum(r["cases"] for r in results)
    failed = sum(r["failed"] for r in results)
    bitid = sum(r["bit_identical"] for r in results)
    fcases = sum(r["cases"] for r in fuzz_results)
    ffailed = sum(r["failed"] for r in fuzz_results)

    messages = param_msgs + err_msgs
    for r in results + edge_results + synth_results + fuzz_results:
        messages += r["messages"]
    shown = messages if args.verbose else messages[:12]
    for m in shown:
        print(m)
    if len(messages) > len(shown):
        print(f"... {len(messages) - len(shown)} more mismatch report(s) suppressed (use -v)")

    n_full = sum(1 for j in jobs if len(j[1]) == len(labels))
    print("=" * 100)
    print(f"datasets: {len(names)}  ({n_full} with the full matrix of {len(labels)} Params, "
          f"{len(names) - n_full} with {len(core_labels)} core Params)"
          + (f"   [last {args.max_bars} bars only]" if args.max_bars else "   [full length, no slicing]"))
    print(f"bars compared: {sum(r['bars'] * r['cases'] for r in results):,}   closed trades compared: "
          f"{sum(r['trades'] for r in results):,}")
    print(f"dataset x Params cases: {cases}   mismatching: {failed}   bit-identical: {bitid}   "
          f"max relative float difference: {max([r['maxrel'] for r in results] + [0.0]):.3g}")
    print(f"input-check (ValueError) cases: {n_err_cases}   mismatching: {len(err_msgs)}"
          f"   Params dataclass: {'identical' if not param_msgs else 'DIFFERENT'}")
    for title, rs in (("edge run() cases (short charts, L120 fallback, partial HTF)", edge_results),
                      ("synthetic-chart run() cases", synth_results)):
        print(f"{title}: {sum(r['cases'] for r in rs)}   mismatching: {sum(r['failed'] for r in rs)}   "
              f"bit-identical: {sum(r['bit_identical'] for r in rs)}   "
              f"closed trades compared: {sum(r['trades'] for r in rs):,}")
    print(f"simulate() fuzz scenarios: {fcases}   mismatching: {ffailed}   "
          f"closed trades compared: {sum(r['trades'] for r in fuzz_results):,}   "
          f"flavours: {_fmt(_merge(r['flavours'] for r in fuzz_results))}")
    print("branch coverage, real data : " + _fmt(_merge(r["cov"] for r in results)))
    print("branch coverage, synth+edge: " + _fmt(_merge(r["cov"] for r in synth_results + edge_results)))
    print("branch coverage, fuzz      : " + _fmt(_merge(r["cov"] for r in fuzz_results)))
    ta = sum(r["ta"] for r in results)
    tb = sum(r["tb"] for r in results)
    print(f"engine time (summed over workers): A {ta:.1f} s   B {tb:.2f} s   (B is {ta / tb if tb else NAN:.0f}x faster)"
          f"   wall {time.perf_counter() - t_start:.1f} s")
    total_bad = (failed + ffailed + len(err_msgs) + len(param_msgs)
                 + sum(r["failed"] for r in edge_results + synth_results))
    print(f"RESULT: {'PASS - zero mismatches' if total_bad == 0 else f'FAIL - {total_bad} mismatching case(s)'}")
    return 0 if total_bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
