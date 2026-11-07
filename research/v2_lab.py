"""v2 research lab: professional-technique variants on the IS windows, 5m and 15m."""
import pickle, time, numpy as np, pandas as pd
from pathlib import Path
from engine import *
from final_config import PROFILES, anchor_minutes, session_ok, cost_for
from fusion import PRIORITY

IS = [("PAXGUSDT_5m", 5, "2023-01-01", "2025-07-01"), ("XAUUSDT_5m", 5, "2025-12-01", "2026-06-01"),
      ("PAXGUSDT_15m", 15, "2022-01-01", "2025-07-01"), ("XAUUSDT_15m", 15, "2025-12-01", "2026-06-01")]
CACHE = Path(__file__).resolve().parent / ".cache"; CACHE.mkdir(exist_ok=True)
PRI = ["BRT", "ORB", "ABRK", "BRK", "EMA", "PB", "FLIP", "VWAP", "ASWP", "SWEEP", "DIV", "REB"]
TREND7 = ["BRT", "ORB", "BRK", "EMA", "PB", "FLIP", "VWAP"]

def get(name, tf):
    f = CACHE / f"{name}.pkl"
    if f.exists():
        return pickle.load(open(f, "rb"))
    df = load(name); P = Params(tf_minutes=tf); F = features(df, P); S = setups(F, P)
    F["anchor"] = htf_trend(df, anchor_minutes(tf), 21)
    pickle.dump((df, F, S), open(f, "wb"))
    return df, F, S

def build(F, S, tf, cfg):
    N = F["N"]; c, o, h, l, a = F["c"], F["o"], F["h"], F["l"], F["atr"]
    L = np.zeros(N, bool); Sh = np.zeros(N, bool); lab = np.array([""] * N, object)
    dL = F["slL"].copy(); dS = F["slS"].copy()
    hr = F["hour_ny"]
    sess = np.ones(N, bool)
    if cfg.get("session", (8, 17)):
        s0, s1 = cfg.get("session", (8, 17)); sess = (hr >= s0) & (hr < s1)
    if cfg.get("killzone"):
        kz = np.zeros(N, bool)
        for s0, s1 in cfg["killzone"]: kz |= (hr >= s0) & (hr < s1)
        sess = kz
    rng = h - l
    with np.errstate(divide="ignore", invalid="ignore"):
        body = np.abs(c - o) / np.where(rng > 0, rng, np.nan)
        posL = (c - l) / np.where(rng > 0, rng, np.nan); posS = (h - c) / np.where(rng > 0, rng, np.nan)
    for d in (1, -1):
        sc = F["scoreL"] if d == 1 else F["scoreS"]
        base = (F["anchor"] == d) & sess
        tg = base & (sc >= cfg.get("min_score", 5)) & (F["htf"] == d)
        q = np.ones(N, bool)
        if cfg.get("q_candle"): q &= (np.nan_to_num(body) >= 0.5) & (np.nan_to_num(posL if d == 1 else posS) >= 0.6)
        if cfg.get("q_range"): q &= rng <= cfg["q_range"] * a
        if cfg.get("q_ext"): q &= (c - F["ema21"]) * d <= cfg["q_ext"] * a
        for k in PRI:
            if k in cfg.get("trend", TREND7):
                s = S[k][0 if d == 1 else 1] & tg & q
            elif k == "ASWP" and "ASWP" in cfg.get("extra", []):
                g = (F["anchor"] == d) if cfg.get("aswp_gate", "daily") == "daily" else (F["anchor"] != -d)
                if cfg.get("aswp_htf"): g &= F["htf"] != -d
                s = S[k][0 if d == 1 else 1] & g
            else:
                continue
            new = s & (lab == "")
            lab[new] = k
            if k == "ASWP":
                if d == 1: dL[new] = np.clip(F["aswpStopL"][new], 0.8 * a[new], 3.5 * a[new])
                else: dS[new] = np.clip(F["aswpStopS"][new], 0.8 * a[new], 3.5 * a[new])
            if d == 1: L |= new
            else: Sh |= new
    return L, Sh, lab, dL, dS

def evaluate(cfg, prof, extra_kw=None, sets=IS, quiet=False, label=""):
    out = []
    for name, tf, a, b in sets:
        df, F, S = get(name, tf)
        kw = dict(PROFILES[prof]); kw.update(extra_kw or {})
        P = Params(tf_minutes=tf, cost_pct=cost_for("metal"), **kw)
        L, Sh, lab, dL, dS = build(F, S, tf, cfg)
        tr = simulate(F, P, L, Sh, lab, distL=dL, distS=dS)
        ta_, tb_ = pd.Timestamp(a).timestamp(), pd.Timestamp(b).timestamp()
        tr = [t for t in tr if ta_ <= F["ts"][t.bar] < tb_]
        st = stats(tr)
        out.append((name, tf, st))
    if not quiet:
        cells = [f"{n.split('_')[0][:4]}{tf:>2}m n={s.get('n',0):4d} w={s.get('win',0)*100:4.1f}% R={s.get('avgR',0):+.3f}" for n, tf, s in out]
        print(f"{label:34s}|" + " | ".join(cells), flush=True)
    return out

if __name__ == "__main__":
    t0 = time.time()
    for name, tf, a, b in IS: get(name, tf)
    print(f"features cached in {time.time()-t0:.0f}s")
