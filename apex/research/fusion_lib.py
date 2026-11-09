#!/usr/bin/env python3
"""Research helpers for the Fusion engine: same universe and train/test protocol as research_lib."""
from __future__ import annotations

import numpy as np

import fusion_engine as F
import research_lib as rl

_FEATS: dict = {}


def series(tfs=None, roles=("primary",)):
    return rl.universe(roles=roles, tfs=tfs)


def run_series(s, p: F.FParams | None = None, mgmt: dict | None = None, cost: float | None = None, key=None):
    """-> (trade dicts in research_lib format, info).  `key` caches features for a parameter set."""
    p = p or F.FParams()
    ctx = F.context(s.name)
    ck = (s.name, key) if key is not None else None
    if ck is not None and ck in _FEATS:
        f = _FEATS[ck]
    else:
        f = F.features(ctx, p)
        if ck is not None:
            _FEATS[ck] = f
    trades, _st, info = F.simulate(ctx, f, p, mgmt, cost)
    t = ctx["chart"]["t"]
    out = []
    for r in trades:
        eb = r["entry_bar"]
        out.append({"series": s.name, "underlying": s.underlying, "asset": s.asset, "tf": s.tf, "group": s.group,
                    "seg": "IS" if eb < s.split else "OOS", "dir": r["dir"], "entry_bar": eb, "exit_bar": r["exit_bar"],
                    "t": int(t[eb]), "trig": r["setup"], "score": r["score"], "R": r["R"], "gross_R": r["gross_R"],
                    "cost_R": r["cost_R"], "hit1": r["hit1"], "hit2": r["hit2"], "hit3": r["hit3"],
                    "reason": r["reason"], "risk_pct": 100.0 * r["risk"] / r["entry"], "bars": r["exit_bar"] - eb})
    return out, info


def run_all(uni, p=None, mgmt=None, cost_fn=None, key=None, p_fn=None):
    trades, sig, fill = [], 0, 0
    for s in uni:
        pp = p_fn(s) if p_fn else p
        t, info = run_series(s, pp, mgmt, cost_fn(s) if cost_fn else None, key)
        trades += t
        sig += info["signals"]
        fill += info["filled"]
    return trades, {"signals": sig, "filled": fill}


def line(label, trades):
    a = rl.summary(trades)
    if a["n"] == 0:
        return f"{label:34s} n=0"
    return (f"{label:34s} n={a['n']:5d} win={100*a['win']:5.1f}% [{100*a['win_lo']:4.1f},{100*a['win_hi']:4.1f}] "
            f"tp1={100*a['tp1']:5.1f}% avgR={a['avgR']:+.3f} PF={a['pf']:5.2f} net={a['netR']:+7.1f}R maxDD={a['maxDD']:5.1f}R")


def cells(label, trades):
    out = f"{label:28s}"
    for c in ("TRAIN", "TEST_TIME", "TEST_INSTR"):
        a = rl.summary(rl.cell(trades, c))
        out += (f" | {c[:9]:9s} n={a['n']:4d} win={100*a['win']:5.1f}% avgR={a['avgR']:+.3f} PF={a['pf']:5.2f}" if a["n"]
                else f" | {c[:9]:9s} n=   0" + " " * 33)
    return out
