"""In-sample research: every setup x quality gate x management profile.
IS windows only: PAXG 2022-01..2025-06 and XAUUSDT 2025-12..2026-05."""
import itertools, sys
import numpy as np, pandas as pd
from engine import *

IS = [("PAXGUSDT_15m", "2022-01-01", "2025-07-01"), ("XAUUSDT_15m", "2025-12-01", "2026-06-01")]
MGMT = {
    "HP":  dict(k1=0.3, k2=1.5, k3=4.0, w1=0.5, w2=0.25, be_on=True, trail_on=True, trail_from=1),
    "BAL": dict(k1=1.0, k2=2.0, k3=3.0, w1=0.4, w2=0.3, be_on=True, trail_on=False),
    "R1":  dict(k1=1.0, k2=1.5, k3=2.0, w1=1.0, w2=0.0, be_on=False, trail_on=False),
}

def window(trades, F, a, b):
    ta, tb = pd.Timestamp(a).timestamp(), pd.Timestamp(b).timestamp()
    return [t for t in trades if ta <= F["ts"][t.bar] < tb]

def gate(F, d, kind):
    sc = F["scoreL"] if d == 1 else F["scoreS"]
    if kind == "none": return np.ones(F["N"], bool)
    if kind == "s5": return (sc >= 5) & (F["htf"] == d)
    if kind == "s6": return (sc >= 6) & (F["htf"] == d)
    if kind == "s7": return sc >= 7
    if kind == "notagainst": # reversal: HTF not opposed
        return F["htf"] != -d
    raise ValueError(kind)

if __name__ == "__main__":
    rows = []
    for name, a, b in IS:
        df = load(name)
        P0 = Params(tf_minutes=15)
        F = features(df, P0); S = setups(F, P0)
        for setup in SETUPS:
            for g in ["none", "notagainst", "s5", "s6", "s7"]:
                L = S[setup][0] & gate(F, 1, g); Sh = S[setup][1] & gate(F, -1, g)
                for m, kw in MGMT.items():
                    P = Params(tf_minutes=15, **kw)
                    tr = window(simulate(F, P, L, Sh, np.array([setup]*F["N"], object)), F, a, b)
                    st = stats(tr)
                    rows.append(dict(data=name[:4], setup=setup, gate=g, mgmt=m, **{k: st.get(k, np.nan) for k in ["n","win","tp1","avgR","pf","long_avgR","short_avgR"]}))
    R = pd.DataFrame(rows)
    R.to_csv("out_is_grid.csv", index=False)
    piv = R.pivot_table(index=["setup","gate"], columns=["mgmt","data"], values=["avgR"]).round(3)
    n = R[R.mgmt=="BAL"].pivot_table(index=["setup","gate"], columns="data", values="n")
    t1 = R[R.mgmt=="BAL"].pivot_table(index=["setup","gate"], columns="data", values="tp1").round(2)
    pd.set_option("display.width", 250); pd.set_option("display.max_rows", 200)
    print(pd.concat([piv, n.add_prefix("n_"), t1.add_prefix("tp1_")], axis=1).to_string())
