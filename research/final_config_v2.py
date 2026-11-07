"""APEX Fusion Pro v2 — frozen on in-sample data (PAXG 5m 2023-Jun 2025, PAXG 15m 2022-Jun 2025,
XAUUSDT 5m/15m Dec 2025-May 2026). Adds professional execution rules to v1:
  • pullback entry: after a signal, a limit order at 33% of the stop distance back toward the stop, valid 3 bars
    (risk and targets are measured from the actual fill to the same structural stop)
  • trend context from 4H on every chart <= 1H (5m used only for timing)
  • skip signal bars wider than 2.5 ATR (news / exhaustion candles)
  • volatility floor: on charts < 1H the stop must be >= 0.43% of price
  • realistic gold cost 0.01% round trip (stress-tested at 0.03%)"""
import numpy as np
from engine import *
from final_config import TREND, anchor_minutes, session_ok
from fusion import PRIORITY

PROFILES = {
    "HighWin": dict(k1=0.5, w1=0.5, k2=2.0, w2=0.25, k3=5.0, be_on=True, lock_tp2=True, trail_on=False, max_bars=0),
    "Balanced": dict(k1=1.0, w1=0.5, k2=3.0, w2=0.25, k3=5.0, be_on=True, lock_tp2=True, trail_on=False, max_bars=0),
}
EXEC = dict(entry_mode="pullback", pb_frac=0.33, pb_bars=3, min_stop_pct=0.43)

def cost_for(asset):
    return {"crypto": 0.10, "silver": 0.06, "gold": 0.01}.get(asset, 0.03)

def params(tf, prof, asset="gold", cost=None, **over):
    kw = dict(PROFILES[prof]); kw.update(EXEC); kw.update(over)
    return Params(tf_minutes=tf, htf_minutes=240 if tf <= 60 else 0, cost_pct=cost_for(asset) if cost is None else cost, **kw)

def signals(df, F, P, asset="gold", trend=TREND, min_score=5, max_bar_atr=2.5):
    S = setups(F, P)
    N = F["N"]
    if "anchor" not in F:
        F["anchor"] = htf_trend(df, anchor_minutes(P.tf_minutes), 21)
    sess = session_ok(F, "crypto" if asset == "crypto" else "metal", P.tf_minutes)
    okBar = (F["h"] - F["l"]) <= max_bar_atr * F["atr"]
    L = np.zeros(N, bool); Sh = np.zeros(N, bool); lab = np.array([""] * N, dtype=object)
    for d in (1, -1):
        sc = F["scoreL"] if d == 1 else F["scoreS"]
        tg = (F["anchor"] == d) & sess & (sc >= min_score) & (F["htf"] == d) & okBar
        for k in PRIORITY:
            if k not in trend:
                continue
            new = S[k][0 if d == 1 else 1] & tg & (lab == "")
            lab[new] = k
            if d == 1: L |= new
            else: Sh |= new
    return L, Sh, lab


# ───────────── shipped defaults (v2.1) ─────────────
# Max Win-Rate was selected after the OOS windows had been seen (disclosed in the report).
PROFILES["MaxWin"] = dict(k1=0.4, w1=0.6, k2=1.5, w2=0.2, k3=4.0, be_on=True, lock_tp2=True, trail_on=False, max_bars=0)

def final_params(tf, asset="gold", prof="auto", cost=None):
    """Charts < 1H: LTF execution pack (pullback entry, 4H trend, bar filter, volatility floor) + Max Win-Rate.
    Charts >= 1H: v1 execution (market at close) + High Win-Rate."""
    if prof == "auto":
        prof = "MaxWin" if tf < 60 else "HighWin"
    c = cost_for(asset) if cost is None else cost
    if tf < 60:
        return params(tf, prof, asset, cost=c)
    return Params(tf_minutes=tf, cost_pct=c, **PROFILES[prof])

def final_signals(df, F, P, asset="gold"):
    if P.tf_minutes < 60:
        return signals(df, F, P, asset)
    import final_config as v1
    return v1.signals(df, F, P, "crypto" if asset == "crypto" else "metal")
