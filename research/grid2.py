import itertools, numpy as np, pandas as pd
from engine import *
from experiments import run, CACHE, TREND
import experiments as E
pd.set_option("display.width", 250)
print("== session variants (R1 mgmt)")
R1 = dict(k1=1.0, w1=1.0, k2=1.5, w2=0.0, k3=2.0, be_on=False, trail_on=False)
for sess in [(5,17),(8,17),(3,17),(7,17)]:
    run(dict(trend=TREND, session=sess), R1, f"session {sess}")
run(dict(trend=["BRK","EMA","PB","ORB"], session=(5,17)), R1, "core BRK/EMA/PB/ORB 05-17")
print("== management grid, session 05-17")
grid = []
for k1, w1, k2, k3, tr, be in itertools.product([0.5, 0.75, 1.0], [0.5], [1.5, 2.0, 3.0], [3.0, 5.0], ["off", "tp1", "tp2"], [True]):
    kw = dict(k1=k1, w1=w1, k2=k2, w2=0.25, k3=k3, be_on=be, trail_on=tr != "off", trail_from=2 if tr == "tp2" else 1)
    run(dict(trend=TREND, session=(5,17)), kw, f"k1={k1} k2={k2} k3={k3} tr={tr}")
