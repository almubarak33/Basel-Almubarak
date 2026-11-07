"""Definitive tables for the shipped defaults (v2.1). 5m and 15m are the primary timeframes."""
import json, numpy as np, pandas as pd
from engine import *
import final_config_v2 as fc
from baseline import apex_original, gbb_original, APEX_P, GBB_P
from validate_v2 import win
from pathlib import Path
OUT = Path(__file__).resolve().parent / "results"
RUNS = [
    ("XAUUSDT_5m", 5, None, None, "FULL", "ذهب 5د — سنة كاملة (ديسمبر 25–نوفمبر 26)"),
    ("XAUUSDT_5m", 5, "2025-12-01", "2026-06-01", "IS", "ذهب 5د — ديسمبر 25–مايو 26"),
    ("XAUUSDT_5m", 5, "2026-06-01", None, "OOS", "ذهب 5د — يونيو–نوفمبر 26"),
    ("PAXGUSDT_5m", 5, "2023-01-01", "2025-07-01", "IS", "PAXG 5د — 2023–يونيو 25"),
    ("PAXGUSDT_5m", 5, "2025-07-01", "2025-12-11", "OOS", "PAXG 5د — يوليو–ديسمبر 25"),
    ("XAUUSDT_15m", 15, None, None, "FULL", "ذهب 15د — سنة كاملة (ديسمبر 25–نوفمبر 26)"),
    ("XAUUSDT_15m", 15, "2025-12-01", "2026-06-01", "IS", "ذهب 15د — ديسمبر 25–مايو 26"),
    ("XAUUSDT_15m", 15, "2026-06-01", None, "OOS", "ذهب 15د — يونيو–نوفمبر 26"),
    ("PAXGUSDT_15m", 15, "2022-01-01", "2025-07-01", "IS", "PAXG 15د — 2022–يونيو 25"),
    ("PAXGUSDT_15m", 15, "2025-07-01", "2025-12-11", "OOS", "PAXG 15د — يوليو–ديسمبر 25"),
    ("PAXGUSDT_15m", 15, "2021-01-01", "2022-01-01", "OOS", "PAXG 15د — 2021 (سيولة ضعيفة)"),
    ("XAUUSDT_1h", 60, None, None, "XTF", "ذهب ساعة — ديسمبر 25–نوفمبر 26"),
    ("GC_F_1h", 60, None, None, "XTF", "COMEX ساعة — يونيو 24–نوفمبر 26"),
    ("PAXGUSDT_1h", 60, None, None, "XTF", "PAXG ساعة — 2021–2026"),
    ("XAGUSDT_15m", 15, None, None, "XASSET", "فضة 15د — يناير–نوفمبر 26"),
]
if __name__ == "__main__":
    rows = []; cache = {}; monthly = []; persetup = []; eq = {}
    for ds, tf, a, b, role, desc in RUNS:
        df = cache.setdefault(ds, load(ds))
        asset = "silver" if ds.startswith("XAG") else "gold"
        systems = [("Fusion (افتراضي)", "auto", None), ("Fusion High Win-Rate", "HighWin", None), ("Fusion Balanced", "Balanced", None),
                   ("Fusion (افتراضي) @0.03%", "auto", 0.03 if asset == "gold" else 0.08), ("APEX الأصلي", "apex", None), ("GBB الأصلي", "gbb", None)]
        Fc = {}
        for sname, prof, cost in systems:
            if prof == "apex":
                P = Params(tf_minutes=tf, cost_pct=fc.cost_for(asset), cg_max_pct=7.0 * fc.cost_for(asset) / 0.03, **APEX_P)
            elif prof == "gbb":
                P = Params(tf_minutes=tf, cost_pct=fc.cost_for(asset), **GBB_P)
            else:
                P = fc.final_params(tf, asset, prof, cost)
            key = (P.htf_minutes, P.stop_mode)
            if key not in Fc: Fc[key] = features(df, P)
            F = Fc[key]
            if prof == "apex": L, S, lab = apex_original(F, P)
            elif prof == "gbb": L, S, lab = gbb_original(F, P)
            else: L, S, lab = fc.final_signals(df, F, P, asset)
            tr = win(simulate(F, P, L, S, lab), F, a, b)
            st = stats(tr)
            rows.append(dict(role=role, data=desc, system=sname, **{k: st.get(k) for k in ["n","win","tp1","tp2","tp3","fullSL","avgR","netR","pf","maxDD","long_n","short_n"]}))
            if sname == "Fusion (افتراضي)" and role == "FULL":
                T = pd.DataFrame(dict(m=pd.to_datetime([F["ts"][t.bar] for t in tr], unit="s").to_period("M").astype(str), R=[t.R for t in tr], w=[t.R > 0 for t in tr], s=[t.setup for t in tr]))
                M = T.groupby("m").agg(n=("R","size"), win=("w","mean"), netR=("R","sum")).reset_index(); M["tf"] = f"{tf}m"; monthly.append(M)
                X = T.groupby("s").agg(n=("R","size"), win=("w","mean"), avgR=("R","mean")).reset_index(); X["tf"] = f"{tf}m"; persetup.append(X)
                eq[f"{tf}m"] = dict(t=[int(F["ts"][t.exit_bar]) for t in tr], cum=np.round(np.cumsum([t.R for t in tr]), 3).tolist())
                pd.DataFrame([dict(entry_time=pd.to_datetime(F["ts"][t.bar], unit="s"), setup=t.setup, dir="BUY" if t.dir == 1 else "SELL", entry=round(t.entry, 2),
                    stop=round(t.sl0, 2), tp1=round(t.tp1, 2), tp2=round(t.tp2, 2), tp3=round(t.tp3, 2), hit_tp1=t.hit1, hit_tp2=t.hit2, hit_tp3=t.hit3,
                    exit=t.reason, exit_time=pd.to_datetime(F["ts"][t.exit_bar], unit="s"), exit_px=round(t.exit_px, 2), R=round(t.R, 3)) for t in tr]).to_csv(OUT / f"trades_final_gold_{tf}m.csv", index=False)
        print("done", desc, flush=True)
    R = pd.DataFrame(rows); R.to_csv(OUT / "validation_final.csv", index=False)
    pd.concat(monthly).to_csv(OUT / "monthly_final.csv", index=False); pd.concat(persetup).to_csv(OUT / "per_setup_final.csv", index=False)
    json.dump(eq, open(OUT / "equity_final.json", "w"))
    pd.set_option("display.width", 250); pd.set_option("display.max_rows", 300)
    sh = R.copy()
    for c in ["win","tp1","tp2","tp3","fullSL"]: sh[c] = (sh[c].astype(float)*100).round(1)
    for c in ["avgR","netR","pf","maxDD"]: sh[c] = sh[c].astype(float).round(3)
    print(sh[["role","data","system","n","win","tp1","tp2","tp3","fullSL","avgR","netR","pf","maxDD"]].to_string(index=False))
    print(pd.concat(monthly).round(3).to_string(index=False)); print(pd.concat(persetup).round(3).to_string(index=False))
