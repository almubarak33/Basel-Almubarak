"""Can APEX Fusion run as a bot on gold? Re-test with bot-realistic execution:
market entry at the next candle's open (not the signal close, not a touched limit), costs per venue."""
import numpy as np, pandas as pd
from engine import *
import final_config as v1
import final_config_v2 as v2
from validate_v2 import win

RUNS = [("XAUUSDT_1h", 60, None, None, "gold 1h (XAUUSDT, Dec25-Nov26)"),
        ("GC_F_1h", 60, None, None, "COMEX 1h (Jun24-Nov26)"),
        ("PAXGUSDT_1h", 60, "2021-01-01", None, "PAXG 1h (2021-2026)"),
        ("XAUUSDT_15m", 15, None, None, "gold 15m (Dec25-Nov26)"),
        ("XAUUSDT_5m", 5, None, None, "gold 5m (Dec25-Nov26)")]
COSTS = [("spot CFD 0.01%", 0.01), ("0.03%", 0.03), ("Binance taker 0.12%", 0.12)]
rows = []
for ds, tf, a, b, desc in RUNS:
    df = load(ds)
    for prof in ["HighWin", "Balanced"]:
        for cname, cost in COSTS:
            if tf >= 60:
                P = Params(tf_minutes=tf, cost_pct=cost, entry_mode="next_open", pb_bars=1, **v2.PROFILES[prof])
                F = features(df, P); L, S, lab = v1.signals(df, F, P, "metal")
            else:
                P = v2.params(tf, prof, "gold", cost=cost, entry_mode="next_open", pb_bars=1)
                P.small_guard = True
                F = features(df, P); L, S, lab = v2.signals(df, F, P)
            R = np.array([t.R for t in win(simulate(F, P, L, S, lab), F, a, b)])
            if len(R) == 0: continue
            rows.append(dict(data=desc, profile=prof, cost=cname, n=len(R), win=round((R > 0).mean() * 100, 1),
                             avgR=round(R.mean(), 3), se=round(R.std(ddof=1) / np.sqrt(len(R)), 3),
                             pf=round(R[R > 0].sum() / -R[R < 0].sum(), 2)))
T = pd.DataFrame(rows); T.to_csv("results/bot_gold_check.csv", index=False)
pd.set_option("display.width", 200); print(T.to_string(index=False))
