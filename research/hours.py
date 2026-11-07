import numpy as np, pandas as pd
from engine import *
from experiments import shadow_outcomes, CACHE
from fusion import PRIORITY
sets = [("PAXGUSDT_15m","2022-01-01","2025-07-01",15),("XAUUSDT_15m","2025-12-01","2026-06-01",15)]
df = load("GC_F_1h"); P = Params(tf_minutes=60); F = features(df, P); S = setups(F, P); F["dtr"] = htf_trend(df, 1440, 21)
CACHE["GC_F_1h"] = (df, F, S); sets.append(("GC_F_1h","2024-07-01","2026-06-01",60))
TREND = ["BRT","ORB","BRK","EMA","PB","FLIP","VWAP"]
rows = []
for name, a, b, tf in sets:
    df, F, S = CACHE[name]; P = Params(tf_minutes=tf)
    ta_, tb_ = pd.Timestamp(a).timestamp(), pd.Timestamp(b).timestamp()
    for k in TREND:
        for d in (1, -1):
            sc = F["scoreL"] if d == 1 else F["scoreS"]
            sig = S[k][0 if d==1 else 1] & (F["dtr"] == d) & (sc >= 5) & (F["htf"] == d)
            if tf < 60: sig &= (F["slL"] if d==1 else F["slS"]) >= 0.03/100*F["c"]/0.07
            for (i, j, r) in shadow_outcomes(F, P, sig, d):
                if ta_ <= F["ts"][i] < tb_ and i >= 250:
                    rows.append(dict(data=name[:4], setup=k, d=d, hour=F["hour_ny"][i], R=r))
T = pd.DataFrame(rows)
T["hb"] = pd.cut(T.hour, [-1,1,4,7,9,11,13,16,23], labels=["18-01","02-04","05-07","08-09","10-11","12-13","14-16","17-23"])
pd.set_option("display.width",200)
print(T.groupby(["hb","data"],observed=True).agg(n=("R","size"),avgR=("R","mean")).round(3).unstack(1).to_string())
T["sess"] = np.where((T.hour>=8)&(T.hour<17), "US08-16", "other")
print(T.groupby(["setup","sess","data"]).agg(n=("R","size"),avgR=("R","mean")).round(3).unstack(2).to_string())
