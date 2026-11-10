#!/usr/bin/env python3
"""Tests of fusion_engine.py.

1. Cross-check against the verified APEX Focus port: with the Fusion-only parts switched off (GBB setups,
   anchor/HTF gates, session filter, execution pack) the script reduces to APEX Focus without the TSMOM gate,
   so fusion_engine must reproduce engine_b trade for trade on real data.
2. Hand-built scenarios for what Fusion adds to the trade kernel: pending pullback limit orders, the time exit
   and the reverse switch.
3. Hand-built bars for the stateful GBB setups (opening range, VWAP reclaim, break & retest, EMA pullback).

Usage: python3 test_fusion.py
"""
import sys

import numpy as np

import datasets as ds
import engine_b as B
import fusion_engine as F

FAIL = []


def check(name, cond, detail=""):
    if not cond:
        FAIL.append(name)
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))


# ───────────────────────────── 1. Focus-equivalent configuration ─────────────────────────────
def focus_equivalence():
    names = [n for n in ds.list_datasets() if n.split("_")[0] in ("OANDA", "BINANCEX", "NASDAQ", "TADAWUL", "NYSE", "AMEX")]
    bad, cases, trades_total = 0, 0, 0
    for name in names:
        ctx = F.context(name)
        m = ctx["market"]
        chart = ctx["chart"]
        htf, _ = ds.htf_bars(name, chart)
        for prof_f, prof_b in (("HP", "HP"), ("RUN", "RUN")):
            pb = B.Params(useTsm=False, profile=prof_b, costMode="Custom", costCustom=0.03)
            rb = B.run(chart, htf, pb, m)
            pf = F.FParams(minScore=7, useAnchor=False, useHtfGate=False, sessIn="Off", ltfPack=False, useBrt=False,
                           useOrb=False, useEma=False, useVwap=False, profile=prof_f, costMode="Custom", costCustom=0.03)
            f = F.features(ctx, pf)
            tf, sf, _ = F.simulate(ctx, f, pf)
            cases += 1
            tb = rb["trades"]
            trades_total += len(tb)
            same = len(tb) == len(tf) and np.array_equal(rb["series"]["longSig"], f["longSig"]) \
                and np.array_equal(rb["series"]["shortSig"], f["shortSig"])
            if same:
                for a, b in zip(tb, tf):
                    if (a["dir"], a["entry_bar"], a["exit_bar"], a["reason"], a["hit1"], a["hit2"], a["hit3"]) != \
                            (b["dir"], b["entry_bar"], b["exit_bar"], b["reason"], b["hit1"], b["hit2"], b["hit3"]) \
                            or abs(a["R"] - b["R"]) > 1e-9 or abs(a["exit_px"] - b["exit_px"]) > 1e-9 * abs(a["exit_px"]):
                        same = False
                        break
            if not same:
                bad += 1
                print("   mismatch:", name, prof_f, len(tb), len(tf))
    check(f"Focus-equivalent configuration reproduces engine_b ({cases} dataset x profile cases, {trades_total} trades)", bad == 0)


# ───────────────────────────── 2. trade-kernel scenarios ─────────────────────────────
MW = {"k1": 0.4, "k2": 1.5, "k3": 4.0, "w1": 0.6, "w2": 0.2, "trailOn": False, "trailFrom": 1, "beOn": True}


def kernel(bars, long_at=(), short_at=(), dist=10.0, mgmt=MW, pullback=True, pb_frac=0.33, pb_bars=3, max_bars=0,
           reverse=True, cost=0.0, mult=0.0):
    o, h, l, c = (np.array(x, dtype=float) for x in zip(*bars))
    n = len(c)
    ls = np.zeros(n, np.bool_)
    ss = np.zeros(n, np.bool_)
    for i in long_at:
        ls[i] = True
    for i in short_at:
        ss[i] = True
    d = np.full(n, dist)
    nanv = np.full(n, np.nan)
    z = np.zeros(n, np.int64)
    rec, st, n_sig, n_fill, n_miss = F._core_fusion(o, h, l, c, ls, ss, d, d, nanv, nanv, z, z, z + 7, z + 7,
                                                   mgmt["k1"], mgmt["k2"], mgmt["k3"], mgmt["w1"], mgmt["w2"],
                                                   mgmt["trailOn"], mgmt["trailFrom"], mgmt["beOn"], cost, 0.01,
                                                   int(mgmt.get("closeStop", 0)), pullback, pb_frac, pb_bars, max_bars, reverse, mult)
    return rec, B.stats_dict(st), (n_sig, n_fill, n_miss)


def scenarios():
    C = F.C_ENTRY, F.C_SL0, F.C_RISK, F.C_TP1, F.C_XPX, F.C_REASON, F.C_R, F.C_EBAR, F.C_XBAR
    e_, sl_, risk_, tp1_, xpx_, rs_, r_, eb_, xb_ = C
    flat = (100, 100, 100, 100)
    # Long signal at close 100, stop distance 10 -> limit 96.7, stop 90.  Risk from the fill = 6.7.
    # Bar 1 dips to 96 -> filled at 96.7 (stop 90 not reached).  TP1 = 96.7 + 0.4*6.7 = 99.38.
    # Bar 2 trades 97..100 -> TP1 (60% closed, +0.24R), stop to 96.7.  Bar 3 opens 96 <= stop -> exit at the open.
    rec, st, info = kernel([flat, (100, 100.5, 96, 97), (97, 100, 96.9, 99.5), (96, 96.5, 95, 95.5)], long_at=[0])
    exp = 0.6 * 0.4 + 0.4 * (96 - 96.7) / 6.7
    check("limit fill: entry at the limit, risk measured from the fill",
          len(rec) == 1 and abs(rec[0, e_] - 96.7) < 1e-12 and abs(rec[0, risk_] - 6.7) < 1e-9 and rec[0, eb_] == 1, str(rec))
    check("limit fill: TP1 then breakeven exit at the next open", len(rec) == 1 and abs(rec[0, r_] - exp) < 1e-9
          and F.REASONS[int(rec[0, rs_])] == "BE/Trail" and rec[0, xb_] == 3, str(rec[0, r_]) + " vs " + str(exp))
    check("limit fill: counters", info == (1, 1, 0), str(info))
    # Gap below the limit at the open: filled at the open (better price), not at the limit.
    rec, st, info = kernel([flat, (95, 96, 94, 95.5), (95.5, 96, 95, 95.5)], long_at=[0])
    check("limit fill at a gap open uses the open", len(rec) == 0 and info == (1, 1, 0))
    # Fill bar also reaches the stop -> counted as a full stop on the fill bar.
    rec, st, info = kernel([flat, (99, 99.5, 89, 92), flat], long_at=[0])
    check("fill bar that also reaches the stop is a stop", len(rec) == 1 and F.REASONS[int(rec[0, rs_])] == "SL"
          and abs(rec[0, r_] + 1.0) < 1e-9 and rec[0, xb_] == 1, str(rec))
    # Not filled within 3 bars -> expires on the 4th bar after the signal even if price comes back then.
    rec, st, info = kernel([flat, (100, 101, 99, 100), (100, 101, 99, 100), (100, 101, 99, 100), (100, 100, 95, 96), flat], long_at=[0])
    check("unfilled limit expires after pbBars", len(rec) == 0 and info == (1, 0, 1), str(info))
    # Open at or beyond the stop invalidates the pending order.
    rec, st, info = kernel([flat, (89, 97, 88, 96), flat], long_at=[0])
    check("pending order cancelled when the bar opens beyond its stop", len(rec) == 0 and info == (1, 0, 1), str(info))
    # A newer signal replaces the pending order.
    rec, st, info = kernel([flat, (100, 101, 99, 100), (100, 100.5, 96, 99), flat], long_at=[0, 1])
    check("a new signal replaces the pending order", info[0] == 2 and info[2] >= 1, str(info))
    # Short mirror: limit 103.3, stop 110, risk 6.7.
    rec, st, info = kernel([flat, (100, 104, 99.5, 103), (103, 111, 102, 110.5)], short_at=[0])
    check("short limit fill and stop", len(rec) == 1 and abs(rec[0, e_] - 103.3) < 1e-9 and abs(rec[0, r_] + 1.0) < 1e-9, str(rec))
    # Market mode (1H and above): entry at the signal close.
    rec, st, info = kernel([flat, (100, 101, 89, 95), flat], long_at=[0], pullback=False)
    check("market mode enters at the close", len(rec) == 1 and rec[0, e_] == 100.0 and rec[0, eb_] == 0 and abs(rec[0, r_] + 1.0) < 1e-12, str(rec))
    # Reverse switch: with reverseOn an opposite signal closes the trade at the close; without it the signal is ignored.
    bars = [flat, (100, 101, 99.5, 100.5), (100.5, 101, 100, 100.5), flat]
    rec, st, info = kernel(bars, long_at=[0], short_at=[2], pullback=False, reverse=True)
    check("reverse on: opposite signal closes at the close", len(rec) == 1 and F.REASONS[int(rec[0, rs_])] == "Reverse"
          and abs(rec[0, r_] - 0.05) < 1e-12, str(rec))
    rec, st, info = kernel(bars, long_at=[0], short_at=[2], pullback=False, reverse=False)
    check("reverse off: opposite signal ignored", len(rec) == 0 and info[0] == 1, str(info))
    # Time exit after N bars at the close.
    rec, st, info = kernel([flat, (100, 101, 99.5, 100.5), (100.5, 101, 100, 100.8), flat], long_at=[0], pullback=False, max_bars=2)
    check("time exit", len(rec) == 1 and F.REASONS[int(rec[0, rs_])] == "Time" and rec[0, xb_] == 2 and abs(rec[0, r_] - 0.08) < 1e-12, str(rec))
    # Cost in R uses the fill and the risk from the fill.
    rec, st, info = kernel([flat, (99, 99.5, 89, 92), flat], long_at=[0], cost=1.0)
    check("cost scaled by entry / risk of the fill", len(rec) == 1 and abs(rec[0, r_] - (-1.0 - 0.01 * 96.7 / 6.7)) < 1e-9, str(rec[0, r_]))
    # v3 cost floor of the first target.  Market long at 100, stop 90 (risk 10), cost 0.1% -> 0.01R.
    # Multiplier 3 with k1 = 0: TP1 = 3 costs = 0.03R = 100.3.  Bar 1 reaches 100.4 -> everything closes there.
    full = {"k1": 0.0, "k2": 1.5, "k3": 4.0, "w1": 1.0, "w2": 0.0, "trailOn": False, "trailFrom": 1, "beOn": True}
    rec, st, info = kernel([flat, (100, 100.4, 99.9, 100.1), flat], long_at=[0], pullback=False, mgmt=full, cost=0.1, mult=3.0)
    check("cost floor: TP1 at 3 x cost, net +2 costs", len(rec) == 1 and abs(rec[0, tp1_] - 100.3) < 1e-9
          and F.REASONS[int(rec[0, rs_])] == "TP" and abs(rec[0, r_] - 0.02) < 1e-9, str(rec))
    # The profile's own k1 wins when it is further than the floor (0.05R > 0.03R).
    rec, st, info = kernel([flat, (100, 100.6, 99.9, 100.1), flat], long_at=[0], pullback=False, mgmt=dict(full, k1=0.05), cost=0.1, mult=3.0)
    check("cost floor: a larger profile target is kept", len(rec) == 1 and abs(rec[0, tp1_] - 100.5) < 1e-9 and abs(rec[0, r_] - 0.04) < 1e-9, str(rec))
    # Multiplier off: TP1 = k1 exactly, even when that is below the cost (the trade then nets a loss).
    rec, st, info = kernel([flat, (100, 100.1, 99.9, 100.0), flat], long_at=[0], pullback=False, mgmt=dict(full, k1=0.005), cost=0.1)
    check("cost floor off: a target below the cost is a net loss", len(rec) == 1 and abs(rec[0, tp1_] - 100.05) < 1e-9 and rec[0, r_] < 0, str(rec))
    # Cap: with an absurd cost (20% -> 2R) the floor stops at half of TP2 (0.75R = 107.5).
    rec, st, info = kernel([flat, (100, 108, 99.9, 107), flat], long_at=[0], pullback=False, mgmt=full, cost=20.0, mult=3.0)
    check("cost floor is capped at k2 / 2", len(rec) == 1 and abs(rec[0, tp1_] - 107.5) < 1e-9, str(rec))
    # Limit fill: the floor uses the fill price and the risk from the fill (96.7, 6.7): 3 x 0.0967 above the fill.
    rec, st, info = kernel([flat, (100, 100.5, 96, 97), (97, 97.2, 96.8, 97.1), flat], long_at=[0], mgmt=full, cost=0.1, mult=3.0)
    check("cost floor after a limit fill is measured from the fill", len(rec) == 1 and abs(rec[0, tp1_] - (96.7 + 3 * 0.0967)) < 1e-9
          and abs(rec[0, r_] - 2 * 0.0967 / 6.7) < 1e-9, str(rec))


# ───────────────────────────── 3. stateful setups ─────────────────────────────
def setups():
    n = 40
    o = np.full(n, 100.0)
    h = np.full(n, 100.5)
    l = np.full(n, 99.5)
    c = np.full(n, 100.0)
    v = np.full(n, 1000.0)
    atr = np.full(n, 1.0)
    rsi = np.full(n, 50.0)
    ok = np.ones(n, np.bool_)
    new_day = np.zeros(n, np.bool_)
    t = (np.arange(n) * 300).astype(np.int64)                 # 5-minute bars
    nanv = np.full(n, np.nan)
    # Opening range: session from bar 10; 15 minutes = bars 10, 11, 12; range high 101 / low 99.
    in_or = np.zeros(n, np.bool_)
    in_or[10:30] = True
    h2, l2, c2 = h.copy(), l.copy(), c.copy()
    h2[10:13] = [101.0, 100.8, 100.9]
    l2[10:13] = [99.0, 99.2, 99.4]
    c2[15] = 101.5                                            # first close above the range high
    h2[15] = 101.6
    c2[17] = 102.0                                            # later closes above it must not fire again
    h2[17] = 102.1
    out = F._state_setups(o, h2, l2, c2, v, atr, rsi, ok, new_day, in_or, t, nanv, nanv, 5, 0.3, 20, 60, 15, True, 6)
    orb_l = out[7]
    check("ORB: fires once, on the first close above the 15-minute range", orb_l[15] and orb_l.sum() == 1, str(np.flatnonzero(orb_l)))
    out = F._state_setups(o, h2, l2, c2, v, atr, rsi, ok, new_day, in_or, t, nanv, nanv, 5, 0.3, 20, 60, 15, False, 6)
    check("ORB: with the setup disabled the raw condition repeats (no 'fired' latch)", out[7][15] and out[7][17])
    # VWAP reclaim: new day at bar 5; 8 closes below VWAP then a close above it.
    nd = np.zeros(n, np.bool_)
    nd[5] = True
    c3, h3, l3 = c.copy(), h.copy(), l.copy()
    for i in range(6, 14):
        c3[i] = 99.0
        h3[i] = 99.6
        l3[i] = 98.8
    c3[14] = 100.2
    h3[14] = 100.4
    l3[14] = 99.0
    out = F._state_setups(o, h3, l3, c3, v, atr, rsi, ok, nd, np.zeros(n, np.bool_), t, nanv, nanv, 5, 0.3, 20, 60, 15, True, 6)
    vw, vw_l = out[0], out[1]
    exp_vwap5 = (h3[5] + l3[5] + c3[5]) / 3.0
    check("VWAP: resets on the new day", abs(vw[5] - exp_vwap5) < 1e-12, f"{vw[5]} vs {exp_vwap5}")
    check("VWAP reclaim: one signal after >= 6 closes below", vw_l[14] and vw_l.sum() == 1, str(np.flatnonzero(vw_l)))
    # Break & retest: swing high 101 reported at bar 8; close above at bar 12; retest (low within 0.3 ATR, bullish close above) at bar 15.
    ph = nanv.copy()
    ph[8] = 101.0
    o4, h4, l4, c4 = o.copy(), h.copy(), l.copy(), c.copy()
    c4[12] = 101.6
    h4[12] = 101.8
    for i in (13, 14):
        o4[i], h4[i], l4[i], c4[i] = 101.8, 102.2, 101.6, 102.0
    o4[15], h4[15], l4[15], c4[15] = 101.3, 101.9, 101.2, 101.7
    out = F._state_setups(o4, h4, l4, c4, v, atr, rsi, ok, new_day, np.zeros(n, np.bool_), t, ph, nanv, 5, 0.3, 20, 60, 15, True, 6)
    brt_l = out[3]
    check("break & retest: fires on the retest bar only", brt_l[15] and brt_l.sum() == 1, str(np.flatnonzero(brt_l)))
    # Pivots: strict peak reported pvLen bars later.
    x = np.array([1, 2, 3, 4, 5, 9, 5, 4, 3, 2, 1, 1, 1], dtype=float)
    pv = F._pivots(x, 5, True)
    check("pivot high reported 5 bars after the peak", pv[10] == 9.0 and np.isnan(pv[9]) and np.nansum(pv) == 9.0, str(pv))
    # Equal highs: the newest one is the pivot (reported 5 bars after it), the older one is not.
    x = np.array([1, 2, 3, 4, 5, 9, 9, 5, 4, 3, 2, 1, 1, 1], dtype=float)
    pv = F._pivots(x, 5, True)
    check("pivot tie: the newest of equal highs is the pivot", pv[11] == 9.0 and np.isnan(pv[10]) and np.nansum(pv) == 9.0, str(pv))
    pv = F._pivots(-x, 5, False)
    check("pivot tie: the newest of equal lows is the pivot", pv[11] == -9.0 and np.isnan(pv[10]), str(pv))
    # Forming higher-timeframe bar: chart bars after the last closed HTF bar are folded into one extra bar.
    chart = {"t": np.array([0, 60, 120, 180, 240]), "o": np.array([1., 2, 3, 4, 5]), "h": np.array([2., 3, 4, 9, 6]),
             "l": np.array([0., 1, 2, 3, 4]), "c": np.array([2., 3, 4, 5, 6]), "v": np.array([1., 1, 1, 1, 1])}
    htf = {"t": np.array([0]), "o": np.array([1.]), "h": np.array([4.]), "l": np.array([0.]), "c": np.array([4.]), "v": np.array([3.])}
    ext = F._with_forming(htf, chart, 180)
    check("forming HTF bar appended from the chart tail", list(ext["t"]) == [0, 180] and ext["o"][1] == 4 and ext["h"][1] == 9
          and ext["l"][1] == 3 and ext["c"][1] == 6 and ext["v"][1] == 2, str(ext))
    check("no forming bar when the chart ends inside the last HTF bar", len(F._with_forming(htf, {k: v[:3] for k, v in chart.items()}, 180)["t"]) == 1)
    # barssince
    bs = F._barssince(np.array([False, True, False, False, True, False]))
    check("barssince", np.isnan(bs[0]) and list(bs[1:]) == [0, 1, 2, 0, 1], str(bs))
    # session mask: 08:00-17:00 New York in winter (UTC-5) and summer (UTC-4)
    import datetime as dt
    ts = np.array([int(dt.datetime(2026, 1, 15, 13, 0, tzinfo=dt.UTC).timestamp()),   # 08:00 EST -> in
                   int(dt.datetime(2026, 1, 15, 12, 55, tzinfo=dt.UTC).timestamp()),  # 07:55 EST -> out
                   int(dt.datetime(2026, 1, 15, 22, 0, tzinfo=dt.UTC).timestamp()),   # 17:00 EST -> out (end exclusive)
                   int(dt.datetime(2026, 7, 15, 12, 0, tzinfo=dt.UTC).timestamp())])  # 08:00 EDT -> in
    check("session mask follows New York daylight saving", list(F._session_mask(ts, "0800-1700", "America/New_York")) == [True, False, False, True])


if __name__ == "__main__":
    scenarios()
    setups()
    focus_equivalence()
    print("PASS" if not FAIL else f"FAIL: {len(FAIL)} checks: {FAIL}")
    sys.exit(1 if FAIL else 0)
