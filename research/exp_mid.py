import numpy as np, pandas as pd
from engine import *
from final_config import signals, PROFILES
from research_is import window
SETS = [("PAXGUSDT_15m","2022-01-01","2025-07-01"),("XAUUSDT_15m","2025-12-01","2026-06-01")]
for name, a, b in SETS:
    df = load(name)
    for prof in ["HighWin","Balanced"]:
        P = Params(tf_minutes=15, **PROFILES[prof]); F = features(df, P)
        mid = htf_trend(df, 60, 50)
        L, S, lab = signals(df, F, P)
        base = stats(window(simulate(F, P, L, S, lab), F, a, b))
        L2, S2 = L & (mid == 1), S & (mid == -1)
        st2 = stats(window(simulate(F, P, L2, S2, lab), F, a, b))
        # alternative: 1H ema21>ema55 order
        print(f"{name[:4]} {prof:8s} base   {fmt_stats(base)}")
        print(f"{name[:4]} {prof:8s} +1H    {fmt_stats(st2)}")
