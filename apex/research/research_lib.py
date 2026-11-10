#!/usr/bin/env python3
"""Research harness for the APEX engine: universe definition, train/test protocol, evaluation helpers.

Protocol (fixed before any tuning, to keep the results honest):
  * one feed per (underlying, timeframe): the deepest series is PRIMARY, the other feed is a REPLICA
    (e.g. OANDA spot gold vs COMEX gold futures) used only to check that a result is not feed-specific;
  * instruments are split into TUNE and HOLDOUT groups (holdout instruments are never used to choose anything);
  * every series is split in time: first 60% of bars = in-sample (IS), last 40% = out-of-sample (OOS);
  * cells:  TRAIN = TUNE x IS   (all decisions are made here)
            TEST_TIME = TUNE x OOS,  TEST_INSTR = HOLDOUT x (IS + OOS)  (reported, never tuned on).
A trade belongs to the segment that contains its ENTRY bar.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace

import numpy as np

import datasets as ds

import engine_v2 as E                  # verified v1 port (engine_b) + the v2 management rule and the replay

IS_FRACTION = 0.60
TF_ORDER = ["5m", "15m", "1h", "4h", "1D"]

# underlying -> asset class
ASSET_CLASS = {
    "GOLD": "metal", "SILVER": "metal", "PLATINUM": "metal", "COPPER": "metal",
    "WTI": "energy", "BRENT": "energy", "NATGAS": "energy",
    "EURUSD": "fx", "GBPUSD": "fx", "USDJPY": "fx", "AUDUSD": "fx", "USDCAD": "fx",
    "SPX": "index", "NDX": "index", "DOW": "index", "DAX": "index", "TASI": "index", "SPY": "index",
    "BTC": "crypto", "ETH": "crypto", "SOL": "crypto", "BNB": "crypto", "XRP": "crypto",
    "AAPL": "stock", "NVDA": "stock", "TSLA": "stock", "MSFT": "stock", "XOM": "stock",
    "RAJHI": "stock", "SABIC": "stock", "ARAMCO": "stock",
}
# ticker in the dataset name -> underlying
UNDERLYING = {
    "XAUUSD": "GOLD", "GOLD": "GOLD", "XAGUSD": "SILVER", "SILVER": "SILVER", "XPTUSD": "PLATINUM",
    "XCUUSD": "COPPER", "COPPER": "COPPER", "WTICOUSD": "WTI", "WTI": "WTI", "BCOUSD": "BRENT", "BRENT": "BRENT",
    "NATGASUSD": "NATGAS", "NATGAS": "NATGAS",
    "EURUSD": "EURUSD", "GBPUSD": "GBPUSD", "USDJPY": "USDJPY", "AUDUSD": "AUDUSD", "USDCAD": "USDCAD",
    "SPX500USD": "SPX", "ES": "SPX", "NAS100USD": "NDX", "NQ": "NDX", "US30USD": "DOW", "YM": "DOW",
    "DE30EUR": "DAX", "TASI": "TASI", "SPY": "SPY",
    "BTCUSDT": "BTC", "ETHUSDT": "ETH", "SOLUSDT": "SOL", "BNBUSDT": "BNB", "XRPUSDT": "XRP",
    "AAPL": "AAPL", "NVDA": "NVDA", "TSLA": "TSLA", "MSFT": "MSFT", "XOM": "XOM",
    "1120": "RAJHI", "2010": "SABIC", "2222": "ARAMCO",
}
# Feeds added later for the gold / silver study (metals_lib.py); the cross-asset universe below stays as it was.
METALS_STUDY_FEEDS = ("HISTDATA_", "BINANCEF_")
# Holdout instruments: fixed up front, roughly one third of every asset class.
HOLDOUT = {"SILVER", "BRENT", "GBPUSD", "USDCAD", "NDX", "DOW", "DAX", "SPY", "ETH", "XRP",
           "MSFT", "XOM", "TSLA", "RAJHI", "ARAMCO"}


@dataclass
class Series:
    name: str
    underlying: str
    asset: str
    tf: str
    role: str            # "primary" | "replica"
    group: str           # "tune" | "holdout"
    chart: dict
    market: object
    htf: dict
    base: dict           # engine base features (parameter independent)
    split: int           # first OOS bar index

    @property
    def n(self) -> int:
        return len(self.chart["c"])


_CACHE: dict[str, Series] = {}


def _meta(name: str):
    m = ds.market_of(name)
    return m, UNDERLYING[m.ticker]


def universe(roles=("primary",), tfs=None, groups=("tune", "holdout")) -> list[Series]:
    """Load (and cache) every series of the requested roles / timeframes / groups."""
    names = [n for n in ds.list_datasets() if not n.startswith(METALS_STUDY_FEEDS)]
    by_key: dict[tuple, list[str]] = {}
    for n in names:
        m, u = _meta(n)
        by_key.setdefault((u, m.interval), []).append(n)
    out = []
    for (u, tf), cands in sorted(by_key.items()):
        if tfs and tf not in tfs:
            continue
        sizes = {n: sum(1 for _ in open(f"{ds.DATA}/{n}.csv")) for n in cands}
        primary = max(cands, key=lambda n: (sizes[n], n))
        for n in cands:
            role = "primary" if n == primary else "replica"
            group = "holdout" if u in HOLDOUT else "tune"
            if role not in roles or group not in groups:
                continue
            if n not in _CACHE:
                chart = ds.load(n)
                market = ds.market_of(n, chart)
                htf, _ = ds.htf_bars(n, chart)
                base = E.base_features(chart, htf, market)
                _CACHE[n] = Series(n, u, ASSET_CLASS[u], tf, role, group, chart, market, htf, base,
                                   int(len(chart["c"]) * IS_FRACTION))
            s = _CACHE[n]
            s.role, s.group = role, group
            out.append(s)
    return out


# ───────────────────────────── evaluation ─────────────────────────────
TRADE_FIELDS = ("series", "underlying", "asset", "tf", "group", "seg", "dir", "entry_bar", "exit_bar", "t",
                "trig", "score", "R", "gross_R", "cost_R", "hit1", "hit2", "hit3", "reason", "risk_pct", "bars")


def run_series(s: Series, params=None, mgmt: dict | None = None, cost_pct: float | None = None,
               sig_filter=None, feats: dict | None = None):
    """Run the engine on one series.

    params      engine Params (signal + stop settings; default = Pine defaults)
    mgmt        override of the management dict {"k1","k2","k3","w1","w2","trailOn","trailFrom","beOn"}
    cost_pct    override of the round-trip cost in percent of price (also used by nothing else here)
    sig_filter  callable(series, feats) -> (allowL, allowS) boolean arrays AND-ed into longSig / shortSig
    Returns (list of trade dicts, feats).
    """
    p = params or E.Params()
    f = feats if feats is not None else E.features(s.chart, s.htf, p, s.market, s.base)
    long_sig, short_sig = f["longSig"], f["shortSig"]
    if sig_filter is not None:
        al, as_ = sig_filter(s, f)
        long_sig = long_sig & al
        short_sig = short_sig & as_
    m = dict(E.mgmt_of(p, s.market))
    if mgmt:
        m.update(mgmt)
    cp = f["costPct"] if cost_pct is None else cost_pct
    c = s.chart
    rec, _op, _st = E.simulate_arrays(c["o"], c["h"], c["l"], c["c"], long_sig, short_sig, f["slDistL"], f["slDistS"],
                                      f["chandL"], f["chandS"], m, cp, f["mintick"], f["trigCodeL"], f["trigCodeS"],
                                      f["scoreL"], f["scoreS"])
    trades = []
    for r in E.trades_list(rec):
        eb = r["entry_bar"]
        trades.append({
            "series": s.name, "underlying": s.underlying, "asset": s.asset, "tf": s.tf, "group": s.group,
            "seg": "IS" if eb < s.split else "OOS", "dir": r["dir"], "entry_bar": eb, "exit_bar": r["exit_bar"],
            "t": int(c["t"][eb]), "trig": r["trig"], "score": r["score"], "R": r["R"], "gross_R": r["gross_R"],
            "cost_R": r["cost_R"], "hit1": r["hit1"], "hit2": r["hit2"], "hit3": r["hit3"], "reason": r["reason"],
            "risk_pct": 100.0 * r["risk"] / r["entry"], "bars": r["exit_bar"] - eb,
        })
    return trades, f


def fine_for(s: Series, min_chart_bars: int = 400):
    """Finer series of the SAME feed that covers at least `min_chart_bars` chart bars (1h preferred, then 4h
    for daily charts; 15m for 4h charts).  -> (name, bars) or (None, None)."""
    m = s.market
    for itv in {"1D": ("1h", "4h"), "4h": ("15m",), "1h": ("5m",)}.get(s.tf, ()):
        name = f"{m.exchange}_{m.ticker}_{itv}"
        try:
            fine = ds.load(name)
        except OSError:
            continue
        di = np.searchsorted(s.chart["t"], fine["t"], side="right") - 1
        if len(np.unique(di[di >= 0])) >= min_chart_bars:
            return name, fine
    return None, None


def replay(s: Series, params=None, mgmt: dict | None = None, cost_pct: float | None = None):
    """Intrabar replay of one series (see engine_v2.magnify).

    -> None when no finer series is available, else (replayed trades, chart-bar trades) over the same
    period, both as trade dicts like run_series() returns."""
    name, fine = fine_for(s)
    if name is None:
        return None
    p = params or E.Params()
    f = E.features(s.chart, s.htf, p, s.market, s.base)
    m = dict(E.mgmt_of(p, s.market))
    if mgmt:
        m.update(mgmt)
    rec_f, rec_c, fb, _d0 = E.magnify(s.chart, f, fine, m, cost_pct)
    t_split = int(s.chart["t"][min(s.split, s.n - 1)])

    def conv(rec, times):
        out = []
        for r in E.trades_list(rec):
            t = int(times[r["entry_bar"]])
            out.append({"series": s.name, "underlying": s.underlying, "asset": s.asset, "tf": s.tf, "group": s.group,
                        "seg": "IS" if t < t_split else "OOS", "dir": r["dir"], "entry_bar": r["entry_bar"],
                        "exit_bar": r["exit_bar"], "t": t, "trig": r["trig"], "score": r["score"], "R": r["R"],
                        "gross_R": r["gross_R"], "cost_R": r["cost_R"], "hit1": r["hit1"], "hit2": r["hit2"],
                        "hit3": r["hit3"], "reason": r["reason"], "risk_pct": 100.0 * r["risk"] / r["entry"],
                        "bars": r["exit_bar"] - r["entry_bar"], "fine": name})
        return out
    return conv(rec_f, fb["t"]), conv(rec_c, s.chart["t"])


def run_universe(series: list[Series], params=None, mgmt=None, cost_pct=None, sig_filter=None,
                 params_fn=None, mgmt_fn=None, cost_fn=None) -> list[dict]:
    """Run a configuration over many series.  *_fn(series) variants allow per-series settings."""
    out = []
    for s in series:
        p = params_fn(s) if params_fn else params
        m = mgmt_fn(s) if mgmt_fn else mgmt
        cp = cost_fn(s) if cost_fn else cost_pct
        t, _ = run_series(s, p, m, cp, sig_filter)
        out.extend(t)
    return out


def cell(trades: list[dict], which: str) -> list[dict]:
    """TRAIN | TEST_TIME | TEST_INSTR | ALL"""
    if which == "TRAIN":
        return [t for t in trades if t["group"] == "tune" and t["seg"] == "IS"]
    if which == "TEST_TIME":
        return [t for t in trades if t["group"] == "tune" and t["seg"] == "OOS"]
    if which == "TEST_INSTR":
        return [t for t in trades if t["group"] == "holdout"]
    if which == "TEST":
        return [t for t in trades if not (t["group"] == "tune" and t["seg"] == "IS")]
    return list(trades)


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson interval for a proportion."""
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, mid - half), min(1.0, mid + half))


def summary(trades: list[dict]) -> dict:
    n = len(trades)
    if n == 0:
        return {"n": 0, "win": float("nan"), "win_lo": float("nan"), "win_hi": float("nan"), "tp1": float("nan"),
                "avgR": float("nan"), "netR": 0.0, "pf": float("nan"), "maxDD": 0.0, "avg_win": float("nan"),
                "avg_loss": float("nan"), "sl": float("nan"), "cost": float("nan"), "t_stat": float("nan")}
    R = np.array([t["R"] for t in trades])
    wins = int((R > 0).sum())
    lo, hi = wilson(wins, n)
    gross = float(R[R > 0].sum())
    loss = float(-R[R < 0].sum())
    # drawdown on the pooled, time-ordered equity curve (1 unit of risk per trade)
    order = np.argsort([t["t"] for t in trades], kind="stable")
    eq = np.cumsum(R[order])
    dd = float(np.max(np.maximum.accumulate(np.maximum(eq, 0.0)) - eq)) if n else 0.0
    sd = float(R.std(ddof=1)) if n > 1 else float("nan")
    return {
        "n": n, "win": wins / n, "win_lo": lo, "win_hi": hi,
        "tp1": sum(t["hit1"] for t in trades) / n,
        "avgR": float(R.mean()), "netR": float(R.sum()),
        "pf": gross / loss if loss > 0 else float("inf"),
        "maxDD": dd,
        "avg_win": float(R[R > 0].mean()) if wins else float("nan"),
        "avg_loss": float(R[R < 0].mean()) if (R < 0).any() else float("nan"),
        "sl": sum(t["reason"] == "SL" for t in trades) / n,
        "cost": float(np.mean([t["cost_R"] for t in trades])),
        "t_stat": float(R.mean() / (sd / math.sqrt(n))) if n > 1 and sd > 0 else float("nan"),
    }


def fmt(s: dict) -> str:
    if s["n"] == 0:
        return "n=0"
    return (f"n={s['n']:5d} win={100*s['win']:5.1f}% [{100*s['win_lo']:4.1f},{100*s['win_hi']:4.1f}] "
            f"tp1={100*s['tp1']:5.1f}% avgR={s['avgR']:+.3f} PF={s['pf']:5.2f} net={s['netR']:+8.1f}R "
            f"maxDD={s['maxDD']:6.1f}R t={s['t_stat']:+.1f}")


def table(trades: list[dict], key, cells=("TRAIN", "TEST_TIME", "TEST_INSTR")) -> str:
    """One line per key value with the summary of every cell."""
    vals = []
    for t in trades:
        v = key(t)
        if v not in vals:
            vals.append(v)
    try:
        vals.sort(key=lambda v: (TF_ORDER.index(v) if v in TF_ORDER else 99, str(v)))
    except Exception:
        pass
    lines = []
    for v in vals:
        sub = [t for t in trades if key(t) == v]
        for c in cells:
            lines.append(f"{str(v):10s} {c:10s} {fmt(summary(cell(sub, c)))}")
    return "\n".join(lines)


def with_params(**kw):
    return replace(E.Params(), **kw)


if __name__ == "__main__":
    uni = universe(roles=("primary", "replica"))
    print(f"{len(uni)} series")
    for tf in TF_ORDER:
        for role in ("primary", "replica"):
            sub = [s for s in uni if s.tf == tf and s.role == role]
            print(f"  {tf:3s} {role:8s} {len(sub):3d} series  {sum(s.n for s in sub):8d} bars   tune={sum(s.group == 'tune' for s in sub)} holdout={sum(s.group == 'holdout' for s in sub)}")
