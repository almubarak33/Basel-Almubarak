#!/usr/bin/env python3
"""Gold / silver study helpers for the Fusion engine.

Feeds (all loaded through datasets.py, market data is git-ignored):
  deep  HISTDATA_*   histdata.com 1-minute bid quotes, 2010-01 -> 2026-10, resampled like OANDA on TradingView;
                     no volume, so the volume filter passes every bar and the VWAP setup never fires
  tv    OANDA_*      the TradingView feed the indicator runs on (short intraday history, tick volume)
  perp  BINANCEF_*   Binance USDT perpetuals, 2025-12 -> 2026-11, traded volume, open around the clock

Protocol (fixed before any tuning): on the deep feed TRAIN = entries before 2020-01-01, TEST = entries from
2020-01-01; choices are made on TRAIN only.  The other feeds are never tuned on.
Every simulation on the deep and perp feeds is replayed on 1-minute bars (signals from the chart timeframe,
fills / stops / targets decided minute by minute) with the v2 rule closeStop = 1 unless stated otherwise.
"""
from __future__ import annotations

import datetime as dt
import math
from dataclasses import replace

import numpy as np

import datasets as ds
import engine_b as B
import fusion_engine as F
from research_lib import wilson

NAN = float("nan")
SPLIT_T = int(dt.datetime(2020, 1, 1, tzinfo=dt.UTC).timestamp())
TFS = ["5m", "15m", "1h", "4h", "1D"]
METALS = ["GOLD", "SILVER"]
FEED_EXCHANGE = {"deep": "HISTDATA", "tv": "OANDA", "perp": "BINANCEF"}
FEED_TICKER = {("GOLD", "deep"): "XAUUSD", ("SILVER", "deep"): "XAGUSD", ("GOLD", "tv"): "XAUUSD", ("SILVER", "tv"): "XAGUSD",
               ("GOLD", "perp"): "XAUUSDT", ("SILVER", "perp"): "XAGUSDT"}


def series_name(metal: str, feed: str, tf: str) -> str:
    return f"{FEED_EXCHANGE[feed]}_{FEED_TICKER[(metal, feed)]}_{tf}"


_FEATS: dict = {}


_KERNEL_ONLY = ("profile", "cTp1", "cW1", "cTp2", "cW2", "cTp3", "cTrail", "cBe", "tp1CostMult", "maxBars", "reverseOn",
                "pbFrac", "pbBars")


def feats(name: str, p: F.FParams):
    """Cached features.  Inputs that only reach the trade kernel are left out of the key; the profile matters only
    through Ultra's wider stop."""
    ctx = F.context(name)
    m = ctx["market"]
    ultra = F.resolve_profile(m, p) == "ULT" and 3600 <= m.tf_seconds < 86400
    key = (name, ultra, tuple(sorted((k, v) for k, v in vars(p).items() if k not in _KERNEL_ONLY)))
    if key not in _FEATS:
        if len(_FEATS) > 40:                       # features of million-bar series are large: keep the cache bounded
            _FEATS.pop(next(iter(_FEATS)))
        _FEATS[key] = F.features(ctx, p)
    return _FEATS[key]


# ───────────────────────────── 1-minute replay (cached mapping) ─────────────────────────────
class _Map:
    __slots__ = ("o", "h", "l", "c", "t", "di", "last_idx", "di_last", "d0", "per_bar", "nan", "zf", "zi")


_MAPS: dict = {}


def _map(name: str) -> _Map:
    if name in _MAPS:
        return _MAPS[name]
    ctx = F.context(name)
    m = ctx["market"]
    fine = ds.load_1m(m.exchange, m.ticker)
    ct = np.asarray(ctx["chart"]["t"])
    di = np.searchsorted(ct, fine["t"], side="right") - 1
    keep = di >= 0
    r = _Map()
    r.di = di[keep]
    r.o, r.h, r.l, r.c = (np.ascontiguousarray(fine[k][keep], dtype=np.float64) for k in ("o", "h", "l", "c"))
    r.t = fine["t"][keep]
    last = np.ones(len(r.di), np.bool_)
    last[:-1] = r.di[1:] != r.di[:-1]
    r.last_idx = np.flatnonzero(last)
    r.di_last = r.di[r.last_idx]
    r.d0 = int(r.di[0])
    r.per_bar = max(1, int(round(len(r.di) / max(1, len(np.unique(r.di))))))
    r.nan = np.full(len(r.di), NAN)
    r.zf = np.zeros(len(r.di))
    r.zi = np.zeros(len(r.di), np.int64)
    if len(_MAPS) >= 2:                            # two 6-million-bar maps at most in memory
        _MAPS.pop(next(iter(_MAPS)))
    _MAPS[name] = r
    return r


def replay(name: str, f: dict, p: F.FParams, mgmt: dict | None = None, cost: float | None = None,
           use_pullback: bool | None = None, long_sig=None, short_sig=None) -> list[dict]:
    """Same result as fusion_engine.replay()[0] (checked in test_metals.py), with the bar mapping cached."""
    ctx = F.context(name)
    rm = _map(name)
    m = dict(F.mgmt_of(ctx["market"], p))
    if mgmt:
        m.update(mgmt)
    nf = len(rm.di)
    ls_c = np.array(f["longSig"] if long_sig is None else long_sig, np.bool_)
    ss_c = np.array(f["shortSig"] if short_sig is None else short_sig, np.bool_)
    ls_c[:rm.d0 + 1] = False
    ss_c[:rm.d0 + 1] = False
    ls_f = np.zeros(nf, np.bool_)
    ss_f = np.zeros(nf, np.bool_)
    ls_f[rm.last_idx] = ls_c[rm.di_last]
    ss_f[rm.last_idx] = ss_c[rm.di_last]

    def at_last(x, dtype):                         # the kernel reads these on signal bars only
        out = np.zeros(nf, dtype)
        out[rm.last_idx] = np.asarray(x)[rm.di_last]
        return out
    if m["trailOn"]:
        prev = np.maximum(rm.di - 1, 0)
        ch_l = np.asarray(f["chandL"])[prev].astype(np.float64)
        ch_s = np.asarray(f["chandS"])[prev].astype(np.float64)
        ch_l[rm.di == 0] = NAN
        ch_s[rm.di == 0] = NAN
        ch_l = np.concatenate([ch_l[1:], [NAN]])
        ch_s = np.concatenate([ch_s[1:], [NAN]])
    else:
        ch_l = ch_s = rm.nan
    up = f["usePullback"] if use_pullback is None else use_pullback
    cp = f["costPct"] if cost is None else cost
    rec, _, n_sig, n_fill, _ = F._core_fusion(
        rm.o, rm.h, rm.l, rm.c, ls_f, ss_f, at_last(f["slDistL"], np.float64), at_last(f["slDistS"], np.float64), ch_l, ch_s,
        at_last(np.maximum(f["setupL"], 0), np.int64), at_last(np.maximum(f["setupS"], 0), np.int64),
        at_last(f["scoreL"], np.int64), at_last(f["scoreS"], np.int64),
        float(m["k1"]), float(m["k2"]), float(m["k3"]), float(m["w1"]), float(m["w2"]), bool(m["trailOn"]),
        int(m["trailFrom"]), bool(m["beOn"]), float(cp), float(f["mintick"]), int(m.get("closeStop", 1)),
        bool(up), float(p.pbFrac), int(p.pbBars) * rm.per_bar, int(p.maxBars) * rm.per_bar, bool(p.reverseOn),
        float(m.get("tp1CostMult", 0.0)))
    return _rows(rec, rm.t, name, int(n_sig), int(n_fill))


def chart_sim(name: str, f: dict, p: F.FParams, mgmt: dict | None = None, cost: float | None = None,
              use_pullback: bool | None = None) -> list[dict]:
    """Chart-bar simulation (what the indicator does without intrabar data); closeStop defaults to 1."""
    ctx = F.context(name)
    mg = {"closeStop": 1}
    mg.update(mgmt or {})
    trades, _st, info = F.simulate(ctx, f, p, mg, cost, use_pullback=use_pullback)
    t = ctx["chart"]["t"]
    out = []
    for r in trades:
        out.append({"series": name, "t": int(t[r["entry_bar"]]), "t_exit": int(t[r["exit_bar"]]), "dir": r["dir"],
                    "setup": r["setup"], "score": r["score"], "R": r["R"], "gross_R": r["gross_R"], "cost_R": r["cost_R"],
                    "hit1": r["hit1"], "hit2": r["hit2"], "hit3": r["hit3"], "reason": r["reason"],
                    "risk_pct": 100.0 * r["risk"] / r["entry"], "signals": info["signals"], "filled": info["filled"]})
    return out


def _rows(rec, times, name, n_sig, n_fill) -> list[dict]:
    out = []
    for r in rec.tolist():
        out.append({"series": name, "t": int(times[int(r[F.C_EBAR])]), "t_exit": int(times[int(r[F.C_XBAR])]),
                    "dir": int(r[F.C_DIR]), "setup": F.SETUPS[int(r[F.C_TRIG])], "score": int(r[F.C_SCORE]),
                    "R": r[F.C_R], "gross_R": r[F.C_GROSS], "cost_R": r[F.C_COST], "hit1": r[F.C_HIT1] != 0.0,
                    "hit2": r[F.C_HIT2] != 0.0, "hit3": r[F.C_HIT3] != 0.0, "reason": F.REASONS[int(r[F.C_REASON])],
                    "risk_pct": 100.0 * r[F.C_RISK] / r[F.C_ENTRY], "signals": n_sig, "filled": n_fill})
    return out


# ───────────────────────────── evaluation ─────────────────────────────
def seg(trades: list[dict], which: str) -> list[dict]:
    if which == "TRAIN":
        return [t for t in trades if t["t"] < SPLIT_T]
    if which == "TEST":
        return [t for t in trades if t["t"] >= SPLIT_T]
    return list(trades)


def summary(trades: list[dict]) -> dict:
    n = len(trades)
    if n == 0:
        return {"n": 0}
    R = np.array([t["R"] for t in trades])
    wins = int((R > 0).sum())
    lo, hi = wilson(wins, n)
    gross = float(R[R > 0].sum())
    loss = float(-R[R <= 0].sum())
    order = np.argsort([t["t"] for t in trades], kind="stable")
    eq = np.cumsum(R[order])
    dd = float(np.max(np.maximum.accumulate(np.maximum(eq, 0.0)) - eq))
    aw = float(R[R > 0].mean()) if wins else NAN
    al = float(-R[R <= 0].mean()) if wins < n else NAN
    years = max((max(t["t"] for t in trades) - min(t["t"] for t in trades)) / (365.25 * 86400), 1e-9)
    sd = float(R.std(ddof=1)) if n > 1 else NAN
    return {"n": n, "wins": wins, "win": wins / n, "lo": lo, "hi": hi, "tp1": sum(t["hit1"] for t in trades) / n,
            "avgR": float(R.mean()), "netR": float(R.sum()), "pf": gross / loss if loss > 0 else float("inf"),
            "maxDD": dd, "avg_win": aw, "avg_loss": al,
            # win rate at which avg_win and avg_loss break even; wins needed to pay for one average loss
            "be_win": al / (aw + al) if wins and wins < n else NAN,
            "wins_per_loss": al / aw if wins and wins < n and aw > 0 else NAN,
            "per_year": n / years, "cost": float(np.mean([t["cost_R"] for t in trades])),
            "t_stat": float(R.mean() / (sd / math.sqrt(n))) if n > 1 and sd > 0 else NAN,
            "worst": float(R.min())}


def fmt(s: dict) -> str:
    if s["n"] == 0:
        return "n=0"
    return (f"n={s['n']:5d} win={100*s['win']:5.1f}% [{100*s['lo']:4.1f},{100*s['hi']:4.1f}] avgR={s['avgR']:+.3f} "
            f"PF={s['pf']:5.2f} net={s['netR']:+8.1f}R DD={s['maxDD']:5.1f}R be={100*s['be_win']:5.1f}% "
            f"1L={s['wins_per_loss']:5.1f}W t={s['t_stat']:+.1f}")


def with_p(base: F.FParams | None = None, **kw) -> F.FParams:
    return replace(base or F.FParams(), **kw)
