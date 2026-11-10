#!/usr/bin/env python3
"""Gold / silver study behind apex/REPORT_METALS.md: every table, written to results/metals_tables.md.

Deep feed: histdata.com 1-minute quotes 2010-01 -> 2026-10 (TRAIN = entries before 2020, TEST = from 2020),
every simulation replayed on 1-minute bars with the v2 rule closeStop = 1.  Other feeds are checks only.
Usage: python3 study_metals.py            (about 10 minutes on 4 cores)
"""
import datetime as dt
import os
from multiprocessing import Pool

import numpy as np

import datasets as ds
import fusion_engine as F
import metals_lib as ml

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
TF_AR = {"5m": "5 دقائق", "15m": "15 دقيقة", "1h": "ساعة", "4h": "4 ساعات", "1D": "يومي"}
METAL_AR = {"GOLD": "الذهب", "SILVER": "الفضة"}
PROFS = ["AUTO3", "ULT", "SHD", "SNP", "MW", "HW", "BAL", "RUN"]
PROF_AR = {"ULT": "Ultra (5× التكلفة)", "SHD": "Shield (0.05R)", "SNP": "Sniper (0.2R)", "MW": "Max Win-Rate (0.4R)",
           "HW": "High Win-Rate (0.5R)", "BAL": "Balanced Pro (1R)", "RUN": "Trend Runner (1R)"}
K1_GRID = [0.03, 0.05, 0.08, 0.12, 0.2, 0.3, 0.5]


def full_close(k1, mult=0.0):
    return {"k1": k1, "k2": 1.5, "k3": 4.0, "w1": 1.0, "w2": 0.0, "trailOn": False, "trailFrom": 1, "beOn": True,
            "tp1CostMult": mult, "closeStop": 1}


def wide_stop(tf):
    """Stop clamp used with the 99% construction: Ultra's 6-12 ATR on 1H-4H charts, the script's own elsewhere."""
    return dict(slMinAtr=F.ULTRA_STOP[0], slMaxAtr=F.ULTRA_STOP[1]) if tf in ("1h", "4h") else {}


def job(args):
    """Everything for one (metal, timeframe) of the deep feed -> dict of summaries (keeps trades out of the pipe)."""
    metal, tf = args
    name = ml.series_name(metal, "deep", tf)
    S = ml.summary
    out = {"metal": metal, "tf": tf, "prof": {}, "front": {}, "p99": {}, "ultra_dir": {}, "auto_dir": {}, "cost": {},
           "rule": {}, "year": {}, "fallback": {}}
    ctx = F.context(name)
    out["bars"] = len(ctx["chart"]["t"])
    for prof in PROFS:
        p = ml.with_p(profile=prof)
        tr = ml.replay(name, ml.feats(name, p), p)
        out["prof"][prof] = {"name": F.resolve_profile(ctx["market"], p), "TRAIN": S(ml.seg(tr, "TRAIN")), "TEST": S(ml.seg(tr, "TEST")),
                             "signals": tr[0]["signals"] if tr else 0, "filled": tr[0]["filled"] if tr else 0}
        if prof in ("AUTO3", "ULT"):
            key = "auto_dir" if prof == "AUTO3" else "ultra_dir"
            for d, lbl in ((1, "long"), (-1, "short")):
                sub = [t for t in tr if t["dir"] == d]
                out[key][lbl] = {"TRAIN": S(ml.seg(sub, "TRAIN")), "TEST": S(ml.seg(sub, "TEST"))}
        if prof == "ULT":
            for t in tr:
                y = dt.datetime.fromtimestamp(t["t"], dt.UTC).year
                a = out["year"].setdefault(y, [0, 0, 0.0])
                a[0] += 1
                a[1] += t["R"] > 0
                a[2] += t["R"]
    p0 = F.FParams()
    f0 = ml.feats(name, p0)
    for k1 in K1_GRID:                                     # first target alone decides the trade: no breakeven runner
        tr = ml.replay(name, f0, p0, full_close(k1))
        out["front"][k1] = {"TRAIN": S(ml.seg(tr, "TRAIN")), "TEST": S(ml.seg(tr, "TEST"))}
    for dm in ("Both", "Long only"):                       # the 99% construction: 2 x cost, everything closed there
        p = ml.with_p(dirMode=dm, **wide_stop(tf))
        tr = ml.replay(name, ml.feats(name, p), p, full_close(0.005, 2.0))
        out["p99"][dm] = {"TRAIN": S(ml.seg(tr, "TRAIN")), "TEST": S(ml.seg(tr, "TEST"))}
    base_cost = F.cost_pct(ctx["market"], p0)
    for mult in (0.5, 1.0, 2.0, 3.0):                      # Ultra under other trading costs (guard and kernel both)
        p = ml.with_p(profile="ULT", costMode="Custom", costCustom=base_cost * mult)
        tr = ml.replay(name, ml.feats(name, p), p)
        out["cost"][mult] = {"ALL": S(tr), "pct": base_cost * mult}
    for prof in ("ULT", "SHD", "SNP", "HW", "BAL"):        # chart-bar simulation against the 1-minute replay
        p = ml.with_p(profile=prof)
        f = ml.feats(name, p)
        out["fallback"][prof] = {"replay": S(ml.replay(name, f, p)), "rule1": S(ml.chart_sim(name, f, p, {"closeStop": 1})),
                                 "rule2": S(ml.chart_sim(name, f, p, {"closeStop": 2}))}
    p = ml.with_p(profile="ULT")
    for rule in (0, 1, 2):                                 # same-minute ambiguity of a stop raised by a fill
        tr = ml.replay(name, ml.feats(name, p), p, {"closeStop": rule})
        out["rule"][rule] = {"ALL": S(tr)}
    return out


def other_feeds():
    """Auto and Ultra on the feeds that were never tuned on."""
    S = ml.summary
    out = []
    for metal in ml.METALS:
        for tf in ml.TFS:
            for feed in ("tv", "perp"):
                name = ml.series_name(metal, feed, tf)
                ctx = F.context(name)
                t = ctx["chart"]["t"]
                span = f"{dt.datetime.fromtimestamp(int(t[0]), dt.UTC):%Y-%m-%d} → {dt.datetime.fromtimestamp(int(t[-1]), dt.UTC):%Y-%m-%d}"
                for prof in ("AUTO3", "ULT"):
                    p = ml.with_p(profile=prof)
                    f = ml.feats(name, p)
                    if feed == "perp":
                        rows = {"replay": S(ml.replay(name, f, p))}
                    else:                                   # no 1-minute history on this feed: chart bars, two bounds
                        rows = {"rule1": S(ml.chart_sim(name, f, p, {"closeStop": 1})), "rule2": S(ml.chart_sim(name, f, p, {"closeStop": 2}))}
                    out.append({"metal": metal, "tf": tf, "feed": feed, "prof": prof, "bars": len(t), "span": span, **rows})
                    if feed == "tv":                        # the deep feed over the same window, replayed by the minute
                        dname = ml.series_name(metal, "deep", tf)
                        tr = [x for x in ml.replay(dname, ml.feats(dname, p), p) if x["t"] >= int(t[0])]
                        out.append({"metal": metal, "tf": tf, "feed": "deep", "prof": prof, "bars": len(t), "span": span, "replay": S(tr)})
    return out


def volume_effect():
    """The deep feed has no volume.  Same OANDA series with and without its volume column, Auto profile."""
    out = []
    for metal in ml.METALS:
        for tf in ml.TFS:
            name = ml.series_name(metal, "tv", tf)
            ctx = F.context(name)
            p = ml.with_p(profile="AUTO3")
            ctx0 = dict(ctx)
            ctx0["chart"] = dict(ctx["chart"], v=np.zeros(len(ctx["chart"]["v"])))
            res = {}
            for lbl, c in (("vol", ctx), ("novol", ctx0)):
                f = F.features(c, p)
                tr, _st, info = F.simulate(c, f, p, {"closeStop": 1})
                R = np.array([x["R"] for x in tr])
                res[lbl] = {"signals": info["signals"], "n": len(tr), "win": float((R > 0).mean()) if len(R) else float("nan"),
                            "avgR": float(R.mean()) if len(R) else float("nan"),
                            "vwap": sum(x["setup"] == "VWAP" for x in tr)}
            out.append({"metal": metal, "tf": tf, **res})
    return out


def validation():
    """Deep feed against OANDA on the bars both have."""
    out = []
    for metal in ml.METALS:
        for tf in ml.TFS:
            a, b = ds.load(ml.series_name(metal, "deep", tf)), ds.load(ml.series_name(metal, "tv", tf))
            _, ia, ib = np.intersect1d(a["t"], b["t"], return_indices=True)
            lo, hi = max(a["t"][0], b["t"][0]), min(a["t"][-1], b["t"][-1])
            out.append({"metal": metal, "tf": tf, "from": f"{dt.datetime.fromtimestamp(int(lo), dt.UTC):%Y-%m-%d}",
                        "to": f"{dt.datetime.fromtimestamp(int(hi), dt.UTC):%Y-%m-%d}",
                        "deep": int(((a["t"] >= lo) & (a["t"] <= hi)).sum()), "tv": int(((b["t"] >= lo) & (b["t"] <= hi)).sum()),
                        "common": len(ia), "dclose": float(np.median(np.abs(a["c"][ia] / b["c"][ib] - 1)) * 100),
                        "corr": float(np.corrcoef(a["c"][ia] / a["o"][ia] - 1, b["c"][ib] / b["o"][ib] - 1)[0, 1]),
                        "samedir": float(np.mean(np.sign(a["c"][ia] - a["o"][ia]) == np.sign(b["c"][ib] - b["o"][ib])))})
    return out


# ───────────────────────────── rendering ─────────────────────────────
lines = []


def emit(s=""):
    lines.append(s)


def pc(x, d=1):
    return "—" if x != x else f"{100 * x:.{d}f}%"


def cells(s):
    """n | win | CI | avgR | PF | maxDD | wins per loss"""
    if not s or s.get("n", 0) == 0:
        return "0 | — | — | — | — | — | —"
    w = s["wins_per_loss"]
    wpl = "—" if w != w else f"{w:.0f}" if w >= 10 else f"{w:.1f}"
    pf = "∞" if s["pf"] == float("inf") else f"{s['pf']:.2f}"
    return (f"{s['n']} | {pc(s['win'])} | {100*s['lo']:.1f}–{100*s['hi']:.1f}% | {s['avgR']:+.3f} | {pf} | "
            f"{s['maxDD']:.1f} | {wpl}")


HEAD7 = "الصفقات | النجاح | مجال الثقة 95% | متوسط R | معامل الربح | أقصى تراجع R | خسارة واحدة = كم ربحًا"


def render(res, feeds, vol, val):
    by = {(r["metal"], r["tf"]): r for r in res}
    emit("### M0 البيانات والتحقق من المصدر العميق")
    emit("| المعدن | الفريم | شموع المصدر العميق | فترة التطابق مع OANDA | شموع مشتركة | فرق الإغلاق الوسيط | ارتباط عوائد الشموع | نفس اتجاه الشمعة |")
    emit("|---|---|---|---|---|---|---|---|")
    for v in val:
        r = by[(v["metal"], v["tf"])]
        emit(f"| {METAL_AR[v['metal']]} | {TF_AR[v['tf']]} | {r['bars']:,} | {v['from']} → {v['to']} | {v['common']:,} من {v['tv']:,} | "
             f"{v['dclose']:.3f}% | {v['corr']:.3f} | {pc(v['samedir'])} |")
    emit()

    emit("### M1 كل أنماط الإدارة على 16.8 سنة (المصدر العميق، إعادة تمثيل بالدقيقة)")
    for metal in ml.METALS:
        for seg, seg_ar in (("TRAIN", "2010–2019 (فترة الضبط)"), ("TEST", "2020–2026 (فترة الاختبار)")):
            emit(f"**{METAL_AR[metal]} — {seg_ar}**")
            emit()
            emit(f"| الفريم | النمط | {HEAD7} |")
            emit("|---|---|---|---|---|---|---|---|---|")
            for tf in ml.TFS:
                r = by[(metal, tf)]
                for prof in PROFS:
                    x = r["prof"][prof]
                    lbl = f"Auto ← {PROF_AR[x['name']].split(' (')[0]}" if prof == "AUTO3" else PROF_AR[prof]
                    emit(f"| {TF_AR[tf]} | {lbl} | {cells(x[seg])} |")
            emit()

    emit("### M2 نسبة النجاح = هندسة الهدف (إغلاق كامل عند الهدف الأول، بلا تعادل)")
    for metal in ml.METALS:
        emit(f"**{METAL_AR[metal]}**")
        emit()
        emit("| الفريم | الهدف الأول | نسبة المشي العشوائي 1/(1+k) | النجاح 2010–2019 | النجاح 2020–2026 | متوسط R 2010–2019 | متوسط R 2020–2026 | الصفقات |")
        emit("|---|---|---|---|---|---|---|---|")
        for tf in ml.TFS:
            r = by[(metal, tf)]
            for k1 in K1_GRID:
                a, b = r["front"][k1]["TRAIN"], r["front"][k1]["TEST"]
                if a.get("n", 0) and b.get("n", 0):
                    emit(f"| {TF_AR[tf]} | {k1}R | {100/(1+k1):.1f}% | {pc(a['win'])} | {pc(b['win'])} | {a['avgR']:+.3f} | {b['avgR']:+.3f} | {a['n'] + b['n']} |")
        emit()

    emit("### M3 كيف تُصنع 99%: هدف = ضعف التكلفة، إغلاق كامل، وقف واسع")
    emit("| المعدن | الفريم | الاتجاه | الفترة | " + HEAD7 + " | نسبة التعادل اللازمة |")
    emit("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for metal in ml.METALS:
        for tf in ml.TFS:
            r = by[(metal, tf)]
            for dm, dm_ar in (("Both", "الاتجاهان"), ("Long only", "شراء فقط")):
                for seg, seg_ar in (("TRAIN", "2010–2019"), ("TEST", "2020–2026")):
                    s = r["p99"][dm][seg]
                    be = "—" if not s.get("n") or s["be_win"] != s["be_win"] else f"{100*s['be_win']:.2f}%"
                    emit(f"| {METAL_AR[metal]} | {TF_AR[tf]} | {dm_ar} | {seg_ar} | {cells(s)} | {be} |")
    emit()

    emit("### M4 نمط Ultra حسب الاتجاه")
    emit("| المعدن | الفريم | الاتجاه | الفترة | " + HEAD7 + " |")
    emit("|---|---|---|---|---|---|---|---|---|---|---|")
    for metal in ml.METALS:
        for tf in ml.TFS:
            r = by[(metal, tf)]
            for lbl, lbl_ar in (("long", "شراء"), ("short", "بيع")):
                for seg, seg_ar in (("TRAIN", "2010–2019"), ("TEST", "2020–2026")):
                    emit(f"| {METAL_AR[metal]} | {TF_AR[tf]} | {lbl_ar} | {seg_ar} | {cells(r['ultra_dir'][lbl][seg])} |")
    emit()

    emit("### M5 النمط التلقائي حسب الاتجاه")
    emit("| المعدن | الفريم | الاتجاه | الفترة | " + HEAD7 + " |")
    emit("|---|---|---|---|---|---|---|---|---|---|---|")
    for metal in ml.METALS:
        for tf in ml.TFS:
            r = by[(metal, tf)]
            for lbl, lbl_ar in (("long", "شراء"), ("short", "بيع")):
                for seg, seg_ar in (("TRAIN", "2010–2019"), ("TEST", "2020–2026")):
                    emit(f"| {METAL_AR[metal]} | {TF_AR[tf]} | {lbl_ar} | {seg_ar} | {cells(r['auto_dir'][lbl][seg])} |")
    emit()

    emit("### M6 مصادر لم يُضبط عليها شيء: OANDA (مصدر TradingView) وعقود Binance الدائمة")
    emit("| المعدن | الفريم | المصدر | الفترة | النمط | القاعدة | " + HEAD7 + " |")
    emit("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for x in feeds:
        prof_ar = "Auto" if x["prof"] == "AUTO3" else "Ultra"
        src = {"tv": "OANDA", "perp": "Binance", "deep": "المصدر العميق، نفس الفترة"}[x["feed"]]
        variants = (("rule1", "شمعة الشارت، القاعدة 1"), ("rule2", "شمعة الشارت، الحد المتشائم")) if x["feed"] == "tv" else (("replay", "إعادة تمثيل بالدقيقة"),)
        for k, k_ar in variants:
            emit(f"| {METAL_AR[x['metal']]} | {TF_AR[x['tf']]} | {src} | {x['span']} | {prof_ar} | {k_ar} | {cells(x[k])} |")
    emit()

    emit("### M7 حساسية Ultra لتكلفة التداول (كل الفترة 2010–2026)")
    emit("| المعدن | الفريم | التكلفة % | " + HEAD7 + " |")
    emit("|---|---|---|---|---|---|---|---|---|---|")
    for metal in ml.METALS:
        for tf in ml.TFS:
            r = by[(metal, tf)]
            for mult in (0.5, 1.0, 2.0, 3.0):
                emit(f"| {METAL_AR[metal]} | {TF_AR[tf]} | {r['cost'][mult]['pct']:.3f} | {cells(r['cost'][mult]['ALL'])} |")
    emit()

    emit("### M8 حساسية Ultra لترتيب الأحداث داخل الدقيقة (كل الفترة)")
    emit("| المعدن | الفريم | القاعدة | " + HEAD7 + " |")
    emit("|---|---|---|---|---|---|---|---|---|---|")
    rule_ar = {0: "0: الوقف المرفوع يُفحص من الدقيقة التالية", 1: "1: خروج إذا أغلقت الدقيقة عبره (المعتمدة)", 2: "2: أي لمس يُحسب (حد متشائم)"}
    for metal in ml.METALS:
        for tf in ml.TFS:
            r = by[(metal, tf)]
            for rule in (0, 1, 2):
                emit(f"| {METAL_AR[metal]} | {TF_AR[tf]} | {rule_ar[rule]} | {cells(r['rule'][rule]['ALL'])} |")
    emit()

    emit("### M9 Ultra سنة بسنة (الذهب ثم الفضة، فريمات ساعة و4 ساعات ويومي مجتمعة)")
    emit("| السنة | صفقات الذهب | نجاح الذهب | صافي الذهب R | صفقات الفضة | نجاح الفضة | صافي الفضة R |")
    emit("|---|---|---|---|---|---|---|")
    years = sorted({y for r in res for y in r["year"]})
    for y in years:
        cols = []
        for metal in ml.METALS:
            n = w = 0
            net = 0.0
            for tf in ("1h", "4h", "1D"):
                a = by[(metal, tf)]["year"].get(y)
                if a:
                    n, w, net = n + a[0], w + a[1], net + a[2]
            cols.append(f"{n} | {pc(w / n) if n else '—'} | {net:+.2f}")
        emit(f"| {y} | {cols[0]} | {cols[1]} |")
    emit()

    emit("### M11 شمعة الشارت بلا بيانات داخلية مقابل الحقيقة بالدقيقة (كل الفترة)")
    emit("| المعدن | الفريم | النمط | صفقات (دقيقة) | نجاح (دقيقة) | متوسط R (دقيقة) | صفقات (القاعدة 1) | نجاح (القاعدة 1) | متوسط R (القاعدة 1) | صفقات (المتشائم) | نجاح (المتشائم) | متوسط R (المتشائم) |")
    emit("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for metal in ml.METALS:
        for tf in ("1h", "4h", "1D"):
            r = by[(metal, tf)]
            for prof in ("ULT", "SHD", "SNP", "HW", "BAL"):
                x = r["fallback"][prof]
                c = lambda s: f"{s['n']} | {pc(s['win'])} | {s['avgR']:+.3f}" if s.get("n") else "0 | — | —"
                emit(f"| {METAL_AR[metal]} | {TF_AR[tf]} | {PROF_AR[prof].split(' (')[0]} | {c(x['replay'])} | {c(x['rule1'])} | {c(x['rule2'])} |")
    emit()

    emit("### M10 أثر غياب الحجم في المصدر العميق (OANDA نفسه بحجمه وبدونه، النمط التلقائي، شمعة الشارت)")
    emit("| المعدن | الفريم | إشارات بالحجم | إشارات بلا حجم | صفقات بالحجم | صفقات بلا حجم | نجاح بالحجم | نجاح بلا حجم | متوسط R بالحجم | متوسط R بلا حجم | صفقات VWAP |")
    emit("|---|---|---|---|---|---|---|---|---|---|---|")
    for v in vol:
        a, b = v["vol"], v["novol"]
        fa = lambda x: "—" if x != x else f"{x:+.3f}"
        emit(f"| {METAL_AR[v['metal']]} | {TF_AR[v['tf']]} | {a['signals']} | {b['signals']} | {a['n']} | {b['n']} | {pc(a['win'])} | {pc(b['win'])} | {fa(a['avgR'])} | {fa(b['avgR'])} | {a['vwap']} |")
    emit()


def main():
    jobs = [(m, tf) for tf in ("1D", "4h", "1h", "15m", "5m") for m in ml.METALS]
    with Pool(3) as pool:
        res = pool.map(job, jobs)
    render(res, other_feeds(), volume_effect(), validation())
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "metals_tables.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
