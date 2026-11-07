"""Cross-asset test of the shipped defaults (frozen on gold — none of this data was used in the design).
Each asset uses what Pine's 'Auto' asset class applies: cost (silver 0.06%, crypto 0.10%, stocks 0.03%),
session filter (off for crypto), opening range (crypto 00:00 UTC), and the execution pack below 1H."""
import sys, numpy as np, pandas as pd
from pathlib import Path
from engine import *
import final_config_v2 as fc
from final_config import anchor_minutes
from baseline import apex_original, gbb_original, APEX_P, GBB_P
OUT = Path(__file__).resolve().parent / "results"
STOCKS = ["SPY", "QQQ", "AAPL", "NVDA", "TSLA", "MSFT", "AMZN", "META"]
CRYPTO = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

def jobs():
    J = []
    for tf, tag in [(5, "5m"), (15, "15m"), (60, "1h")]:
        J.append(dict(group="الفضة", name=f"XAGUSDT_{tag}", tf=tf, asset="metal", cost="silver"))
    J.append(dict(group="الفضة", name="SI_F_1h", tf=60, asset="metal", cost="silver"))
    for s in CRYPTO:
        for tf, tag in [(5, "5m"), (15, "15m"), (60, "1h")]:
            J.append(dict(group="كريبتو", name=f"{s}_{tag}", tf=tf, asset="crypto", cost="crypto"))
    for s in STOCKS:
        for tf, tag in [(5, "5m"), (15, "15m"), (60, "1h")]:
            J.append(dict(group="أسهم", name=f"{s}_{tag}", tf=tf, asset="stock", cost="stock", htf_src=f"{s}_1h", anchor_src=f"{s}_1d"))
    return J

SYSTEMS = ["Fusion (افتراضي)", "Fusion High Win-Rate", "Fusion Balanced", "APEX الأصلي", "GBB الأصلي"]

def run_job(j):
    df = load(j["name"], asset=j["asset"])
    hs = load(j["htf_src"], asset=j["asset"]) if j.get("htf_src") and j["tf"] < 60 else None
    an = load(j["anchor_src"], asset=j["asset"]) if j.get("anchor_src") else None
    out = {}; fcache = {}
    for sname in SYSTEMS:
        prof = {"Fusion (افتراضي)": "auto", "Fusion High Win-Rate": "HighWin", "Fusion Balanced": "Balanced"}.get(sname)
        c = fc.cost_for(j["cost"])
        if prof:
            P = fc.final_params(j["tf"], j["cost"], prof)
        elif sname == "APEX الأصلي":
            P = Params(tf_minutes=j["tf"], cost_pct=c, **APEX_P, **fc._asset_kw(j["asset"]))
        else:
            P = Params(tf_minutes=j["tf"], cost_pct=c, **GBB_P, **fc._asset_kw(j["asset"]))
        key = (P.htf_minutes, P.stop_mode)
        if key not in fcache:
            Fk = features(df, P, htf_src=hs)
            if an is not None:
                Fk["anchor"] = htf_trend(df, anchor_minutes(j["tf"]), 21, src=an)
            fcache[key] = Fk
        F = dict(fcache[key])
        if prof:
            L, S, lab = fc.final_signals(df, F, P, "crypto" if j["asset"] == "crypto" else "metal")
        elif sname == "APEX الأصلي":
            L, S, lab = apex_original(F, P)
        else:
            L, S, lab = gbb_original(F, P)
        out[sname] = (simulate(F, P, L, S, lab), F)
    return df, out

if __name__ == "__main__":
    rows = []; trades_rows = []
    for j in jobs():
        try:
            df, out = run_job(j)
        except FileNotFoundError as e:
            print("missing", j["name"]); continue
        period = f"{df.ts.iloc[0]:%Y-%m-%d} → {df.ts.iloc[-1]:%Y-%m-%d}"
        for sname, (tr, F) in out.items():
            for t in tr:
                trades_rows.append(dict(group=j["group"], symbol=j["name"].rsplit("_", 1)[0], tf=f"{j['tf']}m", system=sname, R=t.R, win=t.R > 0, tp1=t.hit1, reason=t.reason,
                                        entry_time=pd.to_datetime(F["ts"][t.bar], unit="s")))
            st = stats(tr)
            rows.append(dict(group=j["group"], data=j["name"], tf=f"{j['tf']}m", period=period, system=sname, n=st.get("n", 0), win=st.get("win"), avgR=st.get("avgR"), pf=st.get("pf"), netR=st.get("netR"), maxDD=st.get("maxDD")))
        print("done", j["name"], period, flush=True)
    R = pd.DataFrame(rows); R.to_csv(OUT / "cross_asset.csv", index=False)
    T = pd.DataFrame(trades_rows); T.to_csv(OUT / "cross_asset_trades.csv.gz", index=False, compression="gzip")
    pd.set_option("display.width", 250); pd.set_option("display.max_rows", 500)
    # pooled per group x timeframe x system
    g = T.groupby(["group", "tf", "system"]).agg(n=("R", "size"), win=("win", "mean"), avgR=("R", "mean"), netR=("R", "sum"),
            gross=("R", lambda x: x[x > 0].sum()), loss=("R", lambda x: -x[x < 0].sum())).reset_index()
    g["pf"] = g.gross / g.loss.replace(0, np.nan)
    g = g.drop(columns=["gross", "loss"])
    g.to_csv(OUT / "cross_asset_pooled.csv", index=False)
    print(g.round(3).to_string(index=False))
    d = R[R.system == "Fusion (افتراضي)"].copy()
    for c_ in ["win", "avgR", "pf", "netR"]: d[c_] = d[c_].astype(float).round(3)
    print(d[["group", "data", "tf", "period", "n", "win", "avgR", "pf", "netR"]].to_string(index=False))
