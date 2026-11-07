"""Out-of-sample validation of the frozen config + baselines. Writes results/*.csv and prints tables."""
import json, numpy as np, pandas as pd
from engine import *
from final_config import signals, PROFILES, cost_for
from baseline import apex_original, gbb_original, APEX_P, GBB_P
from pathlib import Path
OUT = Path(__file__).resolve().parent / "results"; OUT.mkdir(exist_ok=True)

def win(trades, F, a, b):
    ta = pd.Timestamp(a).timestamp() if a else -1; tb = pd.Timestamp(b).timestamp() if b else 9e18
    return [t for t in trades if ta <= F["ts"][t.bar] < tb]

RUNS = [  # dataset, tf, asset, window-start, window-end, role
    ("XAUUSDT_15m", 15, "metal", "2026-06-01", None, "OOS gold 15m (Jun-Nov 2026)"),
    ("XAUUSDT_15m", 15, "metal", "2025-12-01", "2026-06-01", "IS gold 15m (Dec 2025-May 2026)"),
    ("XAUUSDT_15m", 15, "metal", None, None, "FULL gold 15m (Dec 2025-Nov 2026)"),
    ("PAXGUSDT_15m", 15, "metal", "2025-07-01", "2025-12-11", "OOS PAXG 15m (Jul-Dec 2025)"),
    ("PAXGUSDT_15m", 15, "metal", "2021-01-01", "2022-01-01", "OOS PAXG 15m (2021, thin data)"),
    ("PAXGUSDT_15m", 15, "metal", "2022-01-01", "2025-07-01", "IS PAXG 15m (2022-Jun 2025)"),
    ("XAUUSDT_5m", 5, "metal", None, None, "Cross-TF gold 5m (Dec 2025-Nov 2026)"),
    ("XAUUSDT_1h", 60, "metal", None, None, "Cross-TF gold 1h (Dec 2025-Nov 2026)"),
    ("GC_F_1h", 60, "metal", None, None, "Cross-TF COMEX GC 1h (Jun 2024-Nov 2026)"),
    ("PAXGUSDT_1h", 60, "metal", "2021-01-01", None, "Cross-TF PAXG 1h (2021-2026)"),
    ("XAGUSDT_15m", 15, "silver", None, None, "Cross-asset silver 15m (Jan-Nov 2026)"),
]
if __name__ == "__main__":
    rows = []; trades_dump = {}
    cache = {}
    for ds, tf, asset, a, b, role in RUNS:
        if ds not in cache:
            cache[ds] = load(ds)
        df = cache[ds]
        systems = [("Fusion HighWin", "fusion", PROFILES["HighWin"]), ("Fusion Balanced", "fusion", PROFILES["Balanced"]),
                   ("APEX original", "apex", APEX_P), ("GBB original", "gbb", GBB_P)]
        for sname, kind, kw in systems:
            P = Params(tf_minutes=tf, cost_pct=cost_for(asset), **kw)
            F = features(df, P)
            if kind == "fusion": L, S, lab = signals(df, F, P, asset)
            elif kind == "apex": L, S, lab = apex_original(F, P)
            else: L, S, lab = gbb_original(F, P)
            tr = win(simulate(F, P, L, S, lab), F, a, b)
            st = stats(tr)
            rows.append(dict(role=role, system=sname, **{k: st.get(k) for k in ["n","win","tp1","tp2","tp3","fullSL","avgR","netR","pf","maxDD","costR","long_n","long_avgR","short_n","short_avgR"]}))
            if kind == "fusion" and ds == "XAUUSDT_15m" and a is None:
                trades_dump[sname] = pd.DataFrame([dict(entry_time=pd.to_datetime(F["ts"][t.bar], unit="s"), exit_time=pd.to_datetime(F["ts"][t.exit_bar], unit="s"),
                    setup=t.setup, dir="BUY" if t.dir == 1 else "SELL", entry=round(t.entry, 2), stop=round(t.sl0, 2), tp1=round(t.tp1, 2), tp2=round(t.tp2, 2),
                    tp3=round(t.tp3, 2), hit_tp1=t.hit1, hit_tp2=t.hit2, hit_tp3=t.hit3, exit=t.reason, exit_px=round(t.exit_px, 2), R=round(t.R, 3)) for t in tr])
    R = pd.DataFrame(rows); R.to_csv(OUT / "validation.csv", index=False)
    for k, v in trades_dump.items(): v.to_csv(OUT / f"trades_gold15m_{k.split()[1]}.csv", index=False)
    pd.set_option("display.width", 250); pd.set_option("display.max_rows", 200)
    show = R.copy()
    for c in ["win","tp1","tp2","tp3","fullSL"]: show[c] = (show[c]*100).round(1)
    for c in ["avgR","netR","pf","maxDD","costR","long_avgR","short_avgR"]: show[c] = show[c].astype(float).round(3)
    print(show[["role","system","n","win","tp1","tp2","tp3","fullSL","avgR","netR","pf","maxDD","long_n","long_avgR","short_n","short_avgR"]].to_string(index=False))
