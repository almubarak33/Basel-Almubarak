"""Supplementary tables for the report (frozen config, no tuning)."""
import json, numpy as np, pandas as pd
from engine import *
from final_config import signals, PROFILES, cost_for
from validate import win
OUT = Path(__file__).resolve().parent / "results"
pd.set_option("display.width", 220)

def run(df, tf, prof, cost=None, asset="metal"):
    P = Params(tf_minutes=tf, cost_pct=cost_for(asset) if cost is None else cost, **PROFILES[prof])
    F = features(df, P); L, S, lab = signals(df, F, P, asset)
    return F, simulate(F, P, L, S, lab)

g15 = load("XAUUSDT_15m")
res = {}
# 1) cost sensitivity
rows = []
for prof in ["Balanced", "HighWin"]:
    for cost in [0.0, 0.01, 0.02, 0.03, 0.05]:
        F, tr = run(g15, 15, prof, cost)
        for lab_, a, b in [("OOS Jun-Nov 2026", "2026-06-01", None), ("FULL Dec 2025-Nov 2026", None, None)]:
            s = stats(win(tr, F, a, b)); rows.append(dict(profile=prof, cost_pct=cost, window=lab_, n=s["n"], win=round(s["win"]*100, 1), avgR=round(s["avgR"], 3), netR=round(s["netR"], 1), pf=round(s["pf"], 2)))
C = pd.DataFrame(rows); C.to_csv(OUT / "cost_sensitivity.csv", index=False); print(C.to_string(index=False), "\n")
# 2) monthly + 3) per setup + exits, gold 15m full
mon = []; per = []; ex = []; eq = {}
for prof in ["Balanced", "HighWin"]:
    F, tr = run(g15, 15, prof)
    T = pd.DataFrame(dict(m=pd.to_datetime([F["ts"][t.bar] for t in tr], unit="s").to_period("M").astype(str), R=[t.R for t in tr], w=[t.R > 0 for t in tr],
                          s=[t.setup for t in tr], r=[t.reason for t in tr], tp1=[t.hit1 for t in tr], d=[t.dir for t in tr],
                          t=[int(F["ts"][t.exit_bar]) for t in tr]))
    M = T.groupby("m").agg(n=("R", "size"), win=("w", "mean"), netR=("R", "sum")).reset_index(); M["profile"] = prof; mon.append(M)
    Sx = T.groupby("s").agg(n=("R", "size"), win=("w", "mean"), tp1=("tp1", "mean"), avgR=("R", "mean"), netR=("R", "sum")).reset_index(); Sx["profile"] = prof; per.append(Sx)
    E = T.groupby("r").agg(n=("R", "size"), avgR=("R", "mean")).reset_index(); E["profile"] = prof; ex.append(E)
    eq[prof] = dict(t=T.t.tolist(), cum=np.round(np.cumsum(T.R), 3).tolist())
M = pd.concat(mon); M.to_csv(OUT / "monthly_gold15m.csv", index=False)
print(M.pivot(index="m", columns="profile", values=["n", "win", "netR"]).round(2).to_string(), "\n")
Sx = pd.concat(per); Sx.to_csv(OUT / "per_setup_gold15m.csv", index=False); print(Sx.round(3).to_string(index=False), "\n")
E = pd.concat(ex); print(E.round(3).to_string(index=False), "\n")
json.dump(eq, open(OUT / "equity_gold15m.json", "w"))
# 4) 4H cross-check (PAXG 2021-2026 and GC=F) — session filter off on 4H, anchor = weekly
for name in ["PAXGUSDT_1h", "GC_F_1h"]:
    d4 = resample(load(name), 240)
    for prof in ["Balanced", "HighWin"]:
        F, tr = run(d4, 240, prof)
        print(f"4H {name[:-3]:9s} {prof:8s} {fmt_stats(stats(tr))}")
