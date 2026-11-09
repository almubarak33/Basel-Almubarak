#!/usr/bin/env python3
"""Ground-truth check of the engine's indicator maths against TradingView's own published values.

On 2026-11-09 (after the Saudi market close) TradingView's screener reported the daily indicator values
below for TADAWUL:TASI and TADAWUL:2222.  The engine must reproduce them from the OHLC history:
ATR(14), RSI(14), ADX(14,14), +DI, -DI and EMA(200) all come out of engine.base_features().
EMA(200) only matches with the SMA-seeded recursion, which settles how ta.ema is initialised.

The check needs the data files as fetched on that day (history ending 2026-11-08); it is skipped otherwise.
Usage: python3 test_tv_reference.py
"""
import sys

import numpy as np

import datasets as ds

try:
    import apex_engine as E
except Exception:  # pragma: no cover
    import engine_b as E

LAST_BAR_T = 1794207600  # 2026-11-09 07:00 UTC, the bar the reference values belong to
REF = {
    # name: (o, h, l, c of 2026-11-09), {indicator: TradingView value}, tolerance per indicator
    "TADAWUL_TASI_1D": ((10035.6, 10106.72, 9984.93, 10106.72),
                        {"atr": 149.8328484271709, "rsi14": 49.62431673420119, "adx": 38.10067325413852,
                         "diP": 22.90858755006727, "diM": 30.686648904690383, "ema200": 10756.58983099167}),
    "TADAWUL_2222_1D": ((26.06, 26.2, 26.04, 26.1),
                        {"atr": 0.2873638913120656, "rsi14": 56.318015324432125, "adx": 14.338792691022809,
                         "diP": 24.310373073282317, "diM": 17.893884403810077, "ema200": 26.10498900217552}),
}
# ATR / RSI / EMA reproduce to machine precision.  The DMI family is allowed 1e-5: on 2222 the screener
# differs from the bar history by ~3e-6 (an adjusted bar in its history), on TASI it matches to 1e-15.
TOL = {"atr": 1e-9, "rsi14": 1e-9, "ema200": 1e-9, "adx": 1e-5, "diP": 1e-5, "diM": 1e-5}


def main() -> int:
    worst = 0.0
    ran = 0
    for name, (bar, ref) in REF.items():
        try:
            chart = ds.load(name)
        except OSError:
            print(f"SKIP {name}: data file not present")
            continue
        if int(chart["t"][-1]) >= LAST_BAR_T:
            keep = chart["t"] < LAST_BAR_T
            chart = {k: v[keep] for k, v in chart.items()}
        if int(chart["t"][-1]) != 1794121200:
            print(f"SKIP {name}: history does not end on 2026-11-08 (reference values are for 2026-11-09)")
            continue
        o, h, l, c = bar
        chart = {"t": np.append(chart["t"], LAST_BAR_T), "o": np.append(chart["o"], o), "h": np.append(chart["h"], h),
                 "l": np.append(chart["l"], l), "c": np.append(chart["c"], c), "v": np.append(chart["v"], 0.0)}
        market = ds.market_of(name, chart)
        htf, _ = ds.htf_bars(name, chart)
        base = E.base_features(chart, htf, market)
        ran += 1
        for key, tv in ref.items():
            mine = float(base[key][-1])
            err = abs(mine - tv) / abs(tv)
            worst = max(worst, err / TOL[key])
            flag = "ok " if err <= TOL[key] else "FAIL"
            print(f"{flag} {name:18s} {key:7s} engine={mine:.10f} tradingview={tv:.10f} rel.err={err:.1e}")
    if ran == 0:
        print("no reference check could run")
        return 0
    print("PASS" if worst <= 1.0 else "FAIL")
    return 0 if worst <= 1.0 else 1


if __name__ == "__main__":
    sys.exit(main())
