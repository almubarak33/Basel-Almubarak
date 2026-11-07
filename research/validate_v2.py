"""Out-of-sample validation of v2 (frozen) vs v1 and the two originals. 5m and 15m are primary."""
import numpy as np, pandas as pd
from engine import *
import final_config as v1
import final_config_v2 as v2
from baseline import apex_original, gbb_original, APEX_P, GBB_P
from pathlib import Path
OUT = Path(__file__).resolve().parent / "results"

def win(trades, F, a, b):
    ta = pd.Timestamp(a).timestamp() if a else -1; tb = pd.Timestamp(b).timestamp() if b else 9e18
    return [t for t in trades if ta <= F["ts"][t.bar] < tb]

RUNS = [
    ("XAUUSDT_5m", 5, "2026-06-01", None, "OOS", "gold 5m Jun-Nov 2026"),
    ("XAUUSDT_15m", 15, "2026-06-01", None, "OOS", "gold 15m Jun-Nov 2026"),
    ("PAXGUSDT_5m", 5, "2025-07-01", "2025-12-11", "OOS", "PAXG 5m Jul-Dec 2025"),
    ("PAXGUSDT_15m", 15, "2025-07-01", "2025-12-11", "OOS", "PAXG 15m Jul-Dec 2025"),
    ("PAXGUSDT_15m", 15, "2021-01-01", "2022-01-01", "OOS", "PAXG 15m 2021 (thin data)"),
    ("XAUUSDT_5m", 5, "2025-12-01", "2026-06-01", "IS", "gold 5m Dec 2025-May 2026"),
    ("XAUUSDT_15m", 15, "2025-12-01", "2026-06-01", "IS", "gold 15m Dec 2025-May 2026"),
    ("PAXGUSDT_5m", 5, "2023-01-01", "2025-07-01", "IS", "PAXG 5m 2023-Jun 2025"),
    ("PAXGUSDT_15m", 15, "2022-01-01", "2025-07-01", "IS", "PAXG 15m 2022-Jun 2025"),
    ("XAUUSDT_5m", 5, None, None, "FULL", "gold 5m Dec 2025-Nov 2026"),
    ("XAUUSDT_15m", 15, None, None, "FULL", "gold 15m Dec 2025-Nov 2026"),
    ("XAUUSDT_1h", 60, None, None, "XTF", "gold 1h Dec 2025-Nov 2026"),
    ("GC_F_1h", 60, None, None, "XTF", "COMEX GC 1h Jun 2024-Nov 2026"),
    ("PAXGUSDT_1h", 60, None, None, "XTF", "PAXG 1h 2021-2026"),
    ("XAGUSDT_15m", 15, None, None, "XASSET", "silver 15m Jan-Nov 2026"),
]
if __name__ == "__main__":
    rows = []; cache = {}; dumps = {}
    for ds, tf, a, b, role, desc in RUNS:
        df = cache.setdefault(ds, load(ds))
        asset = "silver" if ds.startswith("XAG") else "gold"
        systems = [
            ("v2 HighWin", lambda: v2.params(tf, "HighWin", asset), "v2"),
            ("v2 Balanced", lambda: v2.params(tf, "Balanced", asset), "v2"),
            ("v2 HighWin @0.03% stress", lambda: v2.params(tf, "HighWin", asset, cost=0.03 if asset == "gold" else 0.08), "v2"),
            ("v2 Balanced @0.03% stress", lambda: v2.params(tf, "Balanced", asset, cost=0.03 if asset == "gold" else 0.08), "v2"),
            ("v1 HighWin", lambda: Params(tf_minutes=tf, cost_pct=v2.cost_for(asset), cg_max_pct=7.0 * v2.cost_for(asset) / 0.03, **v1.PROFILES["HighWin"]), "v1"),
            ("v1 Balanced", lambda: Params(tf_minutes=tf, cost_pct=v2.cost_for(asset), cg_max_pct=7.0 * v2.cost_for(asset) / 0.03, **v1.PROFILES["Balanced"]), "v1"),
            ("APEX original", lambda: Params(tf_minutes=tf, cost_pct=v2.cost_for(asset), cg_max_pct=7.0 * v2.cost_for(asset) / 0.03, **APEX_P), "apex"),
            ("GBB original", lambda: Params(tf_minutes=tf, cost_pct=v2.cost_for(asset), **GBB_P), "gbb"),
        ]
        Fc = {}
        for sname, mkP, kind in systems:
            P = mkP()
            key = (kind == "v2", P.stop_mode)
            if key not in Fc: Fc[key] = features(df, P)
            F = Fc[key]
            if kind == "v2": L, S, lab = v2.signals(df, F, P, asset)
            elif kind == "v1": L, S, lab = v1.signals(df, F, P, "metal")
            elif kind == "apex": L, S, lab = apex_original(F, P)
            else: L, S, lab = gbb_original(F, P)
            tr = win(simulate(F, P, L, S, lab), F, a, b)
            st = stats(tr)
            rows.append(dict(role=role, data=desc, system=sname, **{k: st.get(k) for k in ["n","win","tp1","tp2","tp3","fullSL","avgR","netR","pf","maxDD","long_n","long_avgR","short_n","short_avgR"]}))
            if sname in ("v2 HighWin", "v2 Balanced") and role == "FULL":
                dumps[(desc, sname)] = pd.DataFrame([dict(entry_time=pd.to_datetime(F["ts"][t.bar], unit="s"), exit_time=pd.to_datetime(F["ts"][t.exit_bar], unit="s"),
                    setup=t.setup, dir="BUY" if t.dir == 1 else "SELL", entry=round(t.entry, 2), stop=round(t.sl0, 2), tp1=round(t.tp1, 2), tp2=round(t.tp2, 2),
                    tp3=round(t.tp3, 2), hit_tp1=t.hit1, hit_tp2=t.hit2, hit_tp3=t.hit3, exit=t.reason, exit_px=round(t.exit_px, 2), R=round(t.R, 3)) for t in tr])
        print(f"done {desc}", flush=True)
    R = pd.DataFrame(rows); R.to_csv(OUT / "validation_v2.csv", index=False)
    for (desc, sname), d in dumps.items():
        d.to_csv(OUT / f"trades_v2_{desc.split()[1]}_{sname.split()[1]}.csv", index=False)
    pd.set_option("display.width", 260); pd.set_option("display.max_rows", 300)
    sh = R.copy()
    for c in ["win","tp1","tp2","tp3","fullSL"]: sh[c] = (sh[c].astype(float)*100).round(1)
    for c in ["avgR","netR","pf","maxDD"]: sh[c] = sh[c].astype(float).round(3)
    print(sh[["role","data","system","n","win","tp1","fullSL","avgR","netR","pf","maxDD"]].to_string(index=False))
