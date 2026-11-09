#!/usr/bin/env python3
"""The v2 inputs of apex/APEX_Focus.pine expressed in terms of the verified v1 engine.

v2 changes no trade logic: "Direction: Auto" resolves to a v1 direction per symbol type and the new
"Sniper" profile is a fixed set of management numbers, so both map 1:1 onto the engine's existing inputs.
"""
from __future__ import annotations

from dataclasses import replace

try:
    import apex_engine as E
except Exception:                      # pragma: no cover - before reconciliation
    import engine_b as E

# k1, k2, k3 in R; w1, w2 = share closed at TP1 / TP2 (same table as the Pine script)
PROFILES = {
    "SNP": {"k1": 0.15, "k2": 1.5, "k3": 4.0, "w1": 0.50, "w2": 0.25, "trailOn": True, "trailFrom": 1, "beOn": True},
    "HP":  {"k1": 0.30, "k2": 1.5, "k3": 4.0, "w1": 0.50, "w2": 0.25, "trailOn": True, "trailFrom": 1, "beOn": True},
    "BAL": {"k1": 1.00, "k2": 2.0, "k3": 3.0, "w1": 0.40, "w2": 0.30, "trailOn": False, "trailFrom": 1, "beOn": True},
    "RUN": {"k1": 1.00, "k2": 2.0, "k3": 8.0, "w1": 0.33, "w2": 0.33, "trailOn": True, "trailFrom": 2, "beOn": False},
}


def direction(market, dir_mode: str = "Auto") -> str:
    """Pine: allowShort = dirMode == DIR_AUTO ? syminfo.type == "forex" : dirMode != "Long only"."""
    if dir_mode == "Auto":
        return "Both" if market.sym_type == "forex" else "Long only"
    return dir_mode


def params(market, dir_mode: str = "Auto", **overrides):
    """Engine Params for a v2 configuration on this market."""
    return replace(E.Params(), dirMode=direction(market, dir_mode), **overrides)


def mgmt(market, profile: str = "AUTO") -> dict:
    """Management dict for a v2 profile (AUTO: crypto -> Trend Runner, others -> High-Probability)."""
    if profile == "AUTO":
        profile = "RUN" if market.sym_type == "crypto" else "HP"
    return dict(PROFILES[profile])
