"""Feature decomposition of trend-setup trades on the IS windows (BAL management, s5 gate)."""
import numpy as np, pandas as pd
from engine import *
from research_is import IS, MGMT, window, gate

def zone_room(F, P):
    """Distance from close to the nearest opposing confirmed pivot zone (APEX zones, 3 per side)."""
    c, a, N = F["c"], F["atr"], F["N"]
    res, sup = [], []
    roomL = np.full(N, np.inf); roomS = np.full(N, np.inf)
    for i in range(N):
        if not np.isnan(F["ph10"][i]): res.append(F["ph10"][i]); res[:] = res[-P.zone_count:]
        if not np.isnan(F["pl10"][i]): sup.append(F["pl10"][i]); sup[:] = sup[-P.zone_count:]
        above = [r - 0.15 * a[i] - c[i] for r in res if r - 0.15 * a[i] > c[i]]
        below = [c[i] - (s + 0.15 * a[i]) for s in sup if s + 0.15 * a[i] < c[i]]
        if above: roomL[i] = min(above)
        if below: roomS[i] = min(below)
    return roomL, roomS

rows = []
for name, a, b in IS:
    df = load(name)
    P = Params(tf_minutes=15, **MGMT["BAL"])
    F = features(df, P); S = setups(F, P)
    roomL, roomS = zone_room(F, P)
    dtrend = htf_trend(df, 1440, 21)
    atrMed = pd.Series(F["atr"]).rolling(500, min_periods=100).median().to_numpy()
    for setup in ["BRK","FLIP","PB","EMA","BRT","ORB","VWAP"]:
        L = S[setup][0] & gate(F, 1, "s5"); Sh = S[setup][1] & gate(F, -1, "s5")
        tr = window(simulate(F, P, L, Sh, np.array([setup]*F["N"], object)), F, a, b)
        for t in tr:
            i, d = t.bar, t.dir
            rows.append(dict(data=name[:4], setup=setup, dir=d, R=t.R, tp1=t.hit1, hour=F["hour_ny"][i],
                             chop=F["chop"][i], adx=F["adx"][i], volx=F["atr"][i]/atrMed[i],
                             ext=(F["c"][i]-F["ema21"][i])/F["atr"][i]*d, rsi=(F["rsi"][i]-50)*d,
                             tsm=F["tsm"][i]*d, vw=np.sign(F["c"][i]-F["vwap"][i])*d, dtr=dtrend[i]*d,
                             room=(roomL[i] if d==1 else roomS[i])/t.risk, score=(F["scoreL"] if d==1 else F["scoreS"])[i],
                             riskatr=t.risk/F["atr"][i], volr=F["v"][i]/F["volMa"][i]))
T = pd.DataFrame(rows); T.to_csv("out_is_trades.csv", index=False)
pd.set_option("display.width", 220)
def show(col, bins=None, q=None):
    x = T.copy()
    if q: x[col] = pd.qcut(x[col], q, duplicates="drop")
    elif bins is not None: x[col] = pd.cut(x[col], bins)
    g = x.groupby(["data", col], observed=True).agg(n=("R","size"), avgR=("R","mean"), tp1=("tp1","mean")).round(3)
    print(g.unstack(0).to_string(), "\n")
print("ALL", T.groupby("data").agg(n=("R","size"), avgR=("R","mean"), tp1=("tp1","mean")).round(3).to_string(), "\n")
show("dir"); show("hour", bins=[-1,2,7,11,16,23]); show("chop", q=4); show("adx", q=4); show("volx", q=4)
show("ext", q=5); show("rsi", q=4); show("tsm"); show("vw"); show("dtr"); show("room", bins=[-0.01,0.5,1,2,4,np.inf]); show("score"); show("riskatr", q=4); show("volr", q=4)
