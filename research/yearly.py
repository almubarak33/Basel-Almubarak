import sys, numpy as np, pandas as pd
from engine import *
from fusion import fusion_signals
cfg = dict(trend=["BRT","ORB","BRK","EMA","PB","FLIP","VWAP"])
kw = dict(k1=0.5, w1=0.5, k2=1.5, w2=0.25, k3=4.0, be_on=True, trail_on=True, trail_from=1)
for name, tf in [("PAXGUSDT_15m",15), ("XAUUSDT_15m",15), ("GC_F_1h",60), ("PAXGUSDT_1h",60)]:
    df = load(name); P = Params(tf_minutes=tf, **kw); F = features(df, P)
    L, S, lab = fusion_signals(df, F, P, cfg)
    tr = simulate(F, P, L, S, lab)
    yrs = pd.to_datetime([F["ts"][t.bar] for t in tr], unit="s")
    T = pd.DataFrame(dict(y=yrs.year if tf==60 or "PAXG" in name else yrs.to_period("Q").astype(str), R=[t.R for t in tr], w=[t.R>0 for t in tr], d=[t.dir for t in tr]))
    print(name); print(T.groupby("y").agg(n=("R","size"), win=("w","mean"), avgR=("R","mean"), net=("R","sum"), longs=("d", lambda x: (x==1).mean())).round(3).to_string())
