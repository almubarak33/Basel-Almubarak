import itertools, numpy as np, pandas as pd
from engine import *
from experiments import run, TREND
for k1, w1, k2, k3, mb in itertools.product([0.5], [0.5, 0.65], [2.0, 3.0], [5.0, 8.0], [0, 96, 192]):
    kw = dict(k1=k1, w1=w1, k2=k2, w2=0.25 if w1 == 0.5 else 0.2, k3=k3, be_on=True, trail_on=False, max_bars=mb)
    run(dict(trend=TREND, session=(8,17)), kw, f"w1={w1} k2={k2} k3={k3} mb={mb}")
print("-- 1R family")
for k2, k3, mb in itertools.product([2.0, 3.0], [5.0, 8.0], [0, 96]):
    run(dict(trend=TREND, session=(8,17)), dict(k1=1.0, w1=0.5, k2=k2, w2=0.25, k3=k3, be_on=True, trail_on=False, max_bars=mb), f"k1=1 k2={k2} k3={k3} mb={mb}")
print("-- setups dropped one at a time (0.5/2/5, mb0)")
kw = dict(k1=0.5, w1=0.5, k2=2.0, w2=0.25, k3=5.0, be_on=True, trail_on=False)
for drop in TREND:
    run(dict(trend=[t for t in TREND if t != drop], session=(8,17)), kw, f"without {drop}")
