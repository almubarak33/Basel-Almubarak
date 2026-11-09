#!/usr/bin/env python3
"""Extra intraday depth for non-crypto markets from Yahoo Finance's public chart API (no key needed).

TradingView's feed only returns about 4 weeks of 5-minute bars; Yahoo serves 60 days of 5m/15m and
about 2 years of 1h for the front futures contracts and FX, as an independent second feed.

Usage: python3 fetch_yahoo.py [--force]
Writes data/YF_<NAME>_<interval>.csv (t = bar open, unix seconds UTC). Only closed, well-formed bars are kept.
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
# dataset name -> Yahoo symbol.  Names containing SILVER get the script's higher metal cost.
SYMBOLS = {
    "GOLD": "GC=F", "SILVER": "SI=F", "WTI": "CL=F", "BRENT": "BZ=F", "COPPER": "HG=F", "NATGAS": "NG=F",
    "EURUSD": "EURUSD=X", "GBPUSD": "GBPUSD=X", "USDJPY": "JPY=X", "AUDUSD": "AUDUSD=X",
    "ES": "ES=F", "NQ": "NQ=F", "YM": "YM=F",
}
# our interval -> (yahoo interval, range, bar seconds)
SPECS = {"5m": ("5m", "60d", 300), "15m": ("15m", "60d", 900), "1h": ("60m", "730d", 3600), "1D": ("1d", "max", 86400)}


def get(url):
    last = None
    for attempt in range(5):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (apex-research)"})
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.loads(r.read())
        except Exception as e:  # network hiccup / throttling: back off and retry
            last = e
            time.sleep(2 ** attempt)
    raise last


def fetch(name, ysym, itv):
    yitv, rng, step = SPECS[itv]
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(ysym)}?interval={yitv}&range={rng}&includePrePost=false"
    res = get(url)["chart"]["result"][0]
    ts = res.get("timestamp") or []
    q = res["indicators"]["quote"][0]
    now = time.time()
    rows = {}
    for i, t in enumerate(ts):
        o, h, l, c, v = q["open"][i], q["high"][i], q["low"][i], q["close"][i], q["volume"][i]
        if None in (o, h, l, c) or min(o, h, l, c) <= 0 or h < l or h < max(o, c) or l > min(o, c):
            continue                                    # holes and malformed rows
        if itv != "1D":
            t -= t % step                               # align to the bar grid (last bar can carry a live stamp)
        if t + step > now:
            continue                                    # still forming
        rows[t] = (o, h, l, c, v or 0)
    tss = sorted(rows)
    if len(tss) < 400:
        print(f"YF_{name}_{itv}: only {len(tss)} bars - skipped", flush=True)
        return
    path = os.path.join(OUT, f"YF_{name}_{itv}.csv")
    with open(path + ".part", "w") as fh:
        fh.write("t,o,h,l,c,v\n")
        for t in tss:
            o, h, l, c, v = rows[t]
            fh.write(f"{t},{o},{h},{l},{c},{v}\n")
    os.replace(path + ".part", path)
    print(f"{os.path.basename(path):26s} {len(tss):6d}  {time.strftime('%Y-%m-%d', time.gmtime(tss[0]))} -> {time.strftime('%Y-%m-%d', time.gmtime(tss[-1]))}", flush=True)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    force = "--force" in sys.argv
    for name, ysym in SYMBOLS.items():
        for itv in SPECS:
            if not force and os.path.exists(os.path.join(OUT, f"YF_{name}_{itv}.csv")):
                continue
            try:
                fetch(name, ysym, itv)
            except Exception as e:
                print(f"YF_{name}_{itv}: FAILED {type(e).__name__} {e}", flush=True)
            time.sleep(0.4)
