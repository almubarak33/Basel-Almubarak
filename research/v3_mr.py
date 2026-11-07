"""Connors-style RSI(2) pullback within the Daily + 4H trend (IS first)."""
import numpy as np, pandas as pd, pickle
from engine import *
import final_config_v2 as v2
from final_config import anchor_minutes
from pathlib import Path
IS = [("PAXGUSDT_5m", 5, "2023-01-01", "2025-07-01"), ("XAUUSDT_5m", 5, "2025-12-01", "2026-06-01"),
      ("PAXGUSDT_15m", 15, "2022-01-01", "2025-07-01"), ("XAUUSDT_15m", 15, "2025-12-01", "2026-06-01")]
CACHE = Path(".cache"); CACHE.mkdir(exist_ok=True)
def get(name, tf):
    f = CACHE / f"{name}_v3.pkl"
    if f.exists(): return pickle.load(open(f, "rb"))
    df = load(name); P = Params(tf_minutes=tf, htf_minutes=240); F = features(df, P)
    F["anchor"] = htf_trend(df, anchor_minutes(tf), 21)
    pickle.dump((df, F), open(f, "wb")); return df, F
def mr_signals(F, thr=10, sess=None, ema200=True, okbar=2.5):
    N = F["N"]; hr = F["hour_ny"]
    s = np.ones(N, bool) if sess is None else np.zeros(N, bool)
    if sess is not None:
        for a, b in sess: s |= (hr >= a) & (hr < b) if a < b else ((hr >= a) | (hr < b))
    ok = (F["h"] - F["l"]) <= okbar * F["atr"]
    L = (F["rsi2"] < thr) & (F["anchor"] == 1) & (F["htf"] == 1) & s & ok
    S = (F["rsi2"] > 100 - thr) & (F["anchor"] == -1) & (F["htf"] == -1) & s & ok
    if ema200:
        L &= F["c"] > F["ema200"]; S &= F["c"] < F["ema200"]
    S &= ~L
    return L, S, np.array(["MR"] * N, object)
def ev(label, kw, sigkw, sets=IS):
    cells = []
    for name, tf, a, b in sets:
        df, F = get(name, tf)
        P = Params(tf_minutes=tf, htf_minutes=240, cost_pct=0.01, **kw)
        L, S, lab = mr_signals(F, **sigkw)
        tr = simulate(F, P, L, S, lab)
        ta_, tb_ = pd.Timestamp(a).timestamp(), pd.Timestamp(b).timestamp()
        st = stats([t for t in tr if ta_ <= F["ts"][t.bar] < tb_])
        cells.append(f"{name.split('_')[0][:4]}{tf:>2}m n={st.get('n',0):4d} w={st.get('win',0)*100:4.1f}% R={st.get('avgR',0):+.3f} PF={st.get('pf',0):.2f}")
    print(f"{label:40s}|" + " | ".join(cells), flush=True)
if __name__ == "__main__":
    HW = v2.PROFILES["HighWin"]; FL = dict(min_stop_pct=0.43)
    CON = dict(k1=0.5, w1=0.5, k2=99, w2=0.0, k3=99, be_on=False, lock_tp2=False, trail_on=False)
    ev("MR rsi2<10, HighWin targets, floor", dict(HW, **FL), {})
    ev("MR rsi2<10, Connors exit RSI2>70, floor", dict(k1=99, w1=0, k2=99, w2=0, k3=99, be_on=False, lock_tp2=False, trail_on=False, mr_exit=70, **FL), {})
    ev("MR rsi2<10, TP1 .5R 50% + RSI2>70 exit", dict(CON, mr_exit=70, **FL), {})
    ev("MR rsi2<5, Connors exit, floor", dict(k1=99, w1=0, k2=99, w2=0, k3=99, be_on=False, lock_tp2=False, trail_on=False, mr_exit=70, **FL), dict(thr=5))
    ev("MR rsi2<10, Connors exit, no floor", dict(k1=99, w1=0, k2=99, w2=0, k3=99, be_on=False, lock_tp2=False, trail_on=False, mr_exit=70), {})
    ev("MR rsi2<10, Connors exit, floor, NY 08-17", dict(k1=99, w1=0, k2=99, w2=0, k3=99, be_on=False, lock_tp2=False, trail_on=False, mr_exit=70, **FL), dict(sess=[(8, 17)]))
    ev("MR rsi2<10, Connors exit, floor, Asia 18-03", dict(k1=99, w1=0, k2=99, w2=0, k3=99, be_on=False, lock_tp2=False, trail_on=False, mr_exit=70, **FL), dict(sess=[(18, 3)]))
