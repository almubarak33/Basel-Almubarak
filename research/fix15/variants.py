"""Entry / filter / target variants for APEX Fusion below 1H (gold 15m). Selection on in-sample windows only.
Entries are realistic unless marked: E_touch (limit filled on a touch) is shown for reference only."""
import sys
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from engine import load, features, setups, simulate, htf_trend, Params
from final_config import TREND, anchor_minutes
from fusion import PRIORITY
from diagnose import zigzag

WINDOWS = {
    "IS": [("XAUUSDT_15m", "2025-12-01", "2026-06-01"), ("PAXGUSDT_15m", "2023-01-01", "2025-07-01")],
    "OOS": [("XAUUSDT_15m", "2026-06-01", None), ("PAXGUSDT_15m", "2025-07-01", "2025-12-11")],
}
ENTRIES = {
    "E_touch": dict(entry_mode="pullback", pb_frac=0.33, pb_bars=3, fill_through=0.0),
    "E_limit": dict(entry_mode="pullback", pb_frac=0.33, pb_bars=3, fill_through=0.05),
    "E_market": dict(entry_mode="next_open", pb_bars=1),
    "E_stop": dict(entry_mode="stop", stop_off=0.0, pb_bars=2),
}
GATES = {
    "G_cur": dict(hours=(8, 17), anchor="strict", okbar=True, score=5),
    "G_ldn": dict(hours=(3, 17), anchor="strict", okbar=True, score=5),
    "G_anc": dict(hours=(8, 17), anchor="not_against", okbar=True, score=5),
    "G_ldn_anc": dict(hours=(3, 17), anchor="not_against", okbar=True, score=5),
    "G_nobar": dict(hours=(8, 17), anchor="strict", okbar=False, score=5),
}
MGMT = {
    "MW 0.4/1.5/4": dict(k1=0.4, w1=0.6, k2=1.5, w2=0.2, k3=4.0, be_on=True, lock_tp2=True, trail_on=False, be_at=0.0),
    "HW 0.5/2/5": dict(k1=0.5, w1=0.5, k2=2.0, w2=0.25, k3=5.0, be_on=True, lock_tp2=True, trail_on=False, be_at=0.0),
    "BAL 1/3/5": dict(k1=1.0, w1=0.5, k2=3.0, w2=0.25, k3=5.0, be_on=True, lock_tp2=True, trail_on=False, be_at=0.0),
    "MW be@1R": dict(k1=0.4, w1=0.6, k2=1.5, w2=0.2, k3=4.0, be_on=True, lock_tp2=True, trail_on=False, be_at=1.0),
    "HW be@1R": dict(k1=0.5, w1=0.5, k2=2.0, w2=0.25, k3=5.0, be_on=True, lock_tp2=True, trail_on=False, be_at=1.0),
    "TR 1/2/6+trail": dict(k1=1.0, w1=0.5, k2=2.0, w2=0.25, k3=6.0, be_on=True, lock_tp2=True, trail_on=True, trail_from=1, be_at=0.0),
    "RUN 0.5/2/8+trail": dict(k1=0.5, w1=0.4, k2=2.0, w2=0.3, k3=8.0, be_on=True, lock_tp2=True, trail_on=True, trail_from=2, be_at=0.0),
}


def gated(df, F, S, g):
    N = F["N"]
    hr = F["hour_ny"]
    sess = (hr >= g["hours"][0]) & (hr < g["hours"][1])
    okBar = (F["h"] - F["l"]) <= 2.5 * F["atr"] if g["okbar"] else np.ones(N, bool)
    L = np.zeros(N, bool); Sh = np.zeros(N, bool); lab = np.array([""] * N, dtype=object)
    for d in (1, -1):
        sc = F["scoreL"] if d == 1 else F["scoreS"]
        anc = (F["anchor"] == d) if g["anchor"] == "strict" else (F["anchor"] != -d)
        tg = anc & sess & (sc >= g["score"]) & (F["htf"] == d) & okBar
        for k in PRIORITY:
            if k not in TREND: continue
            new = S[k][0 if d == 1 else 1] & tg & (lab == "")
            lab[new] = k
            if d == 1: L |= new
            else: Sh |= new
    return L, Sh, lab


def metrics(T, F, legs, a_idx, b_idx):
    R = np.array([t.R for t in T], float)
    if len(R) == 0:
        return dict(n=0)
    eq = np.cumsum(R)
    dd = np.max(np.maximum.accumulate(eq) - eq)
    eb = {1: np.array([t.bar for t in T if t.dir == 1]), -1: np.array([t.bar for t in T if t.dir == -1])}
    caught = 0
    for s, e, d in legs:
        w_end = s + max(1, (e - s) // 2) + 3
        x = eb[d]
        caught += bool(len(x) and ((x >= s) & (x <= w_end)).any())
    return dict(n=len(R), win=(R > 0).mean(), avgR=R.mean(), se=R.std(ddof=1) / np.sqrt(len(R)) if len(R) > 1 else np.nan,
                totR=R.sum(), pf=R[R > 0].sum() / max(1e-9, -R[R < 0].sum()), ddR=dd,
                tp2=np.mean([t.hit2 for t in T]), legs=caught / max(1, len(legs)))


def job(args):
    win, ds, a, b, gname = args
    df = load(ds)
    base = Params(tf_minutes=15, htf_minutes=240, cost_pct=0.01, min_stop_pct=0.43)
    F = features(df, base)
    F["anchor"] = htf_trend(df, anchor_minutes(15), 21)
    S = setups(F, base)
    L, Sh, lab = gated(df, F, S, GATES[gname])
    ts = F["ts"]
    a_idx = int(np.searchsorted(ts, pd.Timestamp(a).timestamp())) if a else 0
    b_idx = int(np.searchsorted(ts, pd.Timestamp(b).timestamp())) if b else F["N"]
    legs = [(s, e, d) for s, e, d in zigzag(F["h"], F["l"], 1.0) if a_idx <= s < b_idx and s >= 300]
    rows = []
    for en, ekw in ENTRIES.items():
        for mn, mkw in MGMT.items():
            P = replace(base, **ekw, **mkw)
            T = simulate(F, P, L, Sh, lab, start=max(a_idx, 0), end=b_idx)
            rows.append(dict(win_set=win, data=ds, gate=gname, entry=en, mgmt=mn, **metrics(T, F, legs, a_idx, b_idx)))
    return rows


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "IS"
    jobs = [(which, ds, a, b, g) for ds, a, b in WINDOWS[which] for g in GATES]
    with ProcessPoolExecutor(4) as ex:
        rows = [r for rs in ex.map(job, jobs) for r in rs]
    T = pd.DataFrame(rows)
    out = Path(__file__).resolve().parent / f"variants_{which}.csv"
    T.to_csv(out, index=False)
    print("saved", out, len(T))
