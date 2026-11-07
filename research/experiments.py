"""IS-only experiments: adaptive setup selection, regime switch, squeeze, session."""
import numpy as np, pandas as pd, sys
from engine import *
from fusion import PRIORITY
from research_is import IS, window

def shadow_outcomes(F, P, sig, d):
    """Every signal tracked independently: +1R / -1R (stop-first), returns list of (bar, exit_bar, R)."""
    h, l, c, N = F["h"], F["l"], F["c"], F["N"]
    sl = F["slL"] if d == 1 else F["slS"]
    out = []
    for i in np.where(sig)[0]:
        dist = sl[i]
        if np.isnan(dist) or dist <= 0: continue
        e = c[i]; stop = e - d * dist; tgt = e + d * dist; cost = P.cost_pct / 100 * e / dist
        for j in range(i + 1, min(i + 500, N)):
            if (l[j] <= stop) if d == 1 else (h[j] >= stop): out.append((i, j, -1 - cost)); break
            if (h[j] >= tgt) if d == 1 else (l[j] <= tgt): out.append((i, j, 1 - cost)); break
    return out

def adaptive_mask(F, P, sig, d, look=20, minn=8, thr=0.0):
    sh = shadow_outcomes(F, P, sig, d)
    exits = sorted([(j, r) for (_, j, r) in sh])
    mask = np.zeros(F["N"], bool)
    k = 0; hist = []
    for i in np.where(sig)[0]:
        while k < len(exits) and exits[k][0] < i:
            hist.append(exits[k][1]); k += 1
        recent = hist[-look:]
        mask[i] = len(recent) < minn or np.mean(recent) > thr
    return mask

def efficiency_ratio(c, n):
    ch = np.abs(c - shift(c, n)); vol = pd.Series(np.abs(c - shift(c))).rolling(n).sum().to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        return ch / vol

def run(cfg, kw, label=""):
    res = []
    for name, a, b in IS:
        df, F, S = CACHE[name]
        P = Params(tf_minutes=15, **kw)
        N = F["N"]; L = np.zeros(N, bool); Sh = np.zeros(N, bool); lab = np.array([""] * N, object)
        dtr = F["dtr"]
        for d in (1, -1):
            sc = F["scoreL"] if d == 1 else F["scoreS"]
            base = (dtr == d) if cfg.get("daily", True) else np.ones(N, bool)
            if cfg.get("session"): base &= (F["hour_ny"] >= cfg["session"][0]) & (F["hour_ny"] < cfg["session"][1])
            if cfg.get("squeeze"): base &= F["sqzRel"]
            tg = base & (sc >= cfg.get("min_score", 5)) & (F["htf"] == d)
            rg = base & (F["htf"] != -d)
            if cfg.get("regime"):
                er = F["er4h"]
                tg &= er >= cfg["regime"]; rg &= er < cfg["regime"]
            for k in PRIORITY:
                if k in cfg.get("trend", []): s = S[k][0 if d == 1 else 1] & tg
                elif k in cfg.get("rev", []): s = S[k][0 if d == 1 else 1] & rg
                else: continue
                if cfg.get("adaptive"): s &= adaptive_mask(F, P, s, d, *cfg["adaptive"])
                new = s & (lab == ""); lab[new] = k
                if d == 1: L |= new
                else: Sh |= new
        st = stats(window(simulate(F, P, L, Sh, lab), F, a, b))
        res.append(f"{name[:4]} n={st['n']:4d} win={st['win']*100:4.1f}% avgR={st['avgR']:+.3f} PF={st['pf']:.2f}")
    print(f"{label:38s} | " + " | ".join(res))

CACHE = {}
for name, a, b in IS:
    df = load(name); P = Params(tf_minutes=15); F = features(df, P); S = setups(F, P)
    F["dtr"] = htf_trend(df, 1440, 21)
    # 4H efficiency ratio of the previous completed 4H bar series (approx: 16 x 15m bars per 4H, 10 4H bars)
    F["er4h"] = shift(efficiency_ratio(F["c"], 160), 1)
    bbMid = sma(F["c"], 20); sd = pd.Series(F["c"]).rolling(20).std(ddof=0).to_numpy(); kc = atr(F["h"], F["l"], F["c"], 20)
    sq = (bbMid + 2 * sd < bbMid + 1.5 * kc) & (bbMid - 2 * sd > bbMid - 1.5 * kc)
    F["sqzRel"] = pd.Series(sq).rolling(10, min_periods=1).max().to_numpy().astype(bool)
    CACHE[name] = (df, F, S)

TREND = ["BRT", "ORB", "BRK", "EMA", "PB", "FLIP", "VWAP"]; REV = ["SWEEP", "DIV", "REB"]
R1 = dict(k1=1.0, w1=1.0, k2=1.5, w2=0.0, k3=2.0, be_on=False, trail_on=False)
HPx = dict(k1=0.5, w1=0.5, k2=1.5, w2=0.25, k3=4.0, be_on=True, trail_on=True, trail_from=1)
for mname, kw in [("R1", R1), ("HPx", HPx)]:
    print("== management", mname)
    run(dict(trend=TREND), kw, "trend daily (ref)")
    run(dict(trend=TREND, daily=False), kw, "trend no-daily")
    run(dict(trend=TREND, rev=REV), kw, "trend+rev daily")
    run(dict(trend=TREND, adaptive=(20, 8, 0.0)), kw, "trend daily adaptive20")
    run(dict(trend=TREND, rev=REV, adaptive=(20, 8, 0.0)), kw, "trend+rev daily adaptive20")
    run(dict(trend=TREND, rev=REV, daily=False, adaptive=(20, 8, 0.0)), kw, "trend+rev no-daily adaptive20")
    run(dict(trend=TREND, rev=REV, regime=0.3), kw, "regime ER0.3 trend/rev")
    run(dict(trend=TREND, rev=REV, regime=0.2), kw, "regime ER0.2 trend/rev")
    run(dict(trend=TREND, squeeze=True), kw, "trend daily squeeze-release")
    run(dict(trend=TREND, session=(3, 12)), kw, "trend daily session 03-12NY")
    run(dict(trend=TREND, session=(8, 17)), kw, "trend daily session 08-17NY")
    run(dict(trend=TREND, min_score=6), kw, "trend daily score6")
