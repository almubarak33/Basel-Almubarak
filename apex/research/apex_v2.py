#!/usr/bin/env python3
"""The v2 inputs of apex/APEX_Focus.pine expressed in terms of the engine.

v2 keeps the v1 signal logic.  "Direction: Auto" resolves to a v1 direction per symbol type, the new
management profiles are fixed sets of numbers, and the v2 simulation rule is mgmt["closeStop"] = 1.
"""
from __future__ import annotations

from dataclasses import replace

import engine_v2 as E

HAS_CLOSE_STOP = True

# k1, k2, k3 in R; w1, w2 = share closed at TP1 / TP2 (same table as the Pine script)
PROFILES = {
    "SHD": {"k1": 0.05, "k2": 1.5, "k3": 4.0, "w1": 0.50, "w2": 0.25, "trailOn": True, "trailFrom": 1, "beOn": True},
    "SNP": {"k1": 0.15, "k2": 1.5, "k3": 4.0, "w1": 0.50, "w2": 0.25, "trailOn": True, "trailFrom": 1, "beOn": True},
    "HP":  {"k1": 0.30, "k2": 1.5, "k3": 4.0, "w1": 0.50, "w2": 0.25, "trailOn": True, "trailFrom": 1, "beOn": True},
    "BAL": {"k1": 1.00, "k2": 2.0, "k3": 3.0, "w1": 0.40, "w2": 0.30, "trailOn": False, "trailFrom": 1, "beOn": True},
    "RUN": {"k1": 1.00, "k2": 2.0, "k3": 8.0, "w1": 0.33, "w2": 0.33, "trailOn": True, "trailFrom": 2, "beOn": False},
}
PROFILE_NAMES = {"SHD": "Shield", "SNP": "Sniper", "HP": "High-Probability", "BAL": "Balanced", "RUN": "Trend Runner"}


def direction(market, dir_mode: str = "Auto") -> str:
    """Pine: allowShort = dirMode == DIR_AUTO ? syminfo.type == "forex" : dirMode != "Long only"."""
    if dir_mode == "Auto":
        return "Both" if market.sym_type == "forex" else "Long only"
    return dir_mode


def params(market, dir_mode: str = "Auto", **overrides):
    """Engine Params for a v2 configuration on this market."""
    return replace(E.Params(), dirMode=direction(market, dir_mode), **overrides)


def mgmt(market, profile: str = "AUTO", close_stop: int = 1) -> dict:
    """Management dict for a v2 profile (AUTO: crypto -> Trend Runner, others -> High-Probability)."""
    if profile == "AUTO":
        profile = "RUN" if market.sym_type == "crypto" else "HP"
    m = dict(PROFILES[profile])
    m["closeStop"] = close_stop
    return m
