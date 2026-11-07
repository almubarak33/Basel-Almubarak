"""Download silver, crypto and stock datasets for the cross-asset test."""
import datetime as dt
import fetch_data as fd
now = dt.date.today()
jobs = [("XAGUSDT", "5m", "um", (2026, 1)), ("XAGUSDT", "1h", "um", (2026, 1))]
for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
    jobs += [(sym, "5m", "spot", (2024, 1)), (sym, "15m", "spot", (2023, 1)), (sym, "1h", "spot", (2023, 1))]
for sym, tf, mkt, start in jobs:
    fd.save(fd.binance(sym, tf, mkt, start, (now.year, now.month)), f"{sym}_{tf}")
fd.save(fd.yahoo("SI=F", "60m", "730d"), "SI_F_1h")
fd.save(fd.yahoo("SI=F", "1d", "5y"), "SI_F_1d")
for s in ["SPY", "QQQ", "AAPL", "NVDA", "TSLA", "MSFT", "AMZN", "META"]:
    for iv, rng, tag in [("5m", "60d", "5m"), ("15m", "60d", "15m"), ("60m", "730d", "1h"), ("1d", "5y", "1d")]:
        try:
            fd.save(fd.yahoo(s, iv, rng), f"{s}_{tag}")
        except Exception as e:
            print("FAILED", s, iv, e)
