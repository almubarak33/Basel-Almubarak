"""Python mirror of indicators/Pro_Scalping_Signals.pine, to check the Pine port against the bot.

1. Signals are computed the Pine way (full-history ta.ema / ta.rma / ta.atr / ta.macd seeded with an SMA,
   RSI 50 when there were no down moves) and compared with the bot's own signals from bot_backtest.py
   (strategy.py on 150-candle windows).
2. Trades are simulated with the indicator's rules (one at a time, next-open entry, stop first) to give
   the statistics the indicator's panel should show for the same data.
"""
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from engine import atr, ema, rma, shift

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data_bot"
SYMS = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK", "DOT", "LTC", "UNI", "NEAR", "ARB", "OP",
        "SUI", "APT", "INJ", "TIA", "FIL", "ATOM", "FET", "JUP", "PYTH", "WIF", "PEPE", "SHIB", "TRB", "AAVE", "MKR"]
FEE, SLIP = 0.0005, 0.0001


def pine_signals(df: pd.DataFrame):
    o, h, l, c, v = (df[k].to_numpy(float) for k in ("open", "high", "low", "close", "volume"))
    e9, e21, e50 = ema(c, 9), ema(c, 21), ema(c, 50)
    chg = np.nan_to_num(c - shift(c))
    up, dn = rma(np.maximum(chg, 0), 14), rma(np.maximum(-chg, 0), 14)
    with np.errstate(divide="ignore", invalid="ignore"):
        rsi = np.where(dn == 0, 50.0, 100 - 100 / (1 + up / dn))
    macd = ema(c, 12) - ema(c, 26)
    hist = macd - ema(macd, 9)
    a = atr(h, l, c, 14)
    volavg = pd.Series(v).rolling(20, min_periods=20).mean().to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        vr = np.where(volavg > 0, v / volavg, np.nan)
    vol_ok = np.nan_to_num(vr, nan=0) >= 1.2
    p9, p21, ph = shift(e9), shift(e21), shift(hist)
    L = (e9 > e21) & (e21 > e50) & (p9 < p21) & (rsi >= 45) & (rsi <= 70) & (hist > 0) & (hist > ph) & vol_ok
    S = (e9 < e21) & (e21 < e50) & (p9 > p21) & (rsi >= 30) & (rsi <= 55) & (hist < 0) & (hist < ph) & vol_ok
    warm = (np.arange(len(c)) >= 150) & (a > 0)
    return L & warm, S & warm & ~(L & warm), a


def simulate(df: pd.DataFrame, L, S, a):
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    n = len(c)
    out = []
    i = 0
    pend = None
    cur = None
    for i in range(n):
        if pend is not None and i > pend["bar"]:
            d, sl, tp, risk = pend["d"], pend["sl"], pend["tp"], pend["risk"]
            entry = o[i]
            fill = entry * (1 + d * SLIP)
            pend = None
            cur = dict(d=d, sl=sl, tp=tp, risk=risk, fill=fill, bar=i)
            kind = None
            if (d == 1 and (entry <= sl or entry >= tp)) or (d == -1 and (entry >= sl or entry <= tp)):
                kind, px = "NOFILL", None
            elif (l[i] <= sl) if d == 1 else (h[i] >= sl):
                kind, px = "SL", sl
            elif (h[i] >= tp) if d == 1 else (l[i] <= tp):
                kind, px = "TP", tp
            if kind:
                out.append(close_r(cur, px, kind)); cur = None
        elif cur is not None and i > cur["bar"]:
            d, sl, tp = cur["d"], cur["sl"], cur["tp"]
            kind = None
            if (d == 1 and o[i] <= sl) or (d == -1 and o[i] >= sl):
                kind, px = "GAP", o[i]
            elif (l[i] <= sl) if d == 1 else (h[i] >= sl):
                kind, px = "SL", sl
            elif (h[i] >= tp) if d == 1 else (l[i] <= tp):
                kind, px = "TP", tp
            if kind:
                out.append(close_r(cur, px, kind)); cur = None
        if cur is None and pend is None and (L[i] or S[i]):
            d = 1 if L[i] else -1
            sl, tp = c[i] - d * 1.5 * a[i], c[i] + d * 3.0 * a[i]
            pend = dict(d=d, bar=i, sl=sl, tp=tp, risk=abs(c[i] - sl))
    return out


def close_r(t, px, kind):
    exit_fill = t["fill"] if kind == "NOFILL" else px * (1 - t["d"] * SLIP)
    R = ((exit_fill - t["fill"]) * t["d"] - FEE * (t["fill"] + exit_fill)) / t["risk"]
    return dict(kind=kind, R=R)


def one(sym):
    df = pd.read_csv(DATA / f"{sym}_5m.csv.gz")
    L, S, a = pine_signals(df)
    pine_ts = set(df["ts_ms"].to_numpy()[L | S])
    bot = pd.read_csv(ROOT / "results" / "bot_signals_outcomes.csv.gz", usecols=["sym", "signal_ts"])
    bot_ts = set(bot.loc[bot["sym"] == sym, "signal_ts"])
    trades = simulate(df, L, S, a)
    return sym, len(bot_ts), len(pine_ts), len(bot_ts & pine_ts), trades


if __name__ == "__main__":
    with ProcessPoolExecutor(4) as ex:
        res = list(ex.map(one, SYMS))
    b = sum(r[1] for r in res); p = sum(r[2] for r in res); both = sum(r[3] for r in res)
    print(f"signals: bot {b}, pine-mirror {p}, same candle {both} "
          f"({both / b:.1%} of bot signals, {both / p:.1%} of pine signals)")
    T = pd.DataFrame([t for r in res for t in r[4]])
    R = T["R"].to_numpy()
    print(f"indicator-rule trades (one at a time, all 30 pairs): n={len(R)} win={np.mean(R > 0):.1%} "
          f"target={np.mean(T.kind == 'TP'):.1%} avgR={R.mean():+.3f} PF={R[R > 0].sum() / -R[R < 0].sum():.2f}")
    btc = [r for r in res if r[0] == "BTC"][0]
    Rb = np.array([t["R"] for t in btc[4]])
    print(f"BTC only: n={len(Rb)} win={np.mean(Rb > 0):.1%} avgR={Rb.mean():+.3f}")
