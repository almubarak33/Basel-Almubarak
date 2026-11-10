#!/usr/bin/env python3
"""Shared data plumbing for the APEX research engines (kept separate so engine ports only hold logic).

CSV files live in ./data (git-ignored): <EXCHANGE>_<TICKER>_<interval>.csv, header t,o,h,l,c,v,
t = bar OPEN time in unix seconds UTC, only closed bars.
"""
from __future__ import annotations

import datetime as dt
import os
from dataclasses import dataclass

import numpy as np

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
TF_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1D": 86400, "1W": 604800}
FOREX = {"EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "NZDUSD", "USDCHF"}


@dataclass(frozen=True)
class Market:
    """What the Pine script reads from syminfo.* / timeframe.*"""
    name: str          # dataset stem, e.g. "OANDA_XAUUSD_4h"
    exchange: str      # "OANDA", "BINANCE", "BINANCEX" (deep Binance mirror), "BINANCEF" (USDT perpetuals),
                       # "HISTDATA" (histdata.com 1-minute quotes), "YF" (Yahoo), "TADAWUL", "NASDAQ", ...
    ticker: str        # syminfo.ticker, e.g. "XAUUSD"
    sym_type: str      # syminfo.type: "crypto" | "forex" | "cfd" | "futures" | "stock" | "index" | "fund"
    interval: str      # "5m" | "15m" | "1h" | "4h" | "1D"
    tf_seconds: int    # timeframe.in_seconds()
    htf_seconds: int   # seconds of the script's Auto higher timeframe
    mintick: float     # syminfo.mintick (only used by the script's `tp3 > mintick` guard)


def auto_htf_seconds(tf_s: int) -> int:
    """Pine autoHtf(): <=5m -> 1H, <=1H -> 4H, <=4H -> 1D, <=1D -> 1W, above -> 1M."""
    return 3600 if tf_s <= 300 else 14400 if tf_s <= 3600 else 86400 if tf_s <= 14400 else 604800 if tf_s <= 86400 else 2592000


# Data-quality rules found by scanning every series (zero-range bars, bad ticks):
#  * excluded: Yahoo 5m feeds whose quotes are too coarse/thin for a 5-minute OHLC simulation
#    (12-18% of bars have high == low, or dozens of bad-tick spikes).
#  * trimmed: daily histories whose first years are close-only prints (open = high = low = close).
EXCLUDE = {"YF_EURUSD_5m", "YF_AUDUSD_5m", "YF_BRENT_5m"}
TRIM_START = {"OANDA_XAUUSD_1D": "2000-05-01", "OANDA_XAGUSD_1D": "2000-05-01", "TADAWUL_2010_1D": "2004-02-01"}


def list_datasets() -> list[str]:
    return sorted(f[:-4] for f in os.listdir(DATA) if f.endswith(".csv") and f[:-4] not in EXCLUDE)


def _read(name: str) -> np.ndarray:
    """CSV rows as a float array; big files are cached as .npy next to the CSV (np.loadtxt is slow on a million rows)."""
    path = os.path.join(DATA, name + ".csv")
    cache = os.path.join(DATA, ".cache", name + ".npy")
    if os.path.exists(cache) and os.path.getmtime(cache) >= os.path.getmtime(path):
        return np.load(cache)
    a = np.loadtxt(path, delimiter=",", skiprows=1, ndmin=2)
    if len(a) > 50000:
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        np.save(cache, a)
    return a


def load_1m(exchange: str, ticker: str) -> dict:
    """1-minute bars written by the fetchers as <EXCHANGE>_<TICKER>_1m.npy (used for the intrabar replay)."""
    a = np.load(os.path.join(DATA, f"{exchange}_{ticker}_1m.npy"))
    return {"t": a[:, 0].astype(np.int64), "o": a[:, 1].copy(), "h": a[:, 2].copy(), "l": a[:, 3].copy(),
            "c": a[:, 4].copy(), "v": a[:, 5].copy()}


def load(name: str) -> dict:
    """-> {"t","o","h","l","c","v"} float64 numpy arrays (t as int64), oldest bar first.

    Applies the data-quality rules above: optional start trim, and high/low are widened to contain
    open/close on the rare malformed row.
    """
    a = _read(name)
    if name in TRIM_START:
        t0 = dt.datetime.strptime(TRIM_START[name], "%Y-%m-%d").replace(tzinfo=dt.UTC).timestamp()
        a = a[a[:, 0] >= t0]
    o, h, l, c = a[:, 1].copy(), a[:, 2].copy(), a[:, 3].copy(), a[:, 4].copy()
    h = np.maximum(h, np.maximum(o, c))
    l = np.minimum(l, np.minimum(o, c))
    return {"t": a[:, 0].astype(np.int64), "o": o, "h": h, "l": l, "c": c, "v": a[:, 5].copy()}


def _sym_type(exchange: str, ticker: str) -> str:
    if exchange.startswith("BINANCE"):
        return "crypto"
    if exchange in ("OANDA", "HISTDATA"):                  # spot FX / CFD quotes
        return "forex" if ticker in FOREX else "cfd"
    if exchange == "YF":                                   # Yahoo: front futures contracts and FX quotes
        return "forex" if ticker in FOREX else "futures"
    if ticker in ("TASI",):
        return "index"
    if ticker in ("SPY",):
        return "fund"
    return "stock"


def _mintick(c: np.ndarray) -> float:
    """Smallest decimal step that represents the recent closes (good enough for the tp3 > mintick guard)."""
    tail = c[-500:]
    for k in range(0, 9):
        if np.allclose(tail, np.round(tail, k), rtol=0, atol=10.0 ** (-k - 3)):
            return 10.0 ** (-k)
    return 1e-8


def market_of(name: str, chart: dict | None = None) -> Market:
    exchange, rest = name.split("_", 1)
    ticker, interval = rest.rsplit("_", 1)
    tf_s = TF_SECONDS[interval]
    mt = _mintick(chart["c"]) if chart is not None else 0.01
    return Market(name, exchange, ticker, _sym_type(exchange, ticker), interval, tf_s, auto_htf_seconds(tf_s), mt)


def _week_key(t: int, exchange: str) -> tuple:
    if exchange.startswith("BINANCE"):
        d = dt.datetime.fromtimestamp(t, dt.UTC)                       # crypto: Monday 00:00 UTC weeks
    elif exchange == "TADAWUL":
        d = dt.datetime.fromtimestamp(t, dt.UTC) + dt.timedelta(days=1)  # Sunday-first trading week
    else:
        d = dt.datetime.fromtimestamp(t + 12 * 3600, dt.UTC)           # OANDA daily bars open 21:00/22:00 UTC the day before
    iso = d.isocalendar()
    return (iso[0], iso[1])


def resample_by_key(bars: dict, keys: list) -> dict:
    """Aggregate consecutive bars sharing a key into one bar (t = first bar's open time)."""
    t, o, h, l, c, v = [], [], [], [], [], []
    prev = None
    for i in range(len(bars["t"])):
        k = keys[i]
        if k != prev:
            t.append(bars["t"][i]); o.append(bars["o"][i]); h.append(bars["h"][i])
            l.append(bars["l"][i]); c.append(bars["c"][i]); v.append(bars["v"][i])
            prev = k
        else:
            h[-1] = max(h[-1], bars["h"][i]); l[-1] = min(l[-1], bars["l"][i])
            c[-1] = bars["c"][i]; v[-1] += bars["v"][i]
    return {"t": np.array(t, dtype=np.int64), "o": np.array(o), "h": np.array(h),
            "l": np.array(l), "c": np.array(c), "v": np.array(v)}


def weekly_from_daily(daily: dict, exchange: str) -> dict:
    return resample_by_key(daily, [_week_key(int(x), exchange) for x in daily["t"]])


def htf_bars(name: str, chart: dict) -> tuple[dict, str]:
    """Higher-timeframe bars the script's Auto mode would request for this chart.

    Preference: the real HTF file of the same symbol (what TradingView would serve); otherwise resample.
    Returns (bars, source_description). The LAST htf bar may still be forming relative to the chart's last
    bar - that is fine because the script only ever reads the PREVIOUS completed htf bar.
    """
    m = market_of(name)
    stem = f"{m.exchange}_{m.ticker}_"
    want = {14400: "4h", 86400: "1D", 3600: "1h"}.get(m.htf_seconds)
    if want and os.path.exists(os.path.join(DATA, stem + want + ".csv")):
        return load(stem + want), f"file:{stem + want}"
    if m.htf_seconds == 604800:
        return weekly_from_daily(chart, m.exchange), "resampled:1W from chart"
    # generic fixed-bucket fallback (crypto-style UTC buckets)
    keys = [int(x) // m.htf_seconds for x in chart["t"]]
    return resample_by_key(chart, keys), f"resampled:{m.htf_seconds}s UTC buckets"


if __name__ == "__main__":
    for n in list_datasets():
        ch = load(n)
        mk = market_of(n, ch)
        hb, src = htf_bars(n, ch)
        print(f"{n:28s} bars={len(ch['t']):6d} type={mk.sym_type:6s} tick={mk.mintick:<8g} htf={mk.htf_seconds:6d} ({len(hb['t'])} bars, {src})")
