#!/usr/bin/env python3
"""Can an extra entry filter raise the hit rate?  Quintile analysis of 15 entry features.

Long signals on 4H + 1D (the only place the script shows an edge), pure 1R:1R bracket with the script's
cost.  Quintile cut points come from TRAIN only; a real effect must be monotonic in TRAIN and repeat in
TEST (unseen periods + unseen instruments).
Usage: python3 study_filters.py [tf,tf]
"""
import sys

import numpy as np

import research_lib as rl

E = rl.E
PURE = {"k1": 1.0, "k2": 2.0, "k3": 3.0, "w1": 1.0, "w2": 0.0, "trailOn": False, "trailFrom": 1, "beOn": False}


def roll_mean(x, w):
    out = np.full(len(x), np.nan)
    cs = np.cumsum(np.nan_to_num(x))
    out[w - 1:] = (cs[w - 1:] - np.concatenate([[0], cs[:-w]])) / w
    return out


def pct_rank(x, w):
    out = np.full(len(x), np.nan)
    for i in range(w, len(x)):
        out[i] = (x[i - w + 1:i + 1] <= x[i]).mean()
    return out


def main():
    tfs = tuple(sys.argv[1].split(",")) if len(sys.argv) > 1 else ("4h", "1D")
    params = rl.with_params(dirMode="Long only")
    rows = []
    for s in rl.universe(tfs=tfs):
        f = E.features(s.chart, s.htf, params, s.market, s.base)
        c = s.chart
        o, h, l, cl, v = c["o"], c["h"], c["l"], c["c"], c["v"]
        atr = f["atr"]
        rngb = np.where(h > l, h - l, 1.0)
        age = np.zeros(s.n)
        st = f["stDir"]
        for i in range(1, s.n):
            age[i] = age[i - 1] + 1 if (st[i] < 0 and st[i - 1] < 0) else 0
        with np.errstate(divide="ignore", invalid="ignore"):
            feat = {
                "ext_ema21": (cl - f["ema21"]) / atr, "ext_ema200": (cl - f["ema200"]) / atr, "adx": f["adx"],
                "rsi": f["rsi14"], "atr_rank250": pct_rank(atr / cl, 250), "stop_in_atr": f["slDistL"] / atr,
                "bar_range": (h - l) / atr, "body": np.where(h > l, (cl - o) / rngb, 0.0),
                "close_pos": np.where(h > l, (cl - l) / rngb, 0.5),
                "mom20": (cl - np.concatenate([np.full(20, np.nan), cl[:-20]])) / atr,
                "breakout_size": (cl - f["donHi"]) / atr, "volume_ratio": v / roll_mean(v, 20),
                "trend_age": age, "di_spread": f["diP"] - f["diM"], "ema_gap": (f["ema21"] - f["ema55"]) / atr,
            }
        trades, _ = rl.run_series(s, params, PURE, None, None, f)
        for t in trades:
            t["f"] = {k: float(a[t["entry_bar"]]) for k, a in feat.items()}
            rows.append(t)
    train, test = rl.cell(rows, "TRAIN"), rl.cell(rows, "TEST")
    print(f"{tfs}: {len(rows)} long trades; TRAIN={len(train)} TEST={len(test)}")
    base_tr = np.mean([t["R"] > 0 for t in train])
    base_te = np.mean([t["R"] > 0 for t in test])
    print(f"baseline win rate: TRAIN {100*base_tr:.1f}%  TEST {100*base_te:.1f}%")
    for k in rows[0]["f"]:
        x = np.array([t["f"][k] for t in train])
        ok = np.isfinite(x)
        if ok.sum() < 100:
            continue
        qs = np.quantile(x[ok], [0.2, 0.4, 0.6, 0.8])
        print(f"{k:14s} TRAIN quintile cuts: " + ", ".join(f"{q:.2f}" for q in qs))
        for name, grp in (("TRAIN", train), ("TEST ", test)):
            out = f"   {name}"
            for b in range(5):
                sub = [t["R"] for t in grp if np.isfinite(t["f"][k]) and int(np.searchsorted(qs, t["f"][k], side="right")) == b]
                if sub:
                    r = np.array(sub)
                    out += f" | Q{b+1} n={len(r):4d} win={100*(r > 0).mean():4.1f}%"
            print(out)


if __name__ == "__main__":
    main()
