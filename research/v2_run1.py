from v2_lab import *
for prof in ["HighWin", "Balanced"]:
    print(f"===== profile {prof}")
    evaluate({}, prof, label="v1 baseline")
    for f, nb in [(0.25, 3), (0.33, 3), (0.5, 3), (0.33, 6), (0.5, 6)]:
        evaluate({}, prof, dict(entry_mode="pullback", pb_frac=f, pb_bars=nb), label=f"pullback f={f} bars={nb}")
    evaluate(dict(q_candle=True), prof, label="+ candle quality")
    evaluate(dict(q_range=2.5), prof, label="+ no bar > 2.5 ATR")
    evaluate(dict(q_ext=2.5), prof, label="+ ext <= 2.5 ATR from EMA21")
    evaluate(dict(killzone=[(2, 5), (7, 11)]), prof, label="killzones 02-05 + 07-11 NY")
    evaluate(dict(killzone=[(8, 12)]), prof, label="NY AM 08-12")
    evaluate(dict(trend=["ABRK"]), prof, label="ABRK only (trend gate)")
    evaluate(dict(trend=[], extra=["ASWP"]), prof, label="ASWP only (daily bias)")
    evaluate(dict(trend=[], extra=["ASWP"], aswp_htf=True), prof, label="ASWP only (daily+htf not against)")
    evaluate(dict(trend=[], extra=["ASWP"], aswp_gate="notagainst"), prof, label="ASWP only (daily not against)")
    evaluate(dict(trend=TREND7 + ["ABRK"], extra=["ASWP"]), prof, label="v1 + ABRK + ASWP")
