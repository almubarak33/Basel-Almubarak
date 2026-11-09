#!/usr/bin/env python3
"""Deep crypto history from Binance's public market-data mirror (no key needed).

Usage: python3 fetch_binance.py [--force]   # default universe below; existing files are skipped unless --force
Writes data/BINANCEX_<SYMBOL>_<interval>.csv (t = bar open, unix seconds UTC). Only closed bars are kept.
Files are written atomically (temp file + rename) so readers never see a partial series.
"""
import json
import os
import sys
import time
import urllib.request

BASE = "https://data-api.binance.vision/api/v3/klines"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
ITV = {"5m": "5m", "15m": "15m", "1h": "1h", "4h": "4h", "1D": "1d"}
# symbol -> {interval: max bars}
UNIVERSE = {
    "BTCUSDT": {"5m": 100000, "15m": 60000, "1h": 50000, "4h": 20000, "1D": 4000},
    "ETHUSDT": {"5m": 100000, "15m": 60000, "1h": 50000, "4h": 20000, "1D": 4000},
    "SOLUSDT": {"5m": 100000, "1h": 40000, "4h": 12000, "1D": 3000},
    "BNBUSDT": {"1h": 40000, "4h": 20000, "1D": 4000},
    "XRPUSDT": {"1h": 40000, "4h": 20000, "1D": 4000},
}


def get(url):
    for attempt in range(5):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "apex-research/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except Exception as e:  # network hiccup: back off and retry
            time.sleep(2 ** attempt)
            last = e
    raise last


def fetch(symbol, itv, max_bars):
    rows = {}
    end = None
    now_ms = int(time.time() * 1000)
    while len(rows) < max_bars:
        url = f"{BASE}?symbol={symbol}&interval={ITV[itv]}&limit=1000" + (f"&endTime={end}" if end else "")
        k = get(url)
        if not k:
            break
        for r in k:
            if r[6] < now_ms:  # close time in the past -> bar is closed
                rows[r[0] // 1000] = (r[1], r[2], r[3], r[4], r[5])
        first = k[0][0]
        if end is not None and first >= end:
            break
        end = first - 1
        if len(k) < 1000:
            break
        time.sleep(0.15)
    ts = sorted(rows)[-max_bars:]
    path = os.path.join(OUT, f"BINANCEX_{symbol}_{itv}.csv")
    tmp = path + ".part"
    with open(tmp, "w") as fh:
        fh.write("t,o,h,l,c,v\n")
        for t in ts:
            o, h, l, c, v = rows[t]
            fh.write(f"{t},{float(o)},{float(h)},{float(l)},{float(c)},{float(v)}\n")
    os.replace(tmp, path)
    print(f"{os.path.basename(path):36s} {len(ts):6d}  {time.strftime('%Y-%m-%d', time.gmtime(ts[0]))} -> {time.strftime('%Y-%m-%d', time.gmtime(ts[-1]))}", flush=True)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    force = "--force" in sys.argv
    for sym, spec in UNIVERSE.items():
        for itv, n in spec.items():
            if not force and os.path.exists(os.path.join(OUT, f"BINANCEX_{sym}_{itv}.csv")):
                continue
            fetch(sym, itv, n)
