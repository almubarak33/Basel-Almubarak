"""Download Binance USDT-M futures 5m klines for the pro-scalping-bot's 30 pairs (public archive).
Output: research/data_bot/<SYMBOL>_5m.csv.gz (not committed; re-run this script to reproduce)."""
import io, sys, time, zipfile, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pandas as pd

OUT = Path(__file__).resolve().parent / "data_bot"; OUT.mkdir(exist_ok=True)
SYMS = ["BTC","ETH","SOL","BNB","XRP","DOGE","ADA","AVAX","LINK","DOT","LTC","UNI","NEAR","ARB","OP",
        "SUI","APT","INJ","TIA","FIL","ATOM","FET","JUP","PYTH","WIF","PEPE","SHIB","TRB","AAVE","MKR"]
FUT = {"PEPE": "1000PEPEUSDT", "SHIB": "1000SHIBUSDT"}
MONTHS = [f"{y}-{m:02d}" for y in (2025, 2026) for m in range(1, 13) if (y, m) <= (2026, 10)]

def get(url):
    for k in range(4):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(2 ** (k + 1))
        except Exception:
            time.sleep(2 ** (k + 1))
    raise RuntimeError(f"failed after retries: {url}")

def one(sym):
    t = FUT.get(sym, sym + "USDT")
    frames, missing = [], []
    for m in MONTHS:
        blob = get(f"https://data.binance.vision/data/futures/um/monthly/klines/{t}/5m/{t}-5m-{m}.zip")
        if blob is None:
            missing.append(m); continue
        z = zipfile.ZipFile(io.BytesIO(blob))
        df = pd.read_csv(z.open(z.namelist()[0]), header=None)
        if not str(df.iloc[0, 0]).isdigit():
            df = df.iloc[1:]
        frames.append(df.iloc[:, :6].astype(float))
    df = pd.concat(frames); df.columns = ["ts_ms", "open", "high", "low", "close", "volume"]
    df = df.drop_duplicates("ts_ms").sort_values("ts_ms"); df["ts_ms"] = df["ts_ms"].astype("int64")
    gaps = int((df["ts_ms"].diff() > 300_000).sum())
    df.to_csv(OUT / f"{sym}_5m.csv.gz", index=False, compression="gzip")
    return f"{sym:5s} {len(df):7d} bars  gaps>5m: {gaps:3d}  missing months: {missing or '-'}"

if __name__ == "__main__":
    with ThreadPoolExecutor(6) as ex:
        for line in ex.map(one, SYMS):
            print(line, flush=True)
