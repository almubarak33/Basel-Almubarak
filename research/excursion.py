"""For every aligned trend signal (independently): P(reach x·R before the stop), IS windows."""
import numpy as np, pandas as pd
from engine import *
from research_is import IS, gate

XS = [0.3, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0]
out = []
for name, a, b in IS:
    df = load(name); P = Params(tf_minutes=15); F = features(df, P); S = setups(F, P)
    dtr = htf_trend(df, 1440, 21)
    ta_, tb_ = pd.Timestamp(a).timestamp(), pd.Timestamp(b).timestamp()
    h, l, c, o = F["h"], F["l"], F["c"], F["o"]
    for setup in ["BRK","FLIP","PB","EMA","BRT","ORB","VWAP"]:
        for d in (1, -1):
            sig = S[setup][0 if d == 1 else 1] & gate(F, d, "s5") & (dtr == d)
            for i in np.where(sig)[0]:
                if i < 250 or not (ta_ <= F["ts"][i] < tb_): continue
                dist = F["slL"][i] if d == 1 else F["slS"][i]
                if dist < 0.03/100*c[i]/0.07: continue
                e = c[i]; stop = e - d*dist; mfe = 0.0; stopped = False; bars = 0
                for j in range(i+1, min(i+400, F["N"])):
                    if (l[j] <= stop) if d == 1 else (h[j] >= stop): stopped = True; break
                    mfe = max(mfe, ((h[j]-e) if d == 1 else (e-l[j]))/dist); bars = j - i
                out.append(dict(data=name[:4], setup=setup, dir=d, mfe=mfe, stopped=stopped))
X = pd.DataFrame(out)
for dname, g in X.groupby("data"):
    print(dname, "n=", len(g), " ".join(f"{x}R:{(g.mfe>=x).mean():.2f}" for x in XS))
    for d, gg in g.groupby("dir"):
        print("   dir", d, "n=", len(gg), " ".join(f"{x}R:{(gg.mfe>=x).mean():.2f}" for x in XS))
