#!/usr/bin/env python3
"""Convert raw TradingView-MCP get_ohlcv results (saved by the harness as JSON files) into CSVs.

Usage: python3 tv_ingest.py [RAW_DIR] [OUT_DIR]
Each raw file is the tool JSON: {symbol, interval, bars:{t,o,h,l,c,v}, ...} (format="columns").
Pages of the same (symbol, interval) are merged, de-duplicated on t and sorted.
The still-forming last bar is dropped (bar open + interval must be <= file mtime).
Files are written atomically and only when their content changed.
Output: OUT_DIR/<EXCHANGE>_<TICKER>_<interval>.csv with header t,o,h,l,c,v (t = unix seconds UTC, bar OPEN time)
and OUT_DIR/manifest.json.
"""
import glob
import json
import os
import sys
import datetime as dt

RAW = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser(
    "~/.claude/projects/-home-user-Basel-Almubarak/b1e14752-86e3-5900-b6b0-752861a1bc27/tool-results")
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
SEC = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1D": 86400, "1W": 604800}


def main():
    os.makedirs(OUT, exist_ok=True)
    series = {}
    for f in sorted(glob.glob(os.path.join(RAW, "mcp-tradingview-mcp-tv-get-ohlcv-*.txt"))):
        try:
            d = json.load(open(f))
        except Exception as e:  # not a JSON payload
            print("skip", os.path.basename(f), e)
            continue
        if not d.get("success") or "bars" not in d or not isinstance(d["bars"], dict):
            print("skip (no column bars)", os.path.basename(f))
            continue
        key = (d["symbol"], d["interval"])
        b = d["bars"]
        mtime = os.path.getmtime(f)
        rows = series.setdefault(key, {})
        step = SEC.get(d["interval"], 0)
        for i in range(len(b["t"])):
            t = int(b["t"][i])
            if step and t + step > mtime:  # bar still forming when fetched
                continue
            rows[t] = (b["o"][i], b["h"][i], b["l"][i], b["c"][i], b["v"][i])
    manifest = []
    for (sym, itv), rows in sorted(series.items()):
        ts = sorted(rows)
        name = f"{sym.replace(':', '_')}_{itv}.csv"
        body = "t,o,h,l,c,v\n" + "".join(f"{t},{rows[t][0]},{rows[t][1]},{rows[t][2]},{rows[t][3]},{rows[t][4]}\n" for t in ts)
        path = os.path.join(OUT, name)
        if not os.path.exists(path) or open(path).read() != body:   # leave unchanged files untouched
            with open(path + ".part", "w") as fh:
                fh.write(body)
            os.replace(path + ".part", path)                         # atomic: readers never see a partial file
        iso = lambda x: dt.datetime.fromtimestamp(x, dt.UTC).strftime("%Y-%m-%d %H:%M")
        manifest.append({"file": name, "symbol": sym, "interval": itv, "bars": len(ts),
                         "first": iso(ts[0]), "last": iso(ts[-1]), "source": "TradingView MCP get_ohlcv"})
        print(f"{name:40s} {len(ts):6d}  {iso(ts[0])} -> {iso(ts[-1])}")
    json.dump(manifest, open(os.path.join(OUT, "manifest.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
