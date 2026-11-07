import numpy as np, pandas as pd
from engine import *
import final_config_v2 as v2
from validate_v2 import win
SETS = [("XAUUSDT_5m", 5, "2026-06-01", None, "OOS gold 5m"), ("XAUUSDT_15m", 15, "2026-06-01", None, "OOS gold 15m"),
        ("PAXGUSDT_5m", 5, "2025-07-01", "2025-12-11", "OOS PAXG 5m"), ("PAXGUSDT_15m", 15, "2025-07-01", "2025-12-11", "OOS PAXG 15m"),
        ("XAUUSDT_5m", 5, "2025-12-01", "2026-06-01", "IS gold 5m"), ("XAUUSDT_15m", 15, "2025-12-01", "2026-06-01", "IS gold 15m"),
        ("PAXGUSDT_5m", 5, "2023-01-01", "2025-07-01", "IS PAXG 5m"), ("PAXGUSDT_15m", 15, "2022-01-01", "2025-07-01", "IS PAXG 15m"),
        ("XAUUSDT_5m", 5, None, None, "FULL gold 5m"), ("XAUUSDT_15m", 15, None, None, "FULL gold 15m")]
PROFS = {"HighWin 0.5/2/5": v2.PROFILES["HighWin"],
         "MaxWin 0.3(60%)/1/3": dict(k1=0.3, w1=0.6, k2=1.0, w2=0.2, k3=3.0, be_on=True, lock_tp2=True, trail_on=False, max_bars=0),
         "MaxWin 0.4(60%)/1.5/4": dict(k1=0.4, w1=0.6, k2=1.5, w2=0.2, k3=4.0, be_on=True, lock_tp2=True, trail_on=False, max_bars=0)}
cache = {}; rows = []
for ds, tf, a, b, role in SETS:
    if ds not in cache:
        df = load(ds); P0 = v2.params(tf, "HighWin"); cache[ds] = (df, features(df, P0))
    df, F = cache[ds]
    for pname, pk in PROFS.items():
        kw = dict(pk); kw.update(v2.EXEC)
        P = Params(tf_minutes=tf, htf_minutes=240, cost_pct=0.01, **kw)
        L, S, lab = v2.signals(df, F, P)
        st = stats(win(simulate(F, P, L, S, lab), F, a, b))
        rows.append(dict(window=role, profile=pname, n=st["n"], win=round(st["win"]*100, 1), avgR=round(st["avgR"], 3), pf=round(st["pf"], 2)))
R = pd.DataFrame(rows); R.to_csv("results/maxwin_check.csv", index=False)
pd.set_option("display.width", 200)
print(R.pivot_table(index="window", columns="profile", values=["win", "avgR", "pf"], sort=False).to_string())
