"""EA parity: broker H4/D1 bars start 17:00 New York (NY+7 servers). Re-run the 1h bot check with HTF anchored at 17 vs 18."""
import numpy as np, pandas as pd
import engine
from engine import Params, features, simulate, load
import final_config as v1
import final_config_v2 as v2
from validate_v2 import win

RUNS = [("PAXGUSDT_1h", "2021-01-01", None, "PAXG 1h 2021-2026"),
        ("GC_F_1h", None, None, "COMEX 1h 2024-2026"),
        ("XAUUSDT_1h", None, None, "XAUUSDT 1h 2026")]
rows = []
for hour in (18, 17):
    engine.HTF_START_HOUR = hour
    for ds, a, b, desc in RUNS:
        df = load(ds)
        for prof in ["HighWin", "Balanced"]:
            for cost in (0.01, 0.03):
                P = Params(tf_minutes=60, cost_pct=cost, entry_mode="next_open", pb_bars=1, **v2.PROFILES[prof])
                F = features(df, P); L, S, lab = v1.signals(df, F, P, "metal")
                R = np.array([t.R for t in win(simulate(F, P, L, S, lab), F, a, b)])
                rows.append(dict(htf_hour=hour, data=desc, profile=prof, cost=cost, n=len(R),
                                 win=round((R > 0).mean() * 100, 1), avgR=round(R.mean(), 3),
                                 se=round(R.std(ddof=1) / np.sqrt(len(R)), 3),
                                 pf=round(R[R > 0].sum() / -R[R < 0].sum(), 2)))
T = pd.DataFrame(rows)
T.to_csv("results/bot_gold_check_htf17.csv", index=False)
pd.set_option("display.width", 200)
print(T.to_string(index=False))
