"""Frozen APEX Fusion Pro defaults (chosen on in-sample data only)."""
import numpy as np
from engine import *
from fusion import PRIORITY

TREND = ["BRT", "ORB", "BRK", "EMA", "PB", "FLIP", "VWAP"]   # entry setups enabled by default
REV = ["SWEEP", "DIV", "REB"]                                # available, off by default (negative in IS)

PROFILES = {
    # default: high win-rate — TP1 0.5R closes 50%, stop to breakeven, TP2 2R closes 25%, runner to 5R
    "HighWin": dict(k1=0.5, w1=0.5, k2=2.0, w2=0.25, k3=5.0, be_on=True, lock_tp2=True, trail_on=False, max_bars=0),
    # alternative: higher expectancy — TP1 1R 50%, TP2 3R 25%, runner to 5R
    "Balanced": dict(k1=1.0, w1=0.5, k2=3.0, w2=0.25, k3=5.0, be_on=True, lock_tp2=True, trail_on=False, max_bars=0),
}

def anchor_minutes(tf):
    return 1440 if tf <= 60 else 10080 if tf <= 240 else 43200  # same as Pine autoAnchor()

def session_ok(F, asset, tf=15):
    if asset == "crypto" or tf >= 240:  # Pine: session filter only on intraday charts below 4H
        return np.ones(F["N"], bool)
    h = F["hour_ny"]
    return (h >= 8) & (h < 17)

def signals(df, F, P, asset="metal", trend=TREND, rev=(), min_score=5, use_session=True):
    S = setups(F, P)
    N = F["N"]
    if "anchor" not in F:
        F["anchor"] = htf_trend(df, anchor_minutes(P.tf_minutes), 21)
    sess = session_ok(F, asset, P.tf_minutes) if use_session else np.ones(N, bool)
    L = np.zeros(N, bool); Sh = np.zeros(N, bool); lab = np.array([""] * N, dtype=object)
    for d in (1, -1):
        sc = F["scoreL"] if d == 1 else F["scoreS"]
        base = (F["anchor"] == d) & sess
        tg = base & (sc >= min_score) & (F["htf"] == d)
        rg = base & (F["htf"] != -d)
        for k in PRIORITY:
            if k in trend: s = S[k][0 if d == 1 else 1] & tg
            elif k in rev: s = S[k][0 if d == 1 else 1] & rg
            else: continue
            new = s & (lab == "")
            lab[new] = k
            if d == 1: L |= new
            else: Sh |= new
    both = L & Sh
    return L & ~both, Sh & ~both, lab

def cost_for(asset):
    return {"crypto": 0.10, "silver": 0.06}.get(asset, 0.03)
