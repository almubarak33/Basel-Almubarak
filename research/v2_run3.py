from v2_lab import *
import v2_lab
from v2_run2 import with_htf240, PB, PB25
v2_lab.get = with_htf240
import final_config
for cost in (0.03, 0.01):
    final_config_cost = cost
    v2_lab.cost_for = lambda asset, c=cost: c
    print(f"########## cost {cost}%")
    for prof in ["HighWin", "Balanced"]:
        print(f"===== {prof}")
        evaluate({}, prof, label="v1 entries (market at close)")
        evaluate(dict(q_range=2.5), prof, PB, label="v2: pullback .33 + range<=2.5")
        evaluate(dict(q_range=2.5), prof, PB25, label="v2: pullback .25 + range<=2.5")
        evaluate(dict(q_range=2.5), prof, dict(PB, small_guard=True, cg_max_pct=5.0), label="v2 + cost guard 5%")
