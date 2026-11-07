"""Baselines: the two original indicators, unmodified defaults, on gold."""
import sys, time
import numpy as np
from engine import *

def apex_original(F, P):
    S = setups(F, P)
    trigL = S["BRK"][0] | S["FLIP"][0] | S["PB"][0]
    trigS = S["BRK"][1] | S["FLIP"][1] | S["PB"][1]
    tsm = F["tsm"]
    L = trigL & (F["scoreL"] >= 7) & (tsm >= 1)
    Sh = trigS & (F["scoreS"] >= 7) & (tsm <= -1)
    lab = np.where(S["BRK"][0] | S["BRK"][1], "BRK", np.where(S["FLIP"][0] | S["FLIP"][1], "FLIP", "PB"))
    return L, Sh, lab

def gbb_original(F, P):
    S = setups(F, P)
    names = ["VWAP", "EMA", "BRT", "SWEEP", "DIV", "ORB"]
    L = np.zeros(F["N"], bool); Sh = np.zeros(F["N"], bool); lab = np.array([""] * F["N"], dtype=object)
    for k in names:
        newL = S[k][0] & ~L & ~Sh; newS = S[k][1] & ~L & ~Sh & ~newL
        lab[newL | newS] = k
        L |= newL; Sh |= newS
    return L, Sh, lab

APEX_P = dict()  # defaults in Params are APEX defaults (HP profile)
GBB_P = dict(stop_mode="atr", stop_atr=1.2, k1=1.0, k2=2.0, k3=3.0, w1=0.0, w2=0.0, be_on=False, lock_tp2=False,
             trail_on=False, max_bars=60, reverse=False, small_guard=False, warm=0)

if __name__ == "__main__":
    for name, tf in [("XAUUSDT_15m", 15), ("PAXGUSDT_15m", 15), ("XAUUSDT_1h", 60), ("GC_F_1h", 60)]:
        df = load(name)
        for tag, fn, kw in [("APEX", apex_original, APEX_P), ("GBB", gbb_original, GBB_P)]:
            P = Params(tf_minutes=tf, **kw)
            t0 = time.time()
            F = features(df, P)
            L, S, lab = fn(F, P)
            tr = simulate(F, P, L, S, lab)
            print(f"{name:14s} {tag:5s} {fmt_stats(stats(tr))}  ({time.time()-t0:.1f}s)")
