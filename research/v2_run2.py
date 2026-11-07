from v2_lab import *
import v2_lab
# 5m with HTF = 4H (same trend context as 15m): recompute htf and score from cached features
def with_htf240(name, tf):
    df, F, S = get(name, tf)
    if tf == 5 and "htf240" not in F:
        h4 = htf_trend(df, 240, 50)
        for key, d in (("scoreL", 1), ("scoreS", -1)):
            F[key] = F[key] - (F["htf"] == d) + (h4 == d)
        F["htf"] = h4; F["htf240"] = True
    return df, F, S
orig_get = v2_lab.get
PB = dict(entry_mode="pullback", pb_frac=0.33, pb_bars=3)
PB25 = dict(entry_mode="pullback", pb_frac=0.25, pb_bars=3)
for prof in ["HighWin", "Balanced"]:
    print(f"===== profile {prof}")
    v2_lab.get = orig_get
    evaluate({}, prof, label="v1 (5m HTF=1H)")
    evaluate({}, prof, PB, label="pullback .33 (5m HTF=1H)")
    v2_lab.get = with_htf240
    evaluate({}, prof, label="v1 (5m HTF=4H)")
    evaluate({}, prof, PB25, label="pullback .25 (5m HTF=4H)")
    evaluate({}, prof, PB, label="pullback .33 (5m HTF=4H)")
    evaluate(dict(q_range=2.5), prof, PB, label="pullback .33 + range<=2.5ATR")
    evaluate(dict(min_score=6), prof, PB, label="pullback .33 + score>=6")
    evaluate(dict(session=(7, 17)), prof, PB, label="pullback .33 + session 07-17")
