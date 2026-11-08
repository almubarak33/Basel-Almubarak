"""Why does APEX Fusion (15m gold, shipped defaults) miss big moves, and why do trades rarely pass TP1?

1. Big-move funnel: zigzag legs of >= 1% (about $40 on gold). A leg counts as "caught" at a stage when a
   signal in the leg's direction exists in the first half of the leg (an entry there still captures half the move).
   Stages add the shipped gates one at a time; the last stage is a real filled trade from the simulator.
2. Trade outcomes: how trades end, and how far price went after a breakeven exit."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from engine import load, features, setups, simulate, htf_trend
import final_config_v2 as v2
from final_config import TREND, anchor_minutes, session_ok

LEG_PCT = 1.0


def zigzag(h, l, pct):
    """Alternating swing pivots on highs/lows with a percentage reversal threshold. Returns [(start, end, dir)]."""
    piv, d = [(0, l[0], 1)], 0          # (idx, price, kind) kind 1=low -1=high
    hi_i, lo_i = 0, 0
    for i in range(1, len(h)):
        if h[i] > h[hi_i]: hi_i = i
        if l[i] < l[lo_i]: lo_i = i
        if d >= 0 and l[i] <= h[hi_i] * (1 - pct / 100) and hi_i >= piv[-1][0]:
            piv.append((hi_i, h[hi_i], -1)); d = -1; lo_i = i
        elif d <= 0 and h[i] >= l[lo_i] * (1 + pct / 100) and lo_i >= piv[-1][0]:
            piv.append((lo_i, l[lo_i], 1)); d = 1; hi_i = i
    return [(piv[k][0], piv[k + 1][0], 1 if piv[k][2] == 1 else -1) for k in range(1, len(piv) - 1)]


def run(ds, a=None, b=None):
    df = load(ds)
    P = v2.final_params(15, "gold")
    F = features(df, P)
    S = setups(F, P)
    F["anchor"] = htf_trend(df, anchor_minutes(15), 21)
    N, c, atr = F["N"], F["c"], F["atr"]
    sess = session_ok(F, "metal", 15)
    okBar = (F["h"] - F["l"]) <= 2.5 * atr
    stage = {}
    for d in (1, -1):
        k = 0 if d == 1 else 1
        raw = np.zeros(N, bool)
        for s in TREND: raw |= S[s][k]
        sc = F["scoreL"] if d == 1 else F["scoreS"]
        sl = F["slL"] if d == 1 else F["slS"]
        floor = (sl >= 0.43 / 100 * c) & (sl >= 0.01 / 100 * c / 0.07)
        g = {"anchor": F["anchor"] == d, "session": sess, "score": sc >= 5, "htf": F["htf"] == d,
             "okBar": okBar, "floor": floor}
        stage[d] = (raw, g)
    L, Sh, lab = v2.final_signals(df, F, P, "gold")
    trades = simulate(F, P, L, Sh, lab)
    ts = F["ts"]
    ta = pd.Timestamp(a).timestamp() if a else -1
    tb = pd.Timestamp(b).timestamp() if b else 9e18
    legs = [(s, e, d) for s, e, d in zigzag(F["h"], F["l"], LEG_PCT) if s >= 300 and ta <= ts[s] < tb]
    order = ["anchor", "session", "score", "htf", "okBar", "floor"]
    rows = []
    entry_bars = {}
    for t in trades:
        entry_bars.setdefault(t.dir, []).append(t.bar)
    for s, e, d in legs:
        w = slice(s, s + max(1, (e - s) // 2) + 1)
        raw, g = stage[d]
        r = {"start_hour_ny": F["hour_ny"][s], "bars": e - s, "move_pct": abs(c[e] - c[s]) / c[s] * 100}
        cur = raw.copy()
        r["raw"] = cur[w].any()
        for k in order:
            cur = cur & g[k]
            r[k] = cur[w].any()
        # only this gate removed (all the others kept)
        for k in order:
            m = raw.copy()
            for k2 in order:
                if k2 != k: m &= g[k2]
            r["without_" + k] = m[w].any()
        eb = np.array(entry_bars.get(d, []))
        r["traded"] = bool(((eb >= s) & (eb <= w.stop - 1 + 3)).any()) if len(eb) else False
        rows.append(r)
    R = pd.DataFrame(rows)
    T = [t for t in trades if ta <= ts[t.bar] < tb]
    return R, T, F


def outcome_table(T, F):
    h, l = F["h"], F["l"]
    out = []
    for t in T:
        kind = ("TP3" if t.hit3 else "TP2 then stop at TP1" if t.hit2 else "TP1 then breakeven" if t.hit1 else
                "full stop" if t.reason in ("SL", "Remaining SL") else t.reason)
        # best excursion in R within 32 bars (8h) of the entry
        j = slice(t.bar, min(len(h), t.bar + 33))
        mfe = ((h[j].max() - t.entry) if t.dir == 1 else (t.entry - l[j].min())) / t.risk
        out.append(dict(kind=kind, R=t.R, mfe8h=mfe))
    return pd.DataFrame(out)


if __name__ == "__main__":
    pd.set_option("display.width", 220)
    for ds, a, b in [("XAUUSDT_15m", None, None), ("PAXGUSDT_15m", "2023-01-01", None)]:
        R, T, F = run(ds, a, b)
        print(f"\n===== {ds} {a or ''}  legs >= {LEG_PCT}%: {len(R)}  (median move {R.move_pct.median():.2f}%, median {R.bars.median():.0f} bars)")
        cols = ["raw", "anchor", "session", "score", "htf", "okBar", "floor", "traded"]
        print("caught after each cumulative gate:", "  ".join(f"{k} {R[k].mean():.0%}" for k in cols))
        print("caught with all gates except one :", "  ".join(f"-{k} {R['without_' + k].mean():.0%}" for k in ["anchor", "session", "score", "htf", "okBar", "floor"]))
        sess = pd.cut(R.start_hour_ny, [-1, 2, 7, 16, 17, 24], labels=["Asia 18-03", "London 03-08", "NY 08-17", "break", "Asia 18-03b"])
        sess = sess.astype(str).str.replace("b", "")
        print("legs by start session:", R.groupby(sess).size().to_dict(), "| caught (traded) by session:",
              R.groupby(sess)["traded"].mean().round(2).to_dict())
        O = outcome_table(T, F)
        g = O.groupby("kind").agg(n=("R", "size"), avgR=("R", "mean"), mfe8h_med=("mfe8h", "median"))
        g["share"] = (g.n / len(O)).round(3)
        print(f"trades {len(O)}  win {np.mean(O.R > 0):.1%}  avgR {O.R.mean():+.3f}")
        print(g.round(3).to_string())
        be = O[O.kind == "TP1 then breakeven"]
        if len(be):
            print("after 'TP1 then breakeven': price later reached (within 8h of entry) "
                  + "  ".join(f">={x}R {np.mean(be.mfe8h >= x):.0%}" for x in (1.0, 1.5, 2.0, 3.0, 4.0)))
