#!/usr/bin/env python3
"""Long gold / silver history: histdata.com free 1-minute BID bars (2009 onward, no key needed).

Usage: python3 fetch_histdata.py [START_YEAR]         # default 2010; downloads are cached, reruns resume

Writes (git-ignored, t = bar OPEN time in unix seconds UTC):
  data/histdata_raw/<SYM>_<period>.zip
  data/HISTDATA_<SYM>_1m.npy
  data/HISTDATA_<SYM>_{5m,15m,1h,4h,1D}.csv   resampled with the anchors TradingView uses for OANDA metals:
                                              clock-aligned intraday bars, 4h bars from 17:00 New York,
                                              daily bars 17:00 -> 17:00 New York
The files carry NO volume (the column is always 0): on this feed the script's volume filter passes every bar
and the VWAP-reclaim setup never fires. Source timestamps: see parse().
"""
import datetime as dt
import io
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import zipfile
import zoneinfo

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
RAW = os.path.join(DATA, "histdata_raw")
PAGE = "https://www.histdata.com/download-free-forex-historical-data/?/ascii/1-minute-bar-quotes/{pair}/{period}"
SYMBOLS = ("XAUUSD", "XAGUSD")
UA = "Mozilla/5.0 (apex-research)"
NY = zoneinfo.ZoneInfo("America/New_York")
TFS = {"5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1D": 86400}


def bucket_start(t: np.ndarray, tf_s: int) -> np.ndarray:
    """Open time (UTC seconds) of the bar each minute belongs to."""
    if tf_s <= 3600:
        return (t // tf_s) * tf_s
    # 4h and daily bars are anchored at 17:00 New York (follows daylight saving)
    out = np.empty(len(t), dtype=np.int64)
    days = t // 86400
    for d in np.unique(days):
        sel = days == d
        off = int(dt.datetime.fromtimestamp(int(d) * 86400 + 43200, NY).utcoffset().total_seconds())   # NY offset that day
        local = t[sel] + off - 17 * 3600
        out[sel] = (local // tf_s) * tf_s - off + 17 * 3600
    return out


def resample(m1: np.ndarray, tf_s: int) -> np.ndarray:
    t = m1[:, 0].astype(np.int64)
    b = bucket_start(t, tf_s)
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


def download(sym: str, year: int, month: int | None) -> bytes | None:
    tag = f"{year}" if month is None else f"{year}{month:02d}"
    path = os.path.join(RAW, f"{sym}_{tag}.zip")
    if os.path.exists(path):
        return open(path, "rb").read()
    period = f"{year}" if month is None else f"{year}/{month}"
    page_url = PAGE.format(pair=sym.lower(), period=period)
    for attempt in range(4):
        try:
            html = urllib.request.urlopen(urllib.request.Request(page_url, headers={"User-Agent": UA}), timeout=60).read().decode("utf-8", "replace")
            tk = re.search(r'name="tk" id="tk" value="([0-9a-f]+)"', html)
            if not tk:
                return None                                  # period not published
            form = {"tk": tk.group(1), "date": str(year), "datemonth": tag, "platform": "ASCII", "timeframe": "M1", "fxpair": sym}
            req = urllib.request.Request("https://www.histdata.com/get.php", data=urllib.parse.urlencode(form).encode(),
                                         headers={"User-Agent": UA, "Referer": page_url, "Content-Type": "application/x-www-form-urlencoded"})
            body = urllib.request.urlopen(req, timeout=180).read()
            if body[:2] != b"PK":
                return None
            with open(path + ".part", "wb") as f:
                f.write(body)
            os.replace(path + ".part", path)
            time.sleep(1.0)
            return body
        except Exception as e:
            last = e
            time.sleep(3 * (attempt + 1))
    raise last


def parse(zbytes: bytes) -> np.ndarray:
    """-> rows t,o,h,l,c,v with t in unix seconds UTC.

    The site documents its timestamps as "EST without daylight saving".  Measured against OANDA's bars (see
    validate() in metals_lib.py) they are UTC-5 only during European winter time and UTC-4 during European summer
    time, i.e. the clock is "Eastern European Time minus 7 hours", which is how FX servers keep New York's 17:00
    close at midnight.  Converting through Europe/Helsinki reproduces that rule for every year.
    """
    with zipfile.ZipFile(io.BytesIO(zbytes)) as z:
        name = [n for n in z.namelist() if n.lower().endswith(".csv")][0]
        df = pd.read_csv(io.BytesIO(z.read(name)), sep=";", header=None, usecols=[0, 1, 2, 3, 4],
                         names=["d", "o", "h", "l", "c"], dtype={"d": str})
    eet = pd.to_datetime(df["d"], format="%Y%m%d %H%M%S") + pd.Timedelta(hours=7)
    utc = eet.dt.tz_localize("Europe/Helsinki", ambiguous="NaT", nonexistent="NaT").dt.tz_convert("UTC")
    ok = utc.notna().to_numpy()
    out = np.zeros((int(ok.sum()), 6))
    out[:, 0] = (utc[ok].astype("int64") // 10 ** 9).to_numpy() if str(utc.dtype).endswith("ns, UTC]") else utc[ok].map(lambda x: x.timestamp()).to_numpy()
    for j, k in enumerate(("o", "h", "l", "c"), start=1):
        out[:, j] = df[k].to_numpy()[ok]
    return out


def main() -> None:
    start_year = int(sys.argv[1]) if len(sys.argv) > 1 else 2010
    os.makedirs(RAW, exist_ok=True)
    today = dt.datetime.now(dt.UTC).date()
    for sym in SYMBOLS:
        parts = []
        for year in range(start_year, today.year + 1):
            body = download(sym, year, None)                 # past years come as one file
            if body is not None:
                parts.append(parse(body))
                print(f"{sym} {year}: {len(parts[-1])} bars", flush=True)
                continue
            for month in range(1, 13):                       # the running year comes month by month
                if (year, month) > (today.year, today.month):
                    break
                body = download(sym, year, month)
                if body is not None:
                    parts.append(parse(body))
                    print(f"{sym} {year}-{month:02d}: {len(parts[-1])} bars", flush=True)
        m1 = np.concatenate(parts)
        m1 = m1[np.argsort(m1[:, 0], kind="stable")]
        m1 = m1[np.r_[True, np.diff(m1[:, 0]) > 0]]
        np.save(os.path.join(DATA, f"HISTDATA_{sym}_1m.npy"), m1)
        print(f"{sym}: 1m bars {len(m1)}  {dt.datetime.fromtimestamp(m1[0, 0], dt.UTC):%Y-%m-%d} -> {dt.datetime.fromtimestamp(m1[-1, 0], dt.UTC):%Y-%m-%d}", flush=True)
        for tf, tf_s in TFS.items():
            bars = resample(m1, tf_s)
            path = os.path.join(DATA, f"HISTDATA_{sym}_{tf}.csv")
            np.savetxt(path + ".part", bars, delimiter=",", header="t,o,h,l,c,v", comments="", fmt=["%d", "%.3f", "%.3f", "%.3f", "%.3f", "%.1f"])
            os.replace(path + ".part", path)
            print(f"  {tf}: {len(bars)} bars", flush=True)


if __name__ == "__main__":
    main()
