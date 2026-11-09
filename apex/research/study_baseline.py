#!/usr/bin/env python3
"""Baseline: the script exactly as received (default inputs) on the whole primary universe."""
import research_lib as rl

uni = rl.universe()
trades = rl.run_universe(uni)
print("=== default inputs (profile Auto: crypto -> Trend Runner, others -> High-Probability) ===")
print("-- by timeframe (all cells pooled)")
print(rl.table(trades, lambda t: t["tf"], cells=("ALL",)))
print("-- by timeframe, non-crypto only (High-Probability profile)")
print(rl.table([t for t in trades if t["asset"] != "crypto"], lambda t: t["tf"], cells=("ALL",)))
print("-- by timeframe, crypto only (Trend Runner profile)")
print(rl.table([t for t in trades if t["asset"] == "crypto"], lambda t: t["tf"], cells=("ALL",)))
print("-- by asset class, 4h + 1D")
print(rl.table([t for t in trades if t["tf"] in ("4h", "1D")], lambda t: t["asset"], cells=("ALL",)))
print("-- by trigger, non-crypto")
print(rl.table([t for t in trades if t["asset"] != "crypto"], lambda t: t["trig"], cells=("ALL",)))
print("-- by direction, non-crypto")
print(rl.table([t for t in trades if t["asset"] != "crypto"], lambda t: "long" if t["dir"] == 1 else "short", cells=("ALL",)))
print("-- gold")
print(rl.table([t for t in trades if t["underlying"] == "GOLD"], lambda t: t["series"], cells=("ALL",)))
