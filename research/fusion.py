"""APEX Fusion signal logic (mirrors the Pine indicator)."""
import numpy as np, pandas as pd
from engine import *

PRIORITY = ["BRT", "ORB", "BRK", "EMA", "PB", "FLIP", "VWAP", "SWEEP", "DIV", "REB"]

def fusion_signals(df, F, P, cfg):
    """cfg keys: trend (list), rev (list), min_score, need_htf, need_daily, daily_neutral_ok, tsm,
       rev_gate ('daily'|'daily+htf')"""
    S = setups(F, P)
    N = F["N"]
    dtr = F.get("dtr")
    if dtr is None:
        dtr = F["dtr"] = htf_trend(df, 1440 if P.tf_minutes <= 60 else 10080, 21)
    L = np.zeros(N, bool); Sh = np.zeros(N, bool); lab = np.array([""] * N, dtype=object)
    for d in (1, -1):
        sc = F["scoreL"] if d == 1 else F["scoreS"]
        base = np.ones(N, bool)
        if cfg.get("need_daily", True):
            base &= (dtr == d) | ((dtr == 0) & cfg.get("daily_neutral_ok", False))
        tg = base & (sc >= cfg.get("min_score", 5))
        if cfg.get("need_htf", True):
            tg &= F["htf"] == d
        if cfg.get("tsm") is not None:
            tg &= np.nan_to_num(F["tsm"] * d, nan=-9) >= cfg["tsm"]
        rg = base & (F["htf"] != -d) if cfg.get("rev_gate", "daily+htf") == "daily+htf" else base
        for k in PRIORITY:
            if k in cfg.get("trend", []):
                s = S[k][0 if d == 1 else 1] & tg
            elif k in cfg.get("rev", []):
                s = S[k][0 if d == 1 else 1] & rg
            else:
                continue
            new = s & (lab == "")
            lab[new] = k
            if d == 1: L |= new
            else: Sh |= new
    # a bar with both directions keeps neither (conflict)
    both = L & Sh
    L &= ~both; Sh &= ~both
    return L, Sh, lab
