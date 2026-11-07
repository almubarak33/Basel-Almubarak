"""Download OHLCV research data (public sources, no API key).

Sources
- Binance public data archive (data.binance.vision): XAUUSDT / XAGUSDT USDT-M perpetuals
  (gold / silver, spot-tracking, no contract rolls) and PAXGUSDT spot (tokenised gold, longer history).
- Yahoo Finance chart API: GC=F (COMEX gold futures, 1h, ~730 days).

Output: research/data/<SYMBOL>_<TF>.csv.gz with columns t (unix sec, UTC bar open), o, h, l, c, v.
"""
import datetime as dt
import io
import json
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

import pandas as pd

OUT = Path(__file__).resolve().parent / "data"
OUT.mkdir(exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (research script)"}


def get(url, tries=4):
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(2 ** (k + 1))
        except Exception:
            time.sleep(2 ** (k + 1))
    return None


def parse_kline_zip(blob):
    z = zipfile.ZipFile(io.BytesIO(blob))
    name = z.namelist()[0]
    raw = z.read(name).decode()
    rows = []
    for line in raw.splitlines():
        p = line.split(",")
        if not p[0].isdigit():
            continue  # header row (newer archives)
        t = int(p[0])
        if t > 1e14:  # microseconds (spot archives from 2025)
            t //= 1000
        rows.append((t // 1000, float(p[1]), float(p[2]), float(p[3]), float(p[4]), float(p[5])))
    return rows


def binance(symbol, tf, market, start, end):
    base = "https://data.binance.vision/data/" + ("futures/um" if market == "um" else "spot")
    rows = []
    d = dt.date(start[0], start[1], 1)
    last_month_done = None
    today = dt.date.today()
    while d <= dt.date(end[0], end[1], 1):
        url = f"{base}/monthly/klines/{symbol}/{tf}/{symbol}-{tf}-{d:%Y-%m}.zip"
        blob = get(url)
        if blob:
            rows += parse_kline_zip(blob)
            last_month_done = d
        d = (d.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    # current month: daily archives
    day = (last_month_done.replace(day=28) + dt.timedelta(days=4)).replace(day=1) if last_month_done else today.replace(day=1)
    while day < today:
        url = f"{base}/daily/klines/{symbol}/{tf}/{symbol}-{tf}-{day:%Y-%m-%d}.zip"
        blob = get(url)
        if blob:
            rows += parse_kline_zip(blob)
        day += dt.timedelta(days=1)
    df = pd.DataFrame(rows, columns=["t", "o", "h", "l", "c", "v"]).drop_duplicates("t").sort_values("t")
    return df


def yahoo(symbol, interval, rng):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval={interval}&range={rng}"
    js = json.loads(get(url))
    r = js["chart"]["result"][0]
    q = r["indicators"]["quote"][0]
    df = pd.DataFrame({"t": r["timestamp"], "o": q["open"], "h": q["high"], "l": q["low"], "c": q["close"], "v": q["volume"]})
    return df.dropna(subset=["o", "h", "l", "c"]).drop_duplicates("t").sort_values("t")


def save(df, name):
    df.to_csv(OUT / f"{name}.csv.gz", index=False, compression="gzip")
    t0 = dt.datetime.utcfromtimestamp(df.t.iloc[0]); t1 = dt.datetime.utcfromtimestamp(df.t.iloc[-1])
    print(f"{name:22s} {len(df):7d} bars  {t0:%Y-%m-%d} -> {t1:%Y-%m-%d %H:%M}")


if __name__ == "__main__":
    jobs = sys.argv[1:] or ["all"]
    now = dt.date.today()
    if "all" in jobs or "xau" in jobs:
        for tf in ["5m", "15m", "1h"]:
            save(binance("XAUUSDT", tf, "um", (2025, 12), (now.year, now.month)), f"XAUUSDT_{tf}")
    if "all" in jobs or "xag" in jobs:
        save(binance("XAGUSDT", "15m", "um", (2026, 1), (now.year, now.month)), "XAGUSDT_15m")
    if "all" in jobs or "paxg" in jobs:
        for tf in ["15m", "1h"]:
            save(binance("PAXGUSDT", tf, "spot", (2021, 1), (now.year, now.month)), f"PAXGUSDT_{tf}")
    if "all" in jobs or "yahoo" in jobs:
        save(yahoo("GC=F", "60m", "730d"), "GC_F_1h")
