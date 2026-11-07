"""Sensitivity of the frozen config to the 4H bar anchor (18:00 NY CME-style vs 17:00 NY OANDA-style)."""
import pandas as pd
import engine
from engine import *
from final_config import signals, PROFILES, cost_for
from validate import win
rows = []
for name, tf, a, b, role in [("XAUUSDT_15m", 15, "2026-06-01", None, "gold 15m OOS"), ("XAUUSDT_15m", 15, None, None, "gold 15m full"),
                             ("XAUUSDT_1h", 60, None, None, "gold 1h"), ("PAXGUSDT_1h", 60, None, None, "PAXG 1h 2021-26"),
                             ("PAXGUSDT_15m", 15, "2025-07-01", "2025-12-11", "PAXG 15m OOS")]:
    df = load(name)
    for hour in (18, 17):
        engine.HTF_START_HOUR = hour
        for prof in ("Balanced", "HighWin"):
            P = Params(tf_minutes=tf, cost_pct=cost_for("metal"), **PROFILES[prof]); F = features(df, P)
            L, S, lab = signals(df, F, P); s = stats(win(simulate(F, P, L, S, lab), F, a, b))
            rows.append(dict(data=role, anchor=f"{hour}:00", profile=prof, n=s["n"], win=round(s["win"]*100, 1), avgR=round(s["avgR"], 3), pf=round(s["pf"], 2)))
R = pd.DataFrame(rows); R.to_csv("results/htf_alignment_check.csv", index=False)
print(R.pivot_table(index=["data", "profile"], columns="anchor", values=["n", "win", "avgR", "pf"]).to_string())
