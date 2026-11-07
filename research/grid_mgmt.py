import itertools, numpy as np, pandas as pd
from engine import *
from fusion import fusion_signals
from research_is import IS, window
pd.set_option("display.width", 250); pd.set_option("display.max_rows", 300)
DATA = {}
for name, a, b in IS:
    df = load(name); P = Params(tf_minutes=15); F = features(df, P)
    DATA[name] = (df, F, a, b)
COMBOS = {
 "all7": dict(trend=["BRT","ORB","BRK","EMA","PB","FLIP","VWAP"]),
 "core4": dict(trend=["BRT","ORB","BRK","EMA"]),
 "core6": dict(trend=["BRT","ORB","BRK","EMA","PB","FLIP"]),
 "core6+rev": dict(trend=["BRT","ORB","BRK","EMA","PB","FLIP"], rev=["SWEEP","DIV","REB"]),
 "rev_only": dict(trend=[], rev=["SWEEP","DIV","REB"]),
}
rows = []
for cname, cfg in COMBOS.items():
    for (k1, w1, k2, k3, tr) in itertools.product([0.5, 0.75, 1.0], [0.5], [1.5, 2.5], [4.0, 8.0], ["off", "tp1", "tp2"]):
        kw = dict(k1=k1, w1=w1, k2=k2, w2=0.25, k3=k3, be_on=True, trail_on=tr != "off", trail_from=2 if tr == "tp2" else 1)
        rec = dict(combo=cname, k1=k1, w1=w1, k2=k2, k3=k3, trail=tr)
        for name, (df, F, a, b) in DATA.items():
            P = Params(tf_minutes=15, **kw)
            L, S, lab = fusion_signals(df, F, P, cfg)
            st = stats(window(simulate(F, P, L, S, lab), F, a, b))
            rec.update({f"{name[:4]}_n": st["n"], f"{name[:4]}_win": round(st["win"], 3), f"{name[:4]}_avgR": round(st["avgR"], 3), f"{name[:4]}_pf": round(st["pf"], 2)})
        rows.append(rec)
R = pd.DataFrame(rows)
R["minAvg"] = R[["PAXG_avgR", "XAUU_avgR"]].min(axis=1)
R.to_csv("out_grid_mgmt.csv", index=False)
print(R.sort_values("minAvg", ascending=False).head(40).to_string(index=False))
print()
print(R.groupby("combo")[["PAXG_avgR","XAUU_avgR","PAXG_win","XAUU_win","PAXG_n","XAUU_n"]].mean().round(3))
