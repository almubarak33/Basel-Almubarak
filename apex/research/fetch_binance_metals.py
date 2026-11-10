#!/usr/bin/env python3
"""Gold / silver USDT perpetuals from Binance's public market-data mirror (no key needed): a second, independent
metals feed with real traded volume that trades around the clock.

Usage: python3 fetch_binance_metals.py
Writes data/BINANCEF_<SYM>_1m.npy and data/BINANCEF_<SYM>_{5m,15m,1h,4h,1D}.csv (UTC buckets, as TradingView
builds them for Binance symbols). History starts when the contracts were listed (XAUUSDT 2025-12, XAGUSDT 2026-01).
"""
import datetime as dt
import io
import os
import time
import urllib.error
import urllib.request
import zipfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
RAW = os.path.join(DATA, "binancef_raw")
BASE = "https://data.binance.vision/data/futures/um"
SYMBOLS = {"XAUUSDT": (2025, 12), "XAGUSDT": (2026, 1)}
TFS = {"5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1D": 86400}


def get(url: str):
    for attempt in range(5):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "apex-research/1.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            last = e
        except Exception as e:
            last = e
        time.sleep(2 ** attempt)
    raise last


def rows_of(zbytes: bytes) -> np.ndarray:
    with zipfile.ZipFile(io.BytesIO(zbytes)) as z:
        text = z.read(z.namelist()[0]).decode()
    out = []
    for line in text.splitlines():
        p = line.split(",")
        if not p[0].isdigit():                 # header row in newer files
            continue
        out.append((int(p[0]) // 1000, float(p[1]), float(p[2]), float(p[3]), float(p[4]), float(p[5])))
    return np.array(out)


def cached(kind: str, sym: str, tag: str):
    path = os.path.join(RAW, f"{sym}-1m-{tag}.zip")
    if os.path.exists(path):
        return open(path, "rb").read()
    body = get(f"{BASE}/{kind}/klines/{sym}/1m/{sym}-1m-{tag}.zip")
    if body is not None:
        with open(path + ".part", "wb") as f:
            f.write(body)
        os.replace(path + ".part", path)
    return body


def resample(m1: np.ndarray, tf_s: int) -> np.ndarray:
    b = (m1[:, 0].astype(np.int64) // tf_s) * tf_s
    first = np.flatnonzero(np.r_[True, b[1:] != b[:-1]])
    last = np.r_[first[1:] - 1, len(b) - 1]
    out = np.empty((len(first), 6))
    out[:, 0] = b[first]
    out[:, 1] = m1[first, 1]
    out[:, 2] = np.maximum.reduceat(m1[:, 2], first)
    out[:, 3] = np.minimum.reduceat(m1[:, 3], first)
    out[:, 4] = m1[last, 4]
    out[:, 5] = np.add.reduceat(m1[:, 5], first)
    return out


def main() -> None:
    os.makedirs(RAW, exist_ok=True)
    today = dt.datetime.now(dt.UTC).date()
    for sym, (y, m) in SYMBOLS.items():
        parts = []
        while (y, m) < (today.year, today.month):
            body = cached("monthly", sym, f"{y:04d}-{m:02d}")
            if body is None:                                    # month not published yet: fall back to daily files
                d = dt.date(y, m, 1)
                while d.month == m and d < today:
                    b = cached("daily", sym, d.isoformat())
                    if b is not None:
                        parts.append(rows_of(b))
                    d += dt.timedelta(days=1)
            else:
                parts.append(rows_of(body))
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        d = dt.date(today.year, today.month, 1)
        while d < today:
            b = cached("daily", sym, d.isoformat())
            if b is not None:
                parts.append(rows_of(b))
            d += dt.timedelta(days=1)
        m1 = np.concatenate(parts)
        m1 = m1[np.argsort(m1[:, 0], kind="stable")]
        m1 = m1[np.r_[True, np.diff(m1[:, 0]) > 0]]
        np.save(os.path.join(DATA, f"BINANCEF_{sym}_1m.npy"), m1)
        print(f"{sym}: 1m bars {len(m1)}  {dt.datetime.fromtimestamp(m1[0, 0], dt.UTC):%Y-%m-%d} -> {dt.datetime.fromtimestamp(m1[-1, 0], dt.UTC):%Y-%m-%d}", flush=True)
        for tf, tf_s in TFS.items():
            bars = resample(m1, tf_s)
            bars = bars[bars[:, 0] + tf_s <= m1[-1, 0] + 60]   # only closed bars
            path = os.path.join(DATA, f"BINANCEF_{sym}_{tf}.csv")
            np.savetxt(path + ".part", bars, delimiter=",", header="t,o,h,l,c,v", comments="", fmt=["%d", "%.4f", "%.4f", "%.4f", "%.4f", "%.4f"])
            os.replace(path + ".part", path)
            print(f"  {tf}: {len(bars)} bars", flush=True)


if __name__ == "__main__":
    main()
