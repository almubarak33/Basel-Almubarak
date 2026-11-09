#!/usr/bin/env python3
"""v1 (script as received) versus v2 (Direction: Auto + profiles), with the train/test protocol.

Usage: python3 study_v2.py            # prints every table used in apex/REPORT.md
"""
import research_lib as rl
import apex_v2 as v2

E = rl.E
CELLS = ("TRAIN", "TEST_TIME", "TEST_INSTR")


def run(uni, dir_mode="Auto", profile="AUTO", mgmt=None, cost_fn=None, close_stop=None, **pkw):
    """close_stop: simulation rule; default = v1 rule (0) for Direction "Both" rows, v2 rule (1) otherwise."""
    rule = (0 if dir_mode == "Both" else 1) if close_stop is None else close_stop
    return rl.run_universe(
        uni,
        params_fn=lambda s: v2.params(s.market, dir_mode, **pkw),
        mgmt_fn=(lambda s: {**mgmt, "closeStop": rule}) if mgmt else (lambda s: v2.mgmt(s.market, profile, rule)),
        cost_fn=cost_fn)


def cells_row(label, trades, cells=CELLS):
    out = f"{label:26s}"
    for c in cells:
        a = rl.summary(rl.cell(trades, c))
        if a["n"] == 0:
            out += f" | {c[:10]:10s} n=   0" + " " * 36
        else:
            out += f" | {c[:10]:10s} n={a['n']:4d} win={100*a['win']:5.1f}% avgR={a['avgR']:+.3f} PF={a['pf']:5.2f}"
    return out


def all_row(label, trades):
    a = rl.summary(trades)
    if a["n"] == 0:
        return f"{label:30s} n=0"
    return (f"{label:30s} n={a['n']:5d} win={100*a['win']:5.1f}% [{100*a['win_lo']:4.1f},{100*a['win_hi']:4.1f}] "
            f"tp1={100*a['tp1']:5.1f}% avgR={a['avgR']:+.3f} PF={a['pf']:5.2f} net={a['netR']:+8.1f}R maxDD={a['maxDD']:5.1f}R")


def main():
    uni = rl.universe()
    print(f"universe: {len(uni)} primary series, {sum(s.n for s in uni):,} bars; "
          f"tune={sum(s.group == 'tune' for s in uni)} holdout={sum(s.group == 'holdout' for s in uni)}")

    print("\n[A] v1 defaults (Direction Both) vs v2 defaults (Direction Auto), profile Auto, all data pooled")
    t_v1 = run(uni, dir_mode="Both")
    t_v2 = run(uni, dir_mode="Auto")
    for tf in rl.TF_ORDER:
        print(all_row(f"{tf:3s} v1 Both", [t for t in t_v1 if t["tf"] == tf]))
        print(all_row(f"{tf:3s} v2 Auto", [t for t in t_v2 if t["tf"] == tf]))

    print("\n[B] same, unseen data only (TEST_TIME + TEST_INSTR)")
    for tf in rl.TF_ORDER:
        print(all_row(f"{tf:3s} v1 Both", rl.cell([t for t in t_v1 if t["tf"] == tf], "TEST")))
        print(all_row(f"{tf:3s} v2 Auto", rl.cell([t for t in t_v2 if t["tf"] == tf], "TEST")))

    print("\n[C] v2 Direction Auto: management profiles on 1D and 4H (non-crypto and crypto pooled)")
    for tf in ("1D", "4h"):
        sub = [s for s in uni if s.tf == tf]
        for prof in ("SHD", "SNP", "HP", "BAL", "RUN"):
            print(cells_row(f"{tf} {prof}", run(sub, profile=prof)))

    print("\n[D] the price of a high win rate: first target k1 (R), share closed w1; 1D, Direction Auto, BE + trail")
    sub = [s for s in uni if s.tf == "1D"]
    for k1, w1 in ((0.05, 1.0), (0.05, 0.75), (0.05, 0.5), (0.10, 0.5), (0.15, 0.5), (0.30, 0.5), (0.50, 0.5), (1.00, 0.5)):
        m = {"k1": k1, "k2": max(1.5, 2 * k1), "k3": max(4.0, 4 * k1), "w1": w1, "w2": min(0.25, 1 - w1),
             "trailOn": True, "trailFrom": 1, "beOn": True}
        print(cells_row(f"k1={k1:4.2f} close {int(100*w1):3d}%", run(sub, mgmt=m)))
    print(cells_row("Trend Runner (1R/2R/8R)", run(sub, profile="RUN")))

    print("\n[E] same frontier on 4H")
    sub = [s for s in uni if s.tf == "4h"]
    for k1, w1 in ((0.05, 1.0), (0.05, 0.5), (0.15, 0.5), (0.30, 0.5), (1.00, 0.5)):
        m = {"k1": k1, "k2": max(1.5, 2 * k1), "k3": max(4.0, 4 * k1), "w1": w1, "w2": min(0.25, 1 - w1),
             "trailOn": True, "trailFrom": 1, "beOn": True}
        print(cells_row(f"k1={k1:4.2f} close {int(100*w1):3d}%", run(sub, mgmt=m)))
    print(cells_row("Trend Runner (1R/2R/8R)", run(sub, profile="RUN")))

    print("\n[F] v2 defaults by asset class, 4H + 1D")
    for a in ("metal", "energy", "fx", "index", "stock", "crypto"):
        print(cells_row(a, [t for t in t_v2 if t["asset"] == a and t["tf"] in ("4h", "1D")]))

    print("\n[G] gold (all feeds), v1 Both vs v2 Auto per profile")
    gold = [s for s in rl.universe(roles=("primary", "replica")) if s.underlying == "GOLD"]
    for s in sorted(gold, key=lambda s: (rl.TF_ORDER.index(s.tf), s.name)):
        print(all_row(f"{s.name} v1 default", run([s], dir_mode="Both")))
        for prof in ("SHD", "SNP", "HP", "RUN"):
            print(all_row(f"{s.name} v2 {prof}", run([s], profile=prof)))

    print("\n[H] 5-minute charts: guard and cost sensitivity (v2 Direction Auto, profile Auto)")
    sub = [s for s in uni if s.tf == "5m"]
    print(all_row("5m guard ON, Auto cost", run(sub)))
    print(all_row("5m guard OFF, Auto cost", run(sub, smallGuard=False)))
    print(all_row("5m guard OFF, 1/3 cost", run(sub, smallGuard=False, cost_fn=lambda s: E.cost_pct(E.Params(), s.market) / 3)))
    print(all_row("5m guard OFF, ZERO cost", run(sub, smallGuard=False, cost_fn=lambda s: 0.0)))
    for a in ("metal", "energy", "fx", "index", "stock", "crypto"):
        print(all_row(f"   {a}: guard OFF, zero cost", [t for t in run(sub, smallGuard=False, cost_fn=lambda s: 0.0) if t["asset"] == a]))
    print("15m / 1h for reference (guard ON below 1H, Auto cost):")
    for tf in ("15m", "1h"):
        sub = [s for s in uni if s.tf == tf]
        print(all_row(f"{tf} v2 default", run(sub)))
        print(all_row(f"{tf} v2, zero cost", run(sub, smallGuard=False, cost_fn=lambda s: 0.0)))


if __name__ == "__main__":
    main()
