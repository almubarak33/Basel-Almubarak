#!/usr/bin/env python3
"""Where does the edge come from?  Pure 1R:1R bracket tests (no breakeven, no trailing, close all at 1R).

With a symmetric bracket the win rate is 50% when entries carry no information, so anything above 50%
(before cost) is real directional edge.  Three entry sets are compared:
  * the script's signals (trend state + trigger),
  * random bars                       -> market drift only,
  * random bars while the score is 7  -> drift + trend state, without the trigger timing.
Usage: python3 study_edge.py
"""
import datetime as dt

import numpy as np

import research_lib as rl

E = rl.E
PURE = {"k1": 1.0, "k2": 2.0, "k3": 3.0, "w1": 1.0, "w2": 0.0, "trailOn": False, "trailFrom": 1, "beOn": False}
GROUPS = (("5m+15m+1h", ("5m", "15m", "1h")), ("4h", ("4h",)), ("1D", ("1D",)))


def line(label, trades):
    a = rl.summary(trades)
    if a["n"] == 0:
        return f"{label:44s} n=0"
    return (f"{label:44s} n={a['n']:6d} win={100*a['win']:5.1f}% [{100*a['win_lo']:4.1f},{100*a['win_hi']:4.1f}] "
            f"avgR={a['avgR']:+.3f} PF={a['pf']:4.2f}")


def cells(label, trades):
    out = f"{label:20s}"
    for c in ("TRAIN", "TEST_TIME", "TEST_INSTR"):
        a = rl.summary(rl.cell(trades, c))
        out += (f" | {c[:10]:10s} n={a['n']:4d} win={100*a['win']:5.1f}% avgR={a['avgR']:+.3f}" if a["n"]
                else f" | {c[:10]:10s} n=   0" + " " * 23)
    return out


def sim(s, f, long_sig, short_sig, cost=0.0):
    c = s.chart
    rec, _, _ = E.simulate_arrays(c["o"], c["h"], c["l"], c["c"], long_sig, short_sig, f["slDistL"], f["slDistS"],
                                  f["chandL"], f["chandS"], PURE, cost, f["mintick"])
    return [{"R": r["R"], "hit1": r["hit1"], "reason": r["reason"], "t": r["entry_bar"], "cost_R": r["cost_R"]}
            for r in E.trades_list(rec)]


def main():
    uni = rl.universe()
    feats = {s.name: E.features(s.chart, s.htf, E.Params(smallGuard=False), s.market, s.base) for s in uni}
    rng = np.random.default_rng(12345)

    print("[1] script signals vs random entries, zero cost, pure 1R:1R bracket")
    for grp, tfs in GROUPS:
        for d, dl in ((1, "long"), (-1, "short")):
            sig, rnd, rnd7 = [], [], []
            for s in uni:
                if s.tf not in tfs:
                    continue
                f = feats[s.name]
                n = s.n
                zero = np.zeros(n, bool)
                ls = f["longSig"] if d == 1 else zero
                ss = f["shortSig"] if d == -1 else zero
                sig += sim(s, f, ls, ss)
                k = int((ls | ss).sum())
                ok = np.zeros(n, bool)
                ok[250:] = True
                ok &= np.isfinite(f["slDistL"]) & np.isfinite(f["slDistS"])
                state = ok & ((f["scoreL"] >= 7) if d == 1 else (f["scoreS"] >= 7))
                for _ in range(6):
                    for pool, out in ((ok, rnd), (state, rnd7)):
                        idx = np.flatnonzero(pool)
                        if len(idx) == 0:
                            continue
                        pick = np.zeros(n, bool)
                        pick[rng.choice(idx, size=min(len(idx), max(3 * k, 20)), replace=False)] = True
                        out += sim(s, f, pick if d == 1 else zero, pick if d == -1 else zero)
            print(line(f"{grp} {dl}: script signals", sig))
            print(line(f"{grp} {dl}: random bars", rnd))
            print(line(f"{grp} {dl}: random bars while score = 7", rnd7))

    print("\n[2] script signals with the script's Auto cost, by asset class and direction, 4H + 1D")
    tr = []
    for s in uni:
        t, _ = rl.run_series(s, None, PURE, None, None, feats[s.name])
        tr.extend(t)
    for a in ("metal", "energy", "fx", "index", "stock", "crypto"):
        for d, dl in ((1, "long"), (-1, "short")):
            print(cells(f"{a} {dl}", [t for t in tr if t["asset"] == a and t["dir"] == d and t["tf"] in ("4h", "1D")]))

    print("\n[3] intraday (5m, 15m, 1h), zero cost: by timeframe and direction")
    tr0 = []
    for s in uni:
        if s.tf in ("5m", "15m", "1h"):
            t, _ = rl.run_series(s, None, PURE, 0.0, None, feats[s.name])
            tr0.extend(t)
    for tf in ("5m", "15m", "1h"):
        for d, dl in ((1, "long"), (-1, "short")):
            print(cells(f"{tf} {dl}", [t for t in tr0 if t["tf"] == tf and t["dir"] == d]))
    print("\n[4] intraday, zero cost, non-crypto: by UTC hour of the entry bar")
    nc = [t for t in tr0 if t["asset"] != "crypto"]
    for lo, hi, name in ((22, 24, "22-24"), (0, 6, "00-06"), (6, 9, "06-09 London open"), (9, 12, "09-12"),
                         (12, 15, "12-15 NY open"), (15, 18, "15-18"), (18, 22, "18-22")):
        print(cells(name, [t for t in nc if lo <= dt.datetime.fromtimestamp(t["t"], dt.UTC).hour < hi]))
    print("\n[5] intraday, zero cost: by trigger")
    for g in ("BRK", "FLIP", "PB"):
        print(cells(g, [t for t in tr0 if t["trig"] == g]))


if __name__ == "__main__":
    main()
