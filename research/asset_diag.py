"""Sanity checks for the cross-asset test: HTF mapping for stocks, and edge before costs."""
import numpy as np, pandas as pd
from engine import *
import final_config_v2 as fc
from final_config import anchor_minutes
from test_assets import jobs, run_job
# (a) stock anchor from daily source vs from the chart's own bars (where both are warm)
df = load("SPY_1h", asset="stock"); d1 = load("SPY_1d", asset="stock")
a_src = htf_trend(df, 1440, 21, src=d1); a_own = htf_trend(df, 1440, 21)
m = np.arange(len(df)) > 600
print(f"SPY 1h daily-anchor agreement (src vs own, after warm-up): {(a_src[m] == a_own[m]).mean():.3f}; share non-zero: {(a_src != 0).mean():.2f}")
h_src = htf_trend(load('SPY_15m', asset='stock'), 240, 50, src=df)
print(f"SPY 15m 4H trend from 1h source: share non-zero {(h_src != 0).mean():.2f}")
# (b) Fusion default: average R before and after cost, pooled per asset group and timeframe
rows = []
for j in jobs():
    import test_assets as ta
    ta.SYSTEMS = ["Fusion (افتراضي)"]
    _, out = run_job(j)
    tr, F = out["Fusion (افتراضي)"]
    for t in tr:
        rows.append(dict(group=j["group"], tf=f"{j['tf']}m", R=t.R, gross=t.R + t.costR, cost=t.costR))
T = pd.DataFrame(rows)
print(T.groupby(["group", "tf"]).agg(n=("R", "size"), avgR_net=("R", "mean"), avgR_before_cost=("gross", "mean"), cost_R=("cost", "mean")).round(3).to_string())
