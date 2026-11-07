from v2_lab import *
import v2_lab
from v2_run2 import with_htf240, PB
v2_lab.get = with_htf240
v2_lab.cost_for = lambda asset: 0.01
for prof in ["HighWin", "Balanced"]:
    print(f"===== {prof} (cost 0.01%)")
    for ms in (0.0, 0.3, 0.43, 0.6):
        evaluate(dict(q_range=2.5), prof, dict(PB, min_stop_pct=ms), label=f"v2 floor min stop {ms}% of price")
# PAXG 5m by year (v2, floor .43, cost .01)
print("== PAXG 5m by year, v2 HighWin / Balanced")
for prof in ["HighWin", "Balanced"]:
    for a, b in [("2023-01-01", "2024-01-01"), ("2024-01-01", "2025-01-01"), ("2025-01-01", "2025-07-01")]:
        evaluate(dict(q_range=2.5), prof, dict(PB, min_stop_pct=0.43), sets=[("PAXGUSDT_5m", 5, a, b)], label=f"{prof} {a[:7]}..{b[:7]}")
