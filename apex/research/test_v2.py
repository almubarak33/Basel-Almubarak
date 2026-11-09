#!/usr/bin/env python3
"""Tests of engine_v2: the v2 kernel equals the verified v1 kernel when the new rule is off, the new rule does
what its definition says on hand-built bars, and the intrabar replay agrees with a hand-traced example.

Usage: python3 test_v2.py
"""
import sys

import numpy as np

import datasets as ds
import engine_b as B
import engine_v2 as V

FAIL = []


def check(name, cond, detail=""):
    if not cond:
        FAIL.append(name)
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))


def sim(bars, mgmt, long_at=0, short_at=None, dist=10.0, cost=0.0, chand=None):
    """bars: list of (o, h, l, c).  A signal on bar `long_at` / `short_at`; stop distance `dist`."""
    o, h, l, c = (np.array(x, dtype=float) for x in zip(*bars))
    n = len(c)
    ls = np.zeros(n, bool)
    ss = np.zeros(n, bool)
    if long_at is not None:
        ls[long_at] = True
    if short_at is not None:
        ss[short_at] = True
    d = np.full(n, dist)
    ch = np.full(n, np.nan) if chand is None else np.array(chand, dtype=float)
    rec, op, st = V.simulate_arrays(o, h, l, c, ls, ss, d, d, ch, ch, mgmt, cost, 0.01)
    return V.trades_list(rec), V.open_trade_dict(op), V.stats_dict(st)


HP = {"k1": 0.3, "k2": 1.5, "k3": 4.0, "w1": 0.5, "w2": 0.25, "trailOn": False, "trailFrom": 1, "beOn": True}


def scenarios():
    # Long at 100 (close of bar 0), stop distance 10 -> SL 90, TP1 103, TP2 115, TP3 140.
    # Bar 1 trades up to 104 (TP1 fills, stop -> 100) and CLOSES at 99, below the raised stop.
    bars = [(100, 100, 100, 100), (100, 104, 98, 99), (97, 98, 96, 97)]
    # rule 0 (v1): remainder carried; bar 2 opens at 97 <= stop 100 -> exit at the open 97.
    t, _, _ = sim(bars, {**HP, "closeStop": 0})
    check("rule0: carried to next open", len(t) == 1 and t[0]["exit_bar"] == 2 and t[0]["exit_px"] == 97.0
          and abs(t[0]["R"] - (0.5 * 0.3 + 0.5 * (97 - 100) / 10)) < 1e-12 and t[0]["reason"] == "BE/Trail", str(t))
    # rule 1: the close 99 <= 100 proves the raised stop was crossed after the fill -> exit at 100 on bar 1.
    t, _, _ = sim(bars, {**HP, "closeStop": 1})
    check("rule1: exit at raised stop on the same bar", len(t) == 1 and t[0]["exit_bar"] == 1 and t[0]["exit_px"] == 100.0
          and abs(t[0]["R"] - 0.15) < 1e-12 and t[0]["reason"] == "BE/Trail" and t[0]["hit1"], str(t))
    # Same bar but closing ABOVE the raised stop (101): the order inside the bar is unknown.
    bars2 = [(100, 100, 100, 100), (100, 104, 98, 101), (101, 102, 100.5, 101)]
    t, op, _ = sim(bars2, {**HP, "closeStop": 1})
    check("rule1: no exit when the close is above the raised stop", len(t) == 0 and op is not None and op["hit1"], str(t))
    # rule 2 (pessimistic): the low 98 <= 100 is assumed to have come after the fill -> exit at 100 on bar 1.
    t, _, _ = sim(bars2, {**HP, "closeStop": 2})
    check("rule2: exit when the low reached the raised stop", len(t) == 1 and t[0]["exit_bar"] == 1 and t[0]["exit_px"] == 100.0, str(t))
    # TP1 not reached: nothing was raised, so a weak close changes nothing under any rule.
    bars3 = [(100, 100, 100, 100), (100, 102, 95, 96), (96, 97, 95, 96)]
    for rule in (0, 1, 2):
        t, op, _ = sim(bars3, {**HP, "closeStop": rule})
        check(f"rule{rule}: untouched when no fill raised the stop", len(t) == 0 and op is not None and not op["hit1"], str(t))
    # Breakeven off (Trend Runner style): TP1 does not move the stop, so the rule cannot fire.
    run = {"k1": 0.3, "k2": 1.5, "k3": 4.0, "w1": 0.5, "w2": 0.25, "trailOn": False, "trailFrom": 2, "beOn": False}
    t, op, _ = sim(bars, {**run, "closeStop": 1})
    check("rule1: no breakeven -> no exit", len(t) == 0 and op is not None and op["hit1"], str(t))
    # TP2 lock: bar reaches TP1 and TP2 (116) and closes at 102 <= TP1 (103) -> remainder exits at 103.
    bars4 = [(100, 100, 100, 100), (101, 116, 100.5, 102), (102, 103, 101, 102)]
    t, _, _ = sim(bars4, {**HP, "closeStop": 1})
    exp = 0.5 * 0.3 + 0.25 * 1.5 + 0.25 * 0.3
    check("rule1: TP1 lock after TP2", len(t) == 1 and t[0]["exit_bar"] == 1 and t[0]["exit_px"] == 103.0
          and abs(t[0]["R"] - exp) < 1e-12 and t[0]["hit2"], str(t))
    # Short mirror: short at 100, SL 110, TP1 97; bar trades down to 96 and closes at 101 >= raised stop 100.
    bars5 = [(100, 100, 100, 100), (100, 102, 96, 101), (103, 104, 102, 103)]
    t, _, _ = sim(bars5, {**HP, "closeStop": 1}, long_at=None, short_at=0)
    check("rule1: short mirror", len(t) == 1 and t[0]["exit_bar"] == 1 and t[0]["exit_px"] == 100.0 and abs(t[0]["R"] - 0.15) < 1e-12, str(t))
    # The original stop still comes first: low 89 <= 90 -> full stop even though the high reached TP1.
    bars6 = [(100, 100, 100, 100), (100, 104, 89, 95), (95, 96, 94, 95)]
    t, _, _ = sim(bars6, {**HP, "closeStop": 1})
    check("rule1: initial stop still first", len(t) == 1 and t[0]["reason"] == "SL" and abs(t[0]["R"] + 1.0) < 1e-12 and not t[0]["hit1"], str(t))
    # Cost: the scratch is a win only while the banked part exceeds the cost (0.15R banked; cost 2% of 100 / 10 = 0.2R).
    t, _, _ = sim(bars, {**HP, "closeStop": 1}, cost=2.0)
    check("rule1: cost can turn the scratch into a loss", len(t) == 1 and abs(t[0]["R"] - (0.15 - 0.2)) < 1e-12, str(t))


def replay():
    # Chart bars of 4 fine bars each.  Chart bar 0: flat (the replay starts flat on the first bar with fine
    # data and ignores a signal on it).  Long signal on chart bar 1 (close 100), stop distance 10 -> TP1 103.
    # Chart bar 2 as a whole: high 104, low 98, close 101 -> ambiguous on the chart bar.
    #   order A: dip to 98 first, then rally to 104 and stay above 100  -> remainder survives
    #   order B: rally to 104 first, then dip to 98                     -> remainder stopped at 100 (breakeven)
    flat = [(100, 100, 100, 100)] * 4
    a2 = [(100, 100.5, 98, 99), (99, 104, 99, 103.5), (103.5, 104, 101, 102), (102, 102, 100.5, 101)]
    b2 = [(100, 104, 100, 103.5), (103.5, 103.8, 98, 99), (99, 101, 98.5, 100.5), (100.5, 101.5, 100.2, 101)]
    after = [(101, 102, 100.5, 101.5)] * 4
    for name, mid, survives in (("A", a2, True), ("B", b2, False)):
        fine_bars = flat + flat + mid + after
        fo, fh, fl, fc = (np.array(x, dtype=float) for x in zip(*fine_bars))
        fine = {"t": np.arange(16) * 900, "o": fo, "h": fh, "l": fl, "c": fc, "v": np.ones(16)}
        chart = {"t": np.arange(4) * 3600, "o": np.array([100, 100, 100, 101.0]), "h": np.array([100, 100, 104, 102.0]),
                 "l": np.array([100, 100, 98, 100.5]), "c": np.array([100, 100, 101, 101.5]), "v": np.ones(4)}
        n = 4
        sig = np.zeros(n, bool)
        sig[1] = True
        feats = {"longSig": sig, "shortSig": np.zeros(n, bool), "slDistL": np.full(n, 10.0), "slDistS": np.full(n, 10.0),
                 "chandL": np.full(n, np.nan), "chandS": np.full(n, np.nan), "costPct": 0.0, "mintick": 0.01,
                 "trigCodeL": np.zeros(n, np.int64), "trigCodeS": np.zeros(n, np.int64),
                 "scoreL": np.full(n, 7, np.int64), "scoreS": np.full(n, 7, np.int64)}
        rec_f, rec_c, _, d0 = V.magnify(chart, feats, fine, {**HP, "closeStop": 1})
        tf = V.trades_list(rec_f)
        tc = V.trades_list(rec_c)
        check(f"replay order {name}: first chart bar with fine data is bar 0", d0 == 0)
        if survives:
            check(f"replay order {name}: remainder survives the bar", len(tf) == 0, str(tf))
        else:
            # fine bar 8 (first of chart bar 2) reaches 104 -> TP1, stop to 100; fine bar 9 trades down to 98 -> exit at 100
            check(f"replay order {name}: remainder stopped at breakeven inside the bar",
                  len(tf) == 1 and tf[0]["exit_px"] == 100.0 and abs(tf[0]["R"] - 0.15) < 1e-12 and tf[0]["exit_bar"] == 9, str(tf))
        check(f"replay order {name}: chart-bar rule 1 keeps the trade (close above the stop)", len(tc) == 0, str(tc))
    # a signal on the very first chart bar with fine data is ignored by both simulations (flat start)
    sig0 = np.zeros(4, bool)
    sig0[0] = True
    feats0 = dict(feats)
    feats0["longSig"] = sig0
    rec_f, rec_c, _, _ = V.magnify(chart, feats0, fine, {**HP, "closeStop": 1})
    check("replay: signal on the first covered bar is ignored", len(rec_f) == 0 and len(rec_c) == 0)


def parity():
    bad = 0
    n = 0
    variants = (B.Params(), B.Params(profile="BAL"), B.Params(profile="RUN", dirMode="Long only"),
                B.Params(profile="CUS", cW1=60, cW2=40, cTrail=True), B.Params(profile="HP", minScore=5, useTsm=False))
    for name in ds.list_datasets():
        ch = ds.load(name)
        m = ds.market_of(name, ch)
        htf, _ = ds.htf_bars(name, ch)
        base = B.base_features(ch, htf, m)
        for p in variants:
            f = B.features(ch, htf, p, m, base)
            mg = B.mgmt_of(p, m)
            args = (ch["o"], ch["h"], ch["l"], ch["c"], f["longSig"], f["shortSig"], f["slDistL"], f["slDistS"],
                    f["chandL"], f["chandS"], mg, f["costPct"], f["mintick"], f["trigCodeL"], f["trigCodeS"],
                    f["scoreL"], f["scoreS"])
            a = B.simulate_arrays(*args)
            b = V.simulate_arrays(*args)
            n += 1
            if any(x.shape != y.shape or not np.array_equal(x, y, equal_nan=True) for x, y in zip(a, b)):
                bad += 1
                print("  mismatch:", name, p.profile)
    check(f"v2 kernel with closeStop=0 is bit-identical to engine_b ({n} dataset x parameter cases)", bad == 0)


if __name__ == "__main__":
    scenarios()
    replay()
    parity()
    print("PASS" if not FAIL else f"FAIL: {len(FAIL)} checks")
    sys.exit(1 if FAIL else 0)
