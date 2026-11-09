#!/usr/bin/env python3
"""test_scenarios.py - hand-derived checks of the APEX Focus ports against the Pine source.

test_parity.py proves that engine_a and engine_b AGREE; it cannot see a mistake both ports share.  Every
expectation in this file was therefore derived by hand from apex/APEX_Focus_original.pine (line numbers
L### refer to that file) - never by running an engine - and is asserted against BOTH engines.

Sections
  1. simulate() micro-scenarios   a forced signal on a handful of synthetic bars; the expected trades and the
                                  whole Stats object are worked out in the comments (Pine L321-L502)
  2. indicator sanity             ta.ema / rma / tr / atr / highest / lowest / rsi / dmi / supertrend on series
                                  short enough to verify with pencil and paper (ENGINE_SPEC section 2)
  3. profile / cost tables        Pine L194-L195 and L208-L218, the runtime.error() input checks L103-L110
  4. run() on synthetic charts    warm = bar_index >= 250, trigName precedence, the TSMOM gate, the small-frame
                                  cost guard, request.security alignment + EMA length rule, and one complete
                                  hand-traced trade path through run()

Conventions of the micro-scenarios
  * a row is (open, high, low, close); bar 0 is flat at 100 unless stated otherwise
  * longs={bar: dist} sets longSig on that bar with slDistL = dist (shorts likewise)
  * "L(100,10)" = long opened at close 100 with stop distance 10:  sl0 = 90, tp_i = 100 + k_i * 10
  * management profiles (Pine L208-L218):
        HP   k = 0.3 / 1.5 / 4   w = 0.50 / 0.25   breakeven after TP1, chandelier trail after TP1
        BAL  k = 1 / 2 / 3       w = 0.40 / 0.30   breakeven after TP1, no trail
        RUN  k = 1 / 2 / 8       w = 0.33 / 0.33   no breakeven, chandelier trail after TP2

Usage:  python3 test_scenarios.py [-v] [name-substring ...]
Exit status 0 = every check passed in both engines.
"""
from __future__ import annotations

import math
import sys
import traceback

import numpy as np

import datasets as ds
import engine_a as A
import engine_b as B

NAN = float("nan")
TOL = 1e-9
ENGINES = (("engine_a", A), ("engine_b", B))

HP = dict(k1=0.3, k2=1.5, k3=4.0, w1=0.50, w2=0.25, trailOn=True, trailFrom=1, beOn=True)
BAL = dict(k1=1.0, k2=2.0, k3=3.0, w1=0.40, w2=0.30, trailOn=False, trailFrom=1, beOn=True)
RUN = dict(k1=1.0, k2=2.0, k3=8.0, w1=0.33, w2=0.33, trailOn=True, trailFrom=2, beOn=False)
FLAT = (100.0, 100.0, 100.0, 100.0)

STAT_INT = ("n", "tp1", "tp2", "tp3", "fullSl", "win", "nL", "nS")
STAT_FLOAT = ("gross", "loss", "net", "peak", "maxDd", "costR", "netL", "netS")
TRADE_KEYS = ("dir", "entry_bar", "exit_bar", "trig", "score", "entry", "sl0", "risk", "tp1", "tp2", "tp3",
              "hit1", "hit2", "hit3", "exit_px", "reason", "gross_R", "cost_R", "R")
OPEN_KEYS = ("dir", "entry_bar", "trig", "score", "entry", "sl0", "risk", "tp1", "tp2", "tp3",
             "hit1", "hit2", "hit3")

CHECKS: list = []          # (section, name, function(E))


def check(section: str):
    def deco(fn):
        CHECKS.append((section, fn.__name__, fn))
        return fn
    return deco


# ───────────────────────────── helpers ─────────────────────────────
def custom(w1, w2, **kw):
    """Custom profile with the script's default custom targets 1R / 2R / 3R (L50-L56): no trail, breakeven."""
    m = dict(k1=1.0, k2=2.0, k3=3.0, w1=w1, w2=w2, trailOn=False, trailFrom=1, beOn=True)
    m.update(kw)
    return m


def sim(E, rows, longs=None, shorts=None, mgmt=BAL, cost=0.0, chandL=None, chandS=None, mintick=0.01, **kw):
    n = len(rows)
    o, h, l, c = (np.array([float(r[i]) for r in rows]) for i in range(4))
    long_sig = np.zeros(n, dtype=bool)
    short_sig = np.zeros(n, dtype=bool)
    dist_l = np.full(n, NAN)
    dist_s = np.full(n, NAN)
    for bar, dist in (longs or {}).items():
        long_sig[bar] = True
        dist_l[bar] = dist
    for bar, dist in (shorts or {}).items():
        short_sig[bar] = True
        dist_s[bar] = dist
    ch_l = np.full(n, NAN) if chandL is None else np.array(chandL, dtype=float)
    ch_s = np.full(n, NAN) if chandS is None else np.array(chandS, dtype=float)
    assert len(ch_l) == n and len(ch_s) == n
    return E.simulate(o, h, l, c, long_sig, short_sig, dist_l, dist_s, ch_l, ch_s, dict(mgmt), cost, mintick, **kw)


def stats(**kw):
    """A complete Stats object (Pine L248-L264); every field not named is expected to be zero."""
    s = dict(n=0, tp1=0, tp2=0, tp3=0, fullSl=0, win=0, gross=0.0, loss=0.0, net=0.0, peak=0.0, maxDd=0.0,
             costR=0.0, nL=0, netL=0.0, nS=0, netS=0.0)
    assert set(kw) <= set(s), kw
    s.update(kw)
    return s


def trade(direction, entry_bar, exit_bar, entry, risk, mgmt, exit_px, reason, gross, cost=0.0,
          hits=(False, False, False), trig="BRK", score=7, tp3="auto"):
    """A complete closed-trade record; the levels follow openTrade (L358-L363)."""
    t3 = entry + direction * mgmt["k3"] * risk if tp3 == "auto" else tp3
    return {"dir": direction, "entry_bar": entry_bar, "exit_bar": exit_bar, "trig": trig, "score": score,
            "entry": float(entry), "sl0": float(entry - direction * risk), "risk": float(risk),
            "tp1": float(entry + direction * mgmt["k1"] * risk), "tp2": float(entry + direction * mgmt["k2"] * risk),
            "tp3": t3, "hit1": hits[0], "hit2": hits[1], "hit3": hits[2],
            "exit_px": float(exit_px), "reason": reason, "gross_R": float(gross), "cost_R": float(cost),
            "R": float(gross - cost)}


def open_trade(direction, entry_bar, entry, risk, mgmt, hits=(False, False, False), trig="BRK", score=7,
               tp3="auto"):
    t = trade(direction, entry_bar, 0, entry, risk, mgmt, 0.0, "", 0.0, 0.0, hits, trig, score, tp3)
    return {k: t[k] for k in OPEN_KEYS}


def _same(got, want, key):
    if want is None or isinstance(want, (bool, str)) or (isinstance(want, int) and not isinstance(want, float)):
        assert type(got) is type(want) and got == want, f"{key}: got {got!r}, expected {want!r}"
    else:
        assert isinstance(got, float), f"{key}: got {got!r} ({type(got).__name__}), expected a float"
        assert abs(got - want) <= TOL * max(1.0, abs(want)), f"{key}: got {got!r}, expected {want!r}"


def expect(res, trades, st, open_=None):
    """Assert the complete result of simulate(): every closed trade field by field, open trade, all 16 Stats."""
    got = res["trades"]
    assert len(got) == len(trades), f"closed trades: got {len(got)}, expected {len(trades)}: {got}"
    for i, (g, w) in enumerate(zip(got, trades)):
        assert tuple(g.keys()) == TRADE_KEYS, f"trade {i} keys {list(g.keys())}"
        for k in TRADE_KEYS:
            _same(g[k], w[k], f"trade[{i}].{k}")
    g = res["open_trade"]
    if open_ is None:
        assert g is None, f"open_trade: got {g}, expected None"
    else:
        assert g is not None, "open_trade: got None"
        assert tuple(g.keys()) == OPEN_KEYS, f"open_trade keys {list(g.keys())}"
        for k in OPEN_KEYS:
            _same(g[k], open_[k], f"open_trade.{k}")
    gs = res["stats"]
    assert set(gs.keys()) == set(STAT_INT + STAT_FLOAT), f"stats keys {list(gs.keys())}"
    for k in STAT_INT:
        assert type(gs[k]) is int and gs[k] == st[k], f"stats.{k}: got {gs[k]!r}, expected {st[k]!r}"
    for k in STAT_FLOAT:
        _same(float(gs[k]), float(st[k]), f"stats.{k}")


def close_arr(got, want, tol=1e-12, what=""):
    got = np.asarray(got, dtype=float)
    want = np.asarray(want, dtype=float)
    assert got.shape == want.shape, f"{what}: shape {got.shape} != {want.shape}"
    for i, (g, w) in enumerate(zip(got.tolist(), want.tolist())):
        if w != w:
            assert g != g, f"{what}[{i}]: got {g!r}, expected na"
        else:
            assert g == g and abs(g - w) <= tol * max(1.0, abs(w)), f"{what}[{i}]: got {g!r}, expected {w!r}"


# ════════════════════════════ 1. simulate() micro-scenarios ════════════════════════════
@check("sim")
def long_full_stop(E):
    # bar0: longSig -> openTrade (L358-L363): L(100,10): sl = sl0 = 90, tp1 110, tp2 120, tp3 130.
    # bar1 (100,105,95,102): L398 open 100 <= 90 no; L407 no; L443 low 95 <= 90 no; L454 high 105 >= 110 no.
    # bar2 (101,103,89,92):  L398 101 <= 90 no; L443 low 89 <= 90 -> stop.  L445: open 101 < 90 is false -> px = 90.
    #        activeStopReason (L321): sl == sl0 and openW = 1 -> "SL".
    #        closeTrade (L327): realized = 1 * (90 - 100) * 1 / 10 = -1 ; cR = 0 ; R = -1.
    # Stats: n 1, fullSl 1, win 0, gross 0, loss 1, net -1, peak = max(0, -1) = 0, maxDd = 0 - (-1) = 1, nL 1, netL -1.
    res = sim(E, [FLAT, (100, 105, 95, 102), (101, 103, 89, 92), (92, 93, 91, 92)], longs={0: 10})
    expect(res, [trade(1, 0, 2, 100, 10, BAL, 90, "SL", -1.0)],
           stats(n=1, fullSl=1, loss=1.0, net=-1.0, maxDd=1.0, nL=1, netL=-1.0))


@check("sim")
def long_gap_open_through_stop(E):
    # bar1 opens at 85: L398 open 85 <= sl 90 -> opening stop, closeTrade(cur, open, "SL") (L400-L403).
    # realized = (85 - 100) / 10 = -1.5 : the fill is the OPEN, not the stop price.
    res = sim(E, [FLAT, (85, 88, 84, 86)], longs={0: 10})
    expect(res, [trade(1, 0, 1, 100, 10, BAL, 85, "SL", -1.5)],
           stats(n=1, fullSl=1, loss=1.5, net=-1.5, maxDd=1.5, nL=1, netL=-1.5))


@check("sim")
def long_stop_touched_exactly(E):
    # bar1 (95,96,90,93): L443 is `low <= cur.sl` (non-strict): low 90 <= 90 -> stop at 90, R = -1.
    res = sim(E, [FLAT, (95, 96, 90, 93)], longs={0: 10})
    expect(res, [trade(1, 0, 1, 100, 10, BAL, 90, "SL", -1.0)],
           stats(n=1, fullSl=1, loss=1.0, net=-1.0, maxDd=1.0, nL=1, netL=-1.0))


@check("sim")
def long_tp1_then_breakeven_next_bar(E):
    # bar1 (101,111,100,108): no opening event; L443 low 100 <= 90 no; L454 high 111 >= 110 -> hit1:
    #        w = min(0.4, 1) = 0.4 ; realized = 0.4 * 1 = 0.4 ; openW = 0.6 ; beOn -> sl = max(90, 100) = 100.
    #        L463 high 111 >= 120 no.  The new stop 100 is NOT re-checked on this bar (low is 100) - L452.
    # bar2 (104,106,99,100): L398 104 <= 100 no; L443 low 99 <= 100 -> stop, px = 100 (open 104 not below).
    #        reason: sl 100 != sl0 90 -> "BE/Trail".  realized = 0.4 + 0.6 * (100 - 100) / 10 = 0.4.
    res = sim(E, [FLAT, (101, 111, 100, 108), (104, 106, 99, 100)], longs={0: 10})
    expect(res, [trade(1, 0, 2, 100, 10, BAL, 100, "BE/Trail", 0.4, hits=(True, False, False))],
           stats(n=1, tp1=1, win=1, gross=0.4, net=0.4, peak=0.4, nL=1, netL=0.4))


@check("sim")
def long_tp1_and_stop_same_bar_stop_first(E):
    # bar1 (100,112,89,95): the range holds both tp1 (110) and the stop (90).  L443 is evaluated before L454:
    # low 89 <= 90 -> full stop at 90, hit1 stays false, R = -1.
    res = sim(E, [FLAT, (100, 112, 89, 95)], longs={0: 10})
    expect(res, [trade(1, 0, 1, 100, 10, BAL, 90, "SL", -1.0)],
           stats(n=1, fullSl=1, loss=1.0, net=-1.0, maxDd=1.0, nL=1, netL=-1.0))


@check("sim")
def long_tp1_tp2_in_one_bar_then_stop_at_tp1(E):
    # bar1 (101,121,100,119): L454 hit1: realized 0.4, openW 0.6, sl 100.
    #        L463 openW > 1e-9, hit1, high 121 >= 120 -> hit2: w = min(0.3, 0.6) = 0.3 ; realized = 0.4 + 0.3*2 = 1.0 ;
    #        openW = 0.3 ; sl = max(100, tp1 110) = 110.  L474 high 121 >= 130 no.
    # bar2 (118,119,109,112): L398 118 <= 110 no; L443 low 109 <= 110 -> px 110, "BE/Trail".
    #        realized = 1.0 + 0.3 * (110 - 100) / 10 = 1.3.
    res = sim(E, [FLAT, (101, 121, 100, 119), (118, 119, 109, 112)], longs={0: 10})
    expect(res, [trade(1, 0, 2, 100, 10, BAL, 110, "BE/Trail", 1.3, hits=(True, True, False))],
           stats(n=1, tp1=1, tp2=1, win=1, gross=1.3, net=1.3, peak=1.3, nL=1, netL=1.3))


@check("sim")
def long_gap_above_tp1_tp2_stop_active_same_bar(E):
    # bar1 (125,126,109,112) opens above tp1 110 and tp2 120:
    #   L398 125 <= 90 no.  L407 open 125 >= 110 -> hit1 at the LIMIT price: realized 0.4, openW 0.6, sl 100.
    #   L416 open 125 >= 120 -> hit2: realized 1.0, openW 0.3, sl = max(100, 110) = 110.  L427 125 >= 130 no.
    #   L443: the stop moved by OPENING fills is live on this bar: low 109 <= 110 -> stop.
    #   L445: open 125 < 110 false -> px = 110 ; "BE/Trail" ; realized = 1.0 + 0.3 * 1 = 1.3.  Exit on bar 1.
    res = sim(E, [FLAT, (125, 126, 109, 112)], longs={0: 10})
    expect(res, [trade(1, 0, 1, 100, 10, BAL, 110, "BE/Trail", 1.3, hits=(True, True, False))],
           stats(n=1, tp1=1, tp2=1, win=1, gross=1.3, net=1.3, peak=1.3, nL=1, netL=1.3))


@check("sim")
def long_gap_above_tp1_tp2_then_tp3_by_range(E):
    # bar1 (125,126,111,124): opening fills as above (realized 1.0, openW 0.3, sl 110); low 111 > 110 -> alive.
    # bar2 (124,130,123,129): L398 no; L427 open 124 >= 130 no; L443 123 <= 110 no;
    #        L474 hit2, tp3 130, high 130 >= 130 (non-strict) -> hit3: realized = 1.0 + 0.3 * 3 = 1.9 ; openW = 0 ;
    #        closeTrade(cur, tp3, "TP3") adds 0 * ... = 0.
    res = sim(E, [FLAT, (125, 126, 111, 124), (124, 130, 123, 129)], longs={0: 10})
    expect(res, [trade(1, 0, 2, 100, 10, BAL, 130, "TP3", 1.9, hits=(True, True, True))],
           stats(n=1, tp1=1, tp2=1, tp3=1, win=1, gross=1.9, net=1.9, peak=1.9, nL=1, netL=1.9))


@check("sim")
def long_tp3_in_one_range_bar(E):
    # bar1 (101,131,100,128): L454 hit1 (0.4) ; L463 hit2 (+0.6 = 1.0, openW 0.3) ; L474 high 131 >= 130 -> hit3
    # (+0.3*3 = 0.9) -> realized 1.9, exit price tp3 = 130.
    res = sim(E, [FLAT, (101, 131, 100, 128)], longs={0: 10})
    expect(res, [trade(1, 0, 1, 100, 10, BAL, 130, "TP3", 1.9, hits=(True, True, True))],
           stats(n=1, tp1=1, tp2=1, tp3=1, win=1, gross=1.9, net=1.9, peak=1.9, nL=1, netL=1.9))


@check("sim")
def long_gap_above_tp3_fills_at_limit_prices(E):
    # bar1 opens at 135 above all three targets: L407, L416, L427 all fire at the opening.  Each part is booked at
    # its own target (k1, k2, k3 in R), not at the better open: realized = 0.4 + 0.6 + 0.9 = 1.9, exit_px = 130.
    res = sim(E, [FLAT, (135, 136, 134, 135)], longs={0: 10})
    expect(res, [trade(1, 0, 1, 100, 10, BAL, 130, "TP3", 1.9, hits=(True, True, True))],
           stats(n=1, tp1=1, tp2=1, tp3=1, win=1, gross=1.9, net=1.9, peak=1.9, nL=1, netL=1.9))
    # the opening TP3 (L427) is a known event that precedes the rest of the bar: a later dip to 105, below the
    # stop that TP2 moved to 110, changes nothing.
    res = sim(E, [FLAT, (135, 136, 105, 108)], longs={0: 10})
    expect(res, [trade(1, 0, 1, 100, 10, BAL, 130, "TP3", 1.9, hits=(True, True, True))],
           stats(n=1, tp1=1, tp2=1, tp3=1, win=1, gross=1.9, net=1.9, peak=1.9, nL=1, netL=1.9))


@check("sim")
def long_open_equals_tp1_breakeven_active_same_bar(E):
    # bar1 (110,112,99,105): L407 is `open >= cur.tp1` (non-strict): open 110 >= 110 -> hit1 at the opening,
    # sl = max(90, 100) = 100 and that stop is live for L443: low 99 <= 100 -> px 100, "BE/Trail",
    # realized = 0.4 + 0.6 * 0 = 0.4.  (Had TP1 been a range fill the trade would have survived - next scenario.)
    res = sim(E, [FLAT, (110, 112, 99, 105)], longs={0: 10})
    expect(res, [trade(1, 0, 1, 100, 10, BAL, 100, "BE/Trail", 0.4, hits=(True, False, False))],
           stats(n=1, tp1=1, win=1, gross=0.4, net=0.4, peak=0.4, nL=1, netL=0.4))


@check("sim")
def long_range_tp1_breakeven_not_rechecked_same_bar(E):
    # bar1 (109,112,99,105): open 109 < tp1 -> no opening fill.  L443 against the OLD stop: low 99 <= 90 no.
    # L454 high 112 >= 110 -> hit1, sl = 100.  Low 99 is below the new stop but L452-L453: not re-checked.
    # bar2 (105,106,104,105): nothing.  The trade is still open with hit1.
    res = sim(E, [FLAT, (109, 112, 99, 105), (105, 106, 104, 105)], longs={0: 10})
    expect(res, [], stats(), open_trade(1, 0, 100, 10, BAL, hits=(True, False, False)))


@check("sim")
def long_stop_moved_by_tp2_then_gap_below_it(E):
    # bar1 (101,121,100,119): TP1 + TP2 by range -> realized 1.0, openW 0.3, sl 110.
    # bar2 opens at 105: L398 105 <= 110 -> opening stop at the OPEN, reason "BE/Trail" (sl != sl0).
    #        realized = 1.0 + 0.3 * (105 - 100) / 10 = 1.15.
    res = sim(E, [FLAT, (101, 121, 100, 119), (105, 106, 104, 105)], longs={0: 10})
    expect(res, [trade(1, 0, 2, 100, 10, BAL, 105, "BE/Trail", 1.15, hits=(True, True, False))],
           stats(n=1, tp1=1, tp2=1, win=1, gross=1.15, net=1.15, peak=1.15, nL=1, netL=1.15))


@check("sim")
def hp_trail_tightens_with_previous_bar_chandelier(E):
    # HP L(100,10): tp1 103, tp2 115, tp3 140.  chandL = [80, 101.5, 104, 99].
    # bar1 (101,104,100,103.5): L393 hit1 false -> no trail.  L454 high 104 >= 103 -> hit1: realized = 0.5*0.3 = 0.15,
    #        openW 0.5, sl = max(90, 100) = 100.
    # bar2 (103,106,102,105): L393-L396 tv = chandL[1] = 101.5 (PREVIOUS bar) -> sl = max(100, 101.5) = 101.5.
    #        L398 103 <= 101.5 no; L443 102 <= 101.5 no.   (With the current bar's 104 the open 103 would stop out.)
    # bar3 (105,105.5,103.5,104): tv = chandL[2] = 104 -> sl = 104.  L398 105 <= 104 no; L443 103.5 <= 104 -> px 104.
    #        realized = 0.15 + 0.5 * (104 - 100) / 10 = 0.35 ; "BE/Trail".   (chandL[3] = 99 is never used.)
    res = sim(E, [FLAT, (101, 104, 100, 103.5), (103, 106, 102, 105), (105, 105.5, 103.5, 104)],
              longs={0: 10}, mgmt=HP, chandL=[80, 101.5, 104, 99])
    expect(res, [trade(1, 0, 3, 100, 10, HP, 104, "BE/Trail", 0.35, hits=(True, False, False))],
           stats(n=1, tp1=1, win=1, gross=0.35, net=0.35, peak=0.35, nL=1, netL=0.35))


@check("sim")
def hp_trail_never_loosens(E):
    # chandL = [80, 102, 95, 95].  bar1: TP1 by range (sl 100).  bar2 (104,106,103,105): tv 102 -> sl 102, no stop.
    # bar3 (104,105,101,102): tv = chandL[2] = 95 -> sl = max(102, 95) = 102 (L396 math.max).  L443 101 <= 102 ->
    # px 102.  realized = 0.15 + 0.5 * 0.2 = 0.25.
    res = sim(E, [FLAT, (101, 104, 100, 103.5), (104, 106, 103, 105), (104, 105, 101, 102)],
              longs={0: 10}, mgmt=HP, chandL=[80, 102, 95, 95])
    expect(res, [trade(1, 0, 3, 100, 10, HP, 102, "BE/Trail", 0.25, hits=(True, False, False))],
           stats(n=1, tp1=1, win=1, gross=0.25, net=0.25, peak=0.25, nL=1, netL=0.25))


@check("sim")
def hp_na_chandelier_is_skipped(E):
    # chandL all na: L395 `if not na(tv)` skips the update, the breakeven stop 100 stays.
    # bar2 (103,104,99.5,100): L443 99.5 <= 100 -> px 100 ; realized = 0.15 + 0.5 * 0 = 0.15.
    res = sim(E, [FLAT, (101, 104, 100, 103.5), (103, 104, 99.5, 100)], longs={0: 10}, mgmt=HP)
    expect(res, [trade(1, 0, 2, 100, 10, HP, 100, "BE/Trail", 0.15, hits=(True, False, False))],
           stats(n=1, tp1=1, win=1, gross=0.15, net=0.15, peak=0.15, nL=1, netL=0.15))


@check("sim")
def hp_gap_tp1_then_chandelier_above_open_exits_at_open(E):
    # chandL[0] = 106.  bar1 (104,107,103.5,106): L393 hit1 false -> skip.  L398 no.  L407 open 104 >= 103 -> hit1
    # at the opening: realized 0.15, openW 0.5, sl 100.  L438-L441 (second trail update): tv = chandL[0] = 106 ->
    # sl = 106.  L443 low 103.5 <= 106 -> stop ; L445 open 104 < 106 -> px = OPEN 104.
    # realized = 0.15 + 0.5 * (104 - 100) / 10 = 0.35 ; "BE/Trail".
    res = sim(E, [FLAT, (104, 107, 103.5, 106)], longs={0: 10}, mgmt=HP, chandL=[106, 0])
    expect(res, [trade(1, 0, 1, 100, 10, HP, 104, "BE/Trail", 0.35, hits=(True, False, False))],
           stats(n=1, tp1=1, win=1, gross=0.35, net=0.35, peak=0.35, nL=1, netL=0.35))


@check("sim")
def hp_trailing_stop_gap_exits_at_open(E):
    # chandL[1] = 103.  bar1: TP1 by range (sl 100).  bar2 opens 102.5: L393-L396 run BEFORE the opening check:
    # sl = max(100, 103) = 103 ; L398 102.5 <= 103 -> closeTrade at the open.
    # realized = 0.15 + 0.5 * (102.5 - 100) / 10 = 0.275.
    res = sim(E, [FLAT, (101, 104, 100, 103.5), (102.5, 103, 102, 102.8)], longs={0: 10}, mgmt=HP,
              chandL=[80, 103, 103])
    expect(res, [trade(1, 0, 2, 100, 10, HP, 102.5, "BE/Trail", 0.275, hits=(True, False, False))],
           stats(n=1, tp1=1, win=1, gross=0.275, net=0.275, peak=0.275, nL=1, netL=0.275))


@check("sim")
def hp_full_path_to_tp3(E):
    # bar1 (101,141,100.5,140): 0.5*0.3 + 0.25*1.5 + 0.25*4 = 0.15 + 0.375 + 1.0 = 1.525, exit at tp3 140.
    res = sim(E, [FLAT, (101, 141, 100.5, 140)], longs={0: 10}, mgmt=HP)
    expect(res, [trade(1, 0, 1, 100, 10, HP, 140, "TP3", 1.525, hits=(True, True, True))],
           stats(n=1, tp1=1, tp2=1, tp3=1, win=1, gross=1.525, net=1.525, peak=1.525, nL=1, netL=1.525))


@check("sim")
def run_trail_only_after_tp2(E):
    # RUN L(100,10): tp1 110, tp2 120, tp3 180; trailFrom = 2, no breakeven.  chandL = [95, 105, 106, 112, 100].
    # bar1 (101,111,100,110): hit1: w = 0.33, realized 0.33, openW 0.67 ; beOn false -> sl stays 90.
    # bar2 (110,112,104,108): L393 uses cur.hit2 (false) -> no trail ; sl 90 ; low 104 no stop.
    #        (A trail from TP1 would give sl = chandL[1] = 105 and stop this bar out.)
    # bar3 (109,121,108,120): L463 high 121 >= 120 -> hit2: w = min(0.33, 0.67) = 0.33, realized = 0.33 + 0.66 = 0.99,
    #        openW = 0.34, sl = max(90, tp1 110) = 110.
    # bar4 (119,120,111.5,113): hit2 -> tv = chandL[3] = 112 -> sl = 112.  L443 111.5 <= 112 -> px 112, "BE/Trail".
    #        realized = 0.99 + 0.34 * (112 - 100) / 10 = 0.99 + 0.408 = 1.398.
    res = sim(E, [FLAT, (101, 111, 100, 110), (110, 112, 104, 108), (109, 121, 108, 120), (119, 120, 111.5, 113)],
              longs={0: 10}, mgmt=RUN, chandL=[95, 105, 106, 112, 100])
    expect(res, [trade(1, 0, 4, 100, 10, RUN, 112, "BE/Trail", 1.398, hits=(True, True, False))],
           stats(n=1, tp1=1, tp2=1, win=1, gross=1.398, net=1.398, peak=1.398, nL=1, netL=1.398))


@check("sim")
def run_remaining_sl_after_tp1(E):
    # bar1: TP1 (realized 0.33, openW 0.67, sl still 90 = sl0).  bar2 (108,109,89,90): L443 89 <= 90 -> px 90.
    # activeStopReason: stillInitial, openW 0.67 < 1 - 1e-9 -> "Remaining SL" (NOT counted in fullSl, L335).
    # realized = 0.33 + 0.67 * (-1) = -0.34.
    res = sim(E, [FLAT, (101, 111, 100, 110), (108, 109, 89, 90)], longs={0: 10}, mgmt=RUN)
    expect(res, [trade(1, 0, 2, 100, 10, RUN, 90, "Remaining SL", -0.34, hits=(True, False, False))],
           stats(n=1, tp1=1, loss=0.34, net=-0.34, maxDd=0.34, nL=1, netL=-0.34))


@check("sim")
def run_remaining_sl_gap_open(E):
    # bar2 opens at 85 <= 90: opening stop at the open, "Remaining SL".  realized = 0.33 + 0.67 * (-1.5) = -0.675.
    res = sim(E, [FLAT, (101, 111, 100, 110), (85, 86, 84, 85)], longs={0: 10}, mgmt=RUN)
    expect(res, [trade(1, 0, 2, 100, 10, RUN, 85, "Remaining SL", -0.675, hits=(True, False, False))],
           stats(n=1, tp1=1, loss=0.675, net=-0.675, maxDd=0.675, nL=1, netL=-0.675))


@check("sim")
def run_gap_tp1_has_no_breakeven(E):
    # bar1 (111,112,99,105): L407 open 111 >= tp1 110 -> hit1 at the opening (0.33, openW 0.67).  beOn is false
    # for Trend Runner (L218) and the trail waits for TP2 (L217) -> sl stays 90 ; low 99 > 90 -> still open.
    res = sim(E, [FLAT, (111, 112, 99, 105)], longs={0: 10}, mgmt=RUN, chandL=[105, 105])
    expect(res, [], stats(), open_trade(1, 0, 100, 10, RUN, hits=(True, False, False)))


@check("sim")
def run_tp3_runner(E):
    # bar1 (101,121,100,120): TP1 + TP2 -> realized 0.99, openW 0.34, sl 110.
    # bar2 (120,181,119,180): na chandelier -> sl 110 ; L474 high 181 >= 180 -> hit3: 0.99 + 0.34 * 8 = 3.71.
    res = sim(E, [FLAT, (101, 121, 100, 120), (120, 181, 119, 180)], longs={0: 10}, mgmt=RUN)
    expect(res, [trade(1, 0, 2, 100, 10, RUN, 180, "TP3", 3.71, hits=(True, True, True))],
           stats(n=1, tp1=1, tp2=1, tp3=1, win=1, gross=3.71, net=3.71, peak=3.71, nL=1, netL=3.71))


@check("sim")
def reversal_on_opposite_signal(E):
    # bar1 (101,105,99,104) carries shortSig (dist 8).  Block 1 first: nothing happens to the long.
    # Block 2 (L497): shortSig and cur.dir == 1 -> closeTrade(cur, close 104, "Reverse"): realized = 0.4.
    #        openTrade(-1): S(104,8): sl 112, tp1 96, tp2 88, tp3 80.
    # bar2 (104,113,103,110): short: L398 open 104 >= 112 no; L443 high 113 >= 112 -> px 112, "SL":
    #        realized = 1 * (112 - 104) * (-1) / 8 = -1.
    # Stats: net after trade 1 = 0.4 (peak 0.4), after trade 2 = -0.6 -> maxDd = 0.4 - (-0.6) = 1.0.
    res = sim(E, [FLAT, (101, 105, 99, 104), (104, 113, 103, 110)], longs={0: 10}, shorts={1: 8})
    expect(res, [trade(1, 0, 1, 100, 10, BAL, 104, "Reverse", 0.4),
                 trade(-1, 1, 2, 104, 8, BAL, 112, "SL", -1.0)],
           stats(n=2, fullSl=1, win=1, gross=0.4, loss=1.0, net=-0.6, peak=0.4, maxDd=1.0,
                 nL=1, netL=0.4, nS=1, netS=-1.0))


@check("sim")
def reversal_short_to_long(E):
    # S(100,10).  bar1 (99,101,95,96) + longSig (dist 8): block 1: nothing.  L491: longSig and cur.dir == -1 ->
    # closeTrade(cur, CLOSE 96, "Reverse"): realized = (96 - 100) * (-1) / 10 = 0.4 ; L(96,8): sl 88, tp1 104.
    # bar2 (96,97,87,90): low 87 <= 88 -> px 88, "SL", R = -1.
    res = sim(E, [FLAT, (99, 101, 95, 96), (96, 97, 87, 90)], shorts={0: 10}, longs={1: 8})
    expect(res, [trade(-1, 0, 1, 100, 10, BAL, 96, "Reverse", 0.4),
                 trade(1, 1, 2, 96, 8, BAL, 88, "SL", -1.0)],
           stats(n=2, fullSl=1, win=1, gross=0.4, loss=1.0, net=-0.6, peak=0.4, maxDd=1.0,
                 nL=1, netL=-1.0, nS=1, netS=0.4))


@check("sim")
def reversal_trade_not_managed_on_its_entry_bar(E):
    # bar1 (100,109,91,95) + shortSig (dist 4): the long survives block 1 (91 > 90, 109 < 110), is reversed at 95:
    # realized = (95 - 100) / 10 = -0.5.  New S(95,4): sl 99, tp1 91.  Bar 1's own high 109 / low 91 are NOT applied
    # to the new trade (L390 bar_index > cur.entryBar).  bar2 (95,96,94,95): nothing -> short still open.
    res = sim(E, [FLAT, (100, 109, 91, 95), (95, 96, 94, 95)], longs={0: 10}, shorts={1: 4})
    expect(res, [trade(1, 0, 1, 100, 10, BAL, 95, "Reverse", -0.5)],
           stats(n=1, loss=0.5, net=-0.5, maxDd=0.5, nL=1, netL=-0.5),
           open_trade(-1, 1, 95, 4, BAL))


@check("sim")
def same_direction_signal_ignored(E):
    # bar1 has longSig again (dist 2) while the long is open: L491 needs na(cur) or cur.dir == -1 -> ignored,
    # L497 shortSig false.  bar2 (104,105,89,90): the ORIGINAL trade (entry 100, sl 90) is stopped: R = -1.
    res = sim(E, [FLAT, (101, 106, 100, 105), (104, 105, 89, 90)], longs={0: 10, 1: 2})
    expect(res, [trade(1, 0, 2, 100, 10, BAL, 90, "SL", -1.0)],
           stats(n=1, fullSl=1, loss=1.0, net=-1.0, maxDd=1.0, nL=1, netL=-1.0))
    # short mirror (L497 needs na(cur) or cur.dir == 1): the second shortSig on bar1 is ignored, the original
    # S(100,10) is stopped at 110 on bar2.
    res = sim(E, [FLAT, (99, 100, 94, 95), (96, 111, 95, 110)], shorts={0: 10, 1: 2})
    expect(res, [trade(-1, 0, 2, 100, 10, BAL, 110, "SL", -1.0)],
           stats(n=1, fullSl=1, loss=1.0, net=-1.0, maxDd=1.0, nS=1, netS=-1.0))


@check("sim")
def stop_out_and_new_same_direction_signal_same_bar(E):
    # bar1 (99,100,89,93) + longSig (dist 5): block 1 stops the long at 90 (R = -1, cur := na); block 2 then sees
    # longSig and na(cur) -> a NEW long at the close 93: sl 88, tp 98 / 103 / 108.  bar2: quiet.
    res = sim(E, [FLAT, (99, 100, 89, 93), (93, 94, 92, 93)], longs={0: 10, 1: 5})
    expect(res, [trade(1, 0, 1, 100, 10, BAL, 90, "SL", -1.0)],
           stats(n=1, fullSl=1, loss=1.0, net=-1.0, maxDd=1.0, nL=1, netL=-1.0),
           open_trade(1, 1, 93, 5, BAL))


@check("sim")
def stop_out_and_opposite_signal_same_bar_is_not_a_reverse(E):
    # bar1 (99,100,89,93) + shortSig (dist 4): the long is stopped at 90 with reason "SL" (not "Reverse"),
    # then S(93,4) opens: sl 97, tp1 89.  bar2 (93,97.5,92,97): L443 high 97.5 >= 97 -> px 97, "SL", R = -1.
    res = sim(E, [FLAT, (99, 100, 89, 93), (93, 97.5, 92, 97)], longs={0: 10}, shorts={1: 4})
    expect(res, [trade(1, 0, 1, 100, 10, BAL, 90, "SL", -1.0),
                 trade(-1, 1, 2, 93, 4, BAL, 97, "SL", -1.0)],
           stats(n=2, fullSl=2, loss=2.0, net=-2.0, maxDd=2.0, nL=1, netL=-1.0, nS=1, netS=-1.0))


@check("sim")
def both_signals_on_one_bar(E):
    # bar0 long+short: L491 is tested first, na(cur) -> LONG L(100,10).
    # bar1 (100,102,98,101) long+short: L491 false (cur is long) -> else-if L497 true -> Reverse at 101:
    #        realized = 0.1 ; S(101,5): sl 106, tp1 96.
    # bar2 (101,102,100,101) long+short: L491 longSig and cur.dir == -1 -> Reverse at 101: realized = 0 -> R = 0
    #        (neither win nor loss) ; L(101,5) opens.
    res = sim(E, [FLAT, (100, 102, 98, 101), (101, 102, 100, 101)],
              longs={0: 10, 1: 5, 2: 5}, shorts={0: 10, 1: 5, 2: 5})
    expect(res, [trade(1, 0, 1, 100, 10, BAL, 101, "Reverse", 0.1),
                 trade(-1, 1, 2, 101, 5, BAL, 101, "Reverse", 0.0)],
           stats(n=2, win=1, gross=0.1, net=0.1, peak=0.1, nL=1, netL=0.1, nS=1, netS=0.0),
           open_trade(1, 2, 101, 5, BAL))


@check("sim")
def entry_bar_is_not_managed(E):
    # The signal bar itself spans 50 .. 150: L390 requires bar_index > cur.entryBar, so neither the stop 90 nor
    # any target is applied on bar 0.  bar1 is quiet -> the trade is open and untouched.
    res = sim(E, [(100, 150, 50, 100), (100, 101, 99, 100)], longs={0: 10})
    expect(res, [], stats(), open_trade(1, 0, 100, 10, BAL))


@check("sim")
def signal_on_last_bar_only_opens(E):
    res = sim(E, [FLAT, (100, 104, 99, 103)], shorts={1: 6})
    expect(res, [], stats(), open_trade(-1, 1, 103, 6, BAL))


@check("sim")
def trigger_name_and_score_are_recorded(E):
    # openTrade(1, trigNameL, scoreL) / openTrade(-1, trigNameS, scoreS) (L495 / L501): values of the SIGNAL bar.
    res = sim(E, [FLAT, (101, 105, 99, 104), (104, 113, 103, 110)], longs={0: 10}, shorts={1: 8},
              trigL=["FLIP", "BRK", "BRK"], trigS=["BRK", "PB", "BRK"], scoreL=[6, 7, 7], scoreS=[7, 5, 7])
    expect(res, [trade(1, 0, 1, 100, 10, BAL, 104, "Reverse", 0.4, trig="FLIP", score=6),
                 trade(-1, 1, 2, 104, 8, BAL, 112, "SL", -1.0, trig="PB", score=5)],
           stats(n=2, fullSl=1, win=1, gross=0.4, loss=1.0, net=-0.6, peak=0.4, maxDd=1.0,
                 nL=1, netL=0.4, nS=1, netS=-1.0))


@check("sim")
def targets_touched_exactly(E):
    # L454 / L463 are non-strict.  long: bar1 (101,110,100.5,109): high == tp1 110 -> hit1 (0.4, sl 100).
    res = sim(E, [FLAT, (101, 110, 100.5, 109)], longs={0: 10})
    expect(res, [], stats(), open_trade(1, 0, 100, 10, BAL, hits=(True, False, False)))
    # bar1 (101,111,100.5,109): hit1 ; bar2 (109,120,108,119): high == tp2 120 -> hit2.  Still open.
    res = sim(E, [FLAT, (101, 111, 100.5, 109), (109, 120, 108, 119)], longs={0: 10})
    expect(res, [], stats(), open_trade(1, 0, 100, 10, BAL, hits=(True, True, False)))
    # short: bar1 (99,99.5,90,91): low == tp1 90 -> hit1.
    res = sim(E, [FLAT, (99, 99.5, 90, 91)], shorts={0: 10})
    expect(res, [], stats(), open_trade(-1, 0, 100, 10, BAL, hits=(True, False, False)))
    # bar1 (99,99.5,89,91): hit1 ; bar2 (91,92,80,81): low == tp2 80 -> hit2.
    res = sim(E, [FLAT, (99, 99.5, 89, 91), (91, 92, 80, 81)], shorts={0: 10})
    expect(res, [], stats(), open_trade(-1, 0, 100, 10, BAL, hits=(True, True, False)))


@check("sim")
def hp_trail_update_precedes_opening_targets(E):
    # chandL[1] = 120.  bar1 (101,104,100,103.5): TP1 by range (realized 0.15, openW 0.5, sl 100).
    # bar2 opens at 116, above tp2 115, but L393-L396 run first: sl = max(100, 120) = 120 ; L398 116 <= 120 ->
    # the whole remainder leaves at the open as "BE/Trail" ; TP2 is never booked (hit2 false).
    # realized = 0.15 + 0.5 * (116 - 100) / 10 = 0.95.
    res = sim(E, [FLAT, (101, 104, 100, 103.5), (116, 117, 115.5, 116.5)], longs={0: 10}, mgmt=HP,
              chandL=[80, 120, 120])
    expect(res, [trade(1, 0, 2, 100, 10, HP, 116, "BE/Trail", 0.95, hits=(True, False, False))],
           stats(n=1, tp1=1, win=1, gross=0.95, net=0.95, peak=0.95, nL=1, netL=0.95))


@check("sim")
def custom_trail_without_breakeven_keeps_initial_stop_reason(E):
    # Custom with cTrail on, cBe off (trailFrom is 1 for Custom): chandL[1] = 85 is BELOW the initial stop 90.
    # bar1 (101,111,100.5,108): TP1 (0.4, openW 0.6) ; no breakeven -> sl stays 90.
    # bar2 (108,109,89,90): L396 sl = max(90, 85) = 90 -> still equal to sl0 ; low 89 <= 90 -> px 90.
    #        activeStopReason: stillInitial and openW 0.6 -> "Remaining SL".  realized = 0.4 + 0.6 * (-1) = -0.2.
    res = sim(E, [FLAT, (101, 111, 100.5, 108), (108, 109, 89, 90)], longs={0: 10},
              mgmt=custom(0.4, 0.3, trailOn=True, beOn=False), chandL=[80, 85, 85])
    expect(res, [trade(1, 0, 2, 100, 10, BAL, 90, "Remaining SL", -0.2, hits=(True, False, False))],
           stats(n=1, tp1=1, loss=0.2, net=-0.2, maxDd=0.2, nL=1, netL=-0.2))


# ---- short-side mirrors
@check("sim")
def short_full_stop(E):
    # S(100,10): sl 110, tp1 90, tp2 80, tp3 70.  bar2 (99,111,97,108): L443 high 111 >= 110 -> px 110.
    # realized = 1 * (110 - 100) * (-1) / 10 = -1.  Stats book the short side (L344-L346).
    res = sim(E, [FLAT, (100, 105, 95, 98), (99, 111, 97, 108)], shorts={0: 10})
    expect(res, [trade(-1, 0, 2, 100, 10, BAL, 110, "SL", -1.0)],
           stats(n=1, fullSl=1, loss=1.0, net=-1.0, maxDd=1.0, nS=1, netS=-1.0))


@check("sim")
def short_gap_open_through_stop(E):
    # bar1 opens 115 >= 110 (L398 short branch) -> exit at the open: (115 - 100) * (-1) / 10 = -1.5.
    res = sim(E, [FLAT, (115, 116, 114, 115)], shorts={0: 10})
    expect(res, [trade(-1, 0, 1, 100, 10, BAL, 115, "SL", -1.5)],
           stats(n=1, fullSl=1, loss=1.5, net=-1.5, maxDd=1.5, nS=1, netS=-1.5))


@check("sim")
def short_tp1_then_breakeven_next_bar(E):
    # bar1 (99,100,89,92): L443 high 100 >= 110 no ; L454 low 89 <= 90 -> hit1: realized 0.4, openW 0.6,
    #        sl = min(110, 100) = 100 (high 100 on this bar is not re-checked).
    # bar2 (96,101,95,100): L398 96 >= 100 no ; L443 high 101 >= 100 -> px 100, "BE/Trail", realized 0.4.
    res = sim(E, [FLAT, (99, 100, 89, 92), (96, 101, 95, 100)], shorts={0: 10})
    expect(res, [trade(-1, 0, 2, 100, 10, BAL, 100, "BE/Trail", 0.4, hits=(True, False, False))],
           stats(n=1, tp1=1, win=1, gross=0.4, net=0.4, peak=0.4, nS=1, netS=0.4))


@check("sim")
def short_tp1_and_stop_same_bar_stop_first(E):
    # bar1 (100,111,88,95): high 111 >= 110 is checked first -> full stop at 110, hit1 false.
    res = sim(E, [FLAT, (100, 111, 88, 95)], shorts={0: 10})
    expect(res, [trade(-1, 0, 1, 100, 10, BAL, 110, "SL", -1.0)],
           stats(n=1, fullSl=1, loss=1.0, net=-1.0, maxDd=1.0, nS=1, netS=-1.0))


@check("sim")
def short_tp1_tp2_tp3_in_one_bar(E):
    # bar1 (99,100,69,72): low 69 <= 90, <= 80, <= 70 -> 0.4 + 0.6 + 0.9 = 1.9, exit at tp3 70.
    res = sim(E, [FLAT, (99, 100, 69, 72)], shorts={0: 10})
    expect(res, [trade(-1, 0, 1, 100, 10, BAL, 70, "TP3", 1.9, hits=(True, True, True))],
           stats(n=1, tp1=1, tp2=1, tp3=1, win=1, gross=1.9, net=1.9, peak=1.9, nS=1, netS=1.9))


@check("sim")
def short_gap_below_tp1_tp2_stop_active_same_bar(E):
    # bar1 (75,91,74,88): L407 open 75 <= 90 -> hit1, sl = min(110, 100) = 100 ; L416 open 75 <= 80 -> hit2,
    # sl = min(100, tp1 90) = 90 ; L427 75 <= 70 no.  L443 high 91 >= 90 -> px 90 (open 75 > 90 false).
    # realized = 1.0 + 0.3 * (90 - 100) * (-1) / 10 = 1.3.
    res = sim(E, [FLAT, (75, 91, 74, 88)], shorts={0: 10})
    expect(res, [trade(-1, 0, 1, 100, 10, BAL, 90, "BE/Trail", 1.3, hits=(True, True, False))],
           stats(n=1, tp1=1, tp2=1, win=1, gross=1.3, net=1.3, peak=1.3, nS=1, netS=1.3))


@check("sim")
def short_hp_trail_tightens(E):
    # HP S(100,10): sl 110, tp1 97, tp2 85, tp3 60.  chandS = [120, 98.5, 96, 101].
    # bar1 (99,100,96,96.5): L454 low 96 <= 97 -> hit1: realized 0.15, openW 0.5, sl = min(110, 100) = 100.
    # bar2 (97,98,94,95): tv = chandS[1] = 98.5 -> sl = min(100, 98.5) = 98.5 ; 97 >= 98.5 no ; high 98 no.
    # bar3 (95,96.5,94.5,96): tv = chandS[2] = 96 -> sl = 96 ; open 95 >= 96 no ; high 96.5 >= 96 -> px 96.
    #        realized = 0.15 + 0.5 * (96 - 100) * (-1) / 10 = 0.35.
    res = sim(E, [FLAT, (99, 100, 96, 96.5), (97, 98, 94, 95), (95, 96.5, 94.5, 96)],
              shorts={0: 10}, mgmt=HP, chandS=[120, 98.5, 96, 101])
    expect(res, [trade(-1, 0, 3, 100, 10, HP, 96, "BE/Trail", 0.35, hits=(True, False, False))],
           stats(n=1, tp1=1, win=1, gross=0.35, net=0.35, peak=0.35, nS=1, netS=0.35))


@check("sim")
def short_hp_trail_never_loosens(E):
    # chandS = [120, 98, 105, 105]: bar2 sl = 98 ; bar3 tv 105 -> sl = min(98, 105) = 98 ; high 99 >= 98 -> px 98.
    # realized = 0.15 + 0.5 * (98 - 100) * (-1) / 10 = 0.25.
    res = sim(E, [FLAT, (99, 100, 96, 96.5), (97, 97.5, 94, 95), (95, 99, 94, 98.5)],
              shorts={0: 10}, mgmt=HP, chandS=[120, 98, 105, 105])
    expect(res, [trade(-1, 0, 3, 100, 10, HP, 98, "BE/Trail", 0.25, hits=(True, False, False))],
           stats(n=1, tp1=1, win=1, gross=0.25, net=0.25, peak=0.25, nS=1, netS=0.25))


@check("sim")
def short_far_tp3_is_na(E):
    # RUN S(100,20): sl 120, tp1 80, tp2 60, tp3 = 100 - 8*20 = -60 -> `tp3 > syminfo.mintick ? tp3 : na` -> na.
    # bar1 (99,100,1,5): hit1 (0.33, openW 0.67), hit2 (0.99, openW 0.34, sl = min(120, 80) = 80) ;
    #        L474 `not na(cur.tp3)` false -> no TP3 although the low is 1.
    # bar2 (5,81,4,80): na chandelier ; L443 high 81 >= 80 -> px 80, "BE/Trail".
    #        realized = 0.99 + 0.34 * (80 - 100) * (-1) / 20 = 1.33.
    res = sim(E, [FLAT, (99, 100, 1, 5), (5, 81, 4, 80)], shorts={0: 20}, mgmt=RUN)
    expect(res, [trade(-1, 0, 2, 100, 20, RUN, 80, "BE/Trail", 1.33, hits=(True, True, False), tp3=None)],
           stats(n=1, tp1=1, tp2=1, win=1, gross=1.33, net=1.33, peak=1.33, nS=1, netS=1.33))


@check("sim")
def short_tp3_mintick_boundary(E):
    # BAL S(100,30): tp3 = 100 - 3*30 = 10 exactly.  L363 is a strict `>`:
    #   mintick 5  -> tp3 = 10 ; bar1 (99,100,9,12): TP1 (70), TP2 (40), TP3 (low 9 <= 10) -> 1.9, exit 10.
    #   mintick 10 -> 10 > 10 false -> na ; same bar: only TP1 + TP2, the trade stays open.
    rows = [FLAT, (99, 100, 9, 12)]
    res = sim(E, rows, shorts={0: 30}, mintick=5.0)
    expect(res, [trade(-1, 0, 1, 100, 30, BAL, 10, "TP3", 1.9, hits=(True, True, True), tp3=10.0)],
           stats(n=1, tp1=1, tp2=1, tp3=1, win=1, gross=1.9, net=1.9, peak=1.9, nS=1, netS=1.9))
    res = sim(E, rows, shorts={0: 30}, mintick=10.0)
    expect(res, [], stats(), open_trade(-1, 0, 100, 30, BAL, hits=(True, True, False), tp3=None))


@check("sim")
def short_stop_touched_exactly(E):
    # bar1 (105,110,104,106): L443 short branch `high >= cur.sl`: 110 >= 110 -> stop at 110, R = -1.
    res = sim(E, [FLAT, (105, 110, 104, 106)], shorts={0: 10})
    expect(res, [trade(-1, 0, 1, 100, 10, BAL, 110, "SL", -1.0)],
           stats(n=1, fullSl=1, loss=1.0, net=-1.0, maxDd=1.0, nS=1, netS=-1.0))


@check("sim")
def short_open_equals_tp1_breakeven_active_same_bar(E):
    # bar1 (90,101,88,95): L407 short branch `open <= cur.tp1`: 90 <= 90 -> hit1 at the opening, sl = min(110, 100)
    # = 100, live at once: high 101 >= 100 -> px 100, "BE/Trail", realized 0.4.
    res = sim(E, [FLAT, (90, 101, 88, 95)], shorts={0: 10})
    expect(res, [trade(-1, 0, 1, 100, 10, BAL, 100, "BE/Trail", 0.4, hits=(True, False, False))],
           stats(n=1, tp1=1, win=1, gross=0.4, net=0.4, peak=0.4, nS=1, netS=0.4))


@check("sim")
def short_range_stop_after_opening_fill_exits_at_open(E):
    # HP S(100,10): tp1 97.  chandS[0] = 94.  bar1 (96,96.5,93,94): L407 open 96 <= 97 -> hit1 (0.15, openW 0.5,
    # sl = min(110, 100) = 100) ; L438-L441 tv = chandS[0] = 94 -> sl = 94 ; L443 high 96.5 >= 94 -> stop ;
    # L445 short branch: open 96 > sl 94 -> px = OPEN 96.  realized = 0.15 + 0.5 * (96 - 100) * (-1) / 10 = 0.35.
    res = sim(E, [FLAT, (96, 96.5, 93, 94)], shorts={0: 10}, mgmt=HP, chandS=[94, 0])
    expect(res, [trade(-1, 0, 1, 100, 10, HP, 96, "BE/Trail", 0.35, hits=(True, False, False))],
           stats(n=1, tp1=1, win=1, gross=0.35, net=0.35, peak=0.35, nS=1, netS=0.35))


# ---- custom weights
@check("sim")
def custom_weights_60_40_close_everything_at_tp2(E):
    # w1 + w2 = 100%.  bar1 (101,111,100.5,108): hit1: realized 0.6, openW 0.4, sl 100.
    # bar2 (108,135,107,130): L463 hit2: w = min(0.4, 0.4) = 0.4 ; realized = 0.6 + 0.8 = 1.4 ; openW = 0.
    #        L471 openW <= 1e-9 -> closeTrade(cur, tp2 120, "TP") ; cur := na, so L474 never marks TP3 although
    #        the high 135 is above tp3 130.
    res = sim(E, [FLAT, (101, 111, 100.5, 108), (108, 135, 107, 130)], longs={0: 10}, mgmt=custom(0.6, 0.4))
    expect(res, [trade(1, 0, 2, 100, 10, BAL, 120, "TP", 1.4, hits=(True, True, False))],
           stats(n=1, tp1=1, tp2=1, win=1, gross=1.4, net=1.4, peak=1.4, nL=1, netL=1.4))


@check("sim")
def custom_weights_60_40_gap_open_above_tp2(E):
    # bar1 opens 125: L407 hit1 (0.6), L416 hit2 (+0.8 = 1.4, openW 0), L424 -> closeTrade(tp2, "TP") in the
    # opening phase ; exit_px 120.  The later dip to 105 (below the stop moved to 110) no longer matters.
    res = sim(E, [FLAT, (125, 140, 105, 139)], longs={0: 10}, mgmt=custom(0.6, 0.4))
    expect(res, [trade(1, 0, 1, 100, 10, BAL, 120, "TP", 1.4, hits=(True, True, False))],
           stats(n=1, tp1=1, tp2=1, win=1, gross=1.4, net=1.4, peak=1.4, nL=1, netL=1.4))


@check("sim")
def custom_weights_100_0_close_everything_at_tp1(E):
    # bar1 (101,125,100.5,124): hit1: w = 1, realized 1.0, openW 0.  L463 needs openW > 1e-9 -> hit2 stays false
    # although the high is above tp2.  L471 -> closeTrade(cur, tp1 110, "TP").
    res = sim(E, [FLAT, (101, 125, 100.5, 124)], longs={0: 10}, mgmt=custom(1.0, 0.0))
    expect(res, [trade(1, 0, 1, 100, 10, BAL, 110, "TP", 1.0, hits=(True, False, False))],
           stats(n=1, tp1=1, win=1, gross=1.0, net=1.0, peak=1.0, nL=1, netL=1.0))
    # the same at the opening (L407 -> L424-L425): bar1 opens at 125, the exit price is still tp1 110 and the
    # reason "TP" even though the bar later trades down to 99, below the breakeven stop.
    res = sim(E, [FLAT, (125, 126, 99, 125)], longs={0: 10}, mgmt=custom(1.0, 0.0))
    expect(res, [trade(1, 0, 1, 100, 10, BAL, 110, "TP", 1.0, hits=(True, False, False))],
           stats(n=1, tp1=1, win=1, gross=1.0, net=1.0, peak=1.0, nL=1, netL=1.0))


@check("sim")
def custom_weight_zero_at_tp1_breakeven_scratch(E):
    # w1 = 0: bar1 (101,111,100.5,108): hit1 with w = 0 -> realized 0, openW 1, but beOn still moves sl to 100.
    # bar2 (105,106,99,100): stop at 100.  activeStopReason: sl != sl0 -> "BE/Trail" even with the full position.
    # realized = 1 * (100 - 100) / 10 = 0 -> R = 0: counted in n and tp1, neither win nor loss (L336-L338).
    res = sim(E, [FLAT, (101, 111, 100.5, 108), (105, 106, 99, 100)], longs={0: 10}, mgmt=custom(0.0, 0.5))
    expect(res, [trade(1, 0, 2, 100, 10, BAL, 100, "BE/Trail", 0.0, hits=(True, False, False))],
           stats(n=1, tp1=1, nL=1))


@check("sim")
def over_allocated_weights_use_min_w_openW(E):
    # w1 = 0.7, w2 = 0.5 (the script's input check forbids this for Custom, but L418 still guards it):
    # bar1 (101,121,100.5,119): hit1: realized 0.7, openW 0.3 ; hit2: w = math.min(0.5, 0.3) = 0.3 ->
    # realized = 0.7 + 0.3 * 2 = 1.3 (not 0.7 + 0.5 * 2), openW 0 -> "TP" at tp2 120.
    res = sim(E, [FLAT, (101, 121, 100.5, 119)], longs={0: 10}, mgmt=custom(0.7, 0.5))
    expect(res, [trade(1, 0, 1, 100, 10, BAL, 120, "TP", 1.3, hits=(True, True, False))],
           stats(n=1, tp1=1, tp2=1, win=1, gross=1.3, net=1.3, peak=1.3, nL=1, netL=1.3))
    # the opening branch has the same guard (L418): bar1 opens at 125 above both targets.
    res = sim(E, [FLAT, (125, 126, 124, 125)], longs={0: 10}, mgmt=custom(0.7, 0.5))
    expect(res, [trade(1, 0, 1, 100, 10, BAL, 120, "TP", 1.3, hits=(True, True, False))],
           stats(n=1, tp1=1, tp2=1, win=1, gross=1.3, net=1.3, peak=1.3, nL=1, netL=1.3))


# ---- cost
@check("sim")
def cost_on_full_stop(E):
    # costPct = 1.0: cR = 1.0 / 100 * 100 / 10 = 0.1 (L329) ; R = -1 - 0.1 = -1.1 ; st.costR = 0.1.
    res = sim(E, [FLAT, (100, 105, 95, 102), (101, 103, 89, 92)], longs={0: 10}, cost=1.0)
    expect(res, [trade(1, 0, 2, 100, 10, BAL, 90, "SL", -1.0, cost=0.1)],
           stats(n=1, fullSl=1, loss=1.1, net=-1.1, maxDd=1.1, costR=0.1, nL=1, netL=-1.1))


@check("sim")
def cost_turns_scratch_into_loss(E):
    # The breakeven scratch above with costPct 1.0: gross 0, cR 0.1 -> R = -0.1: win 0, loss 0.1.
    res = sim(E, [FLAT, (101, 111, 100.5, 108), (105, 106, 99, 100)], longs={0: 10}, mgmt=custom(0.0, 0.5),
              cost=1.0)
    expect(res, [trade(1, 0, 2, 100, 10, BAL, 100, "BE/Trail", 0.0, cost=0.1, hits=(True, False, False))],
           stats(n=1, tp1=1, loss=0.1, net=-0.1, maxDd=0.1, costR=0.1, nL=1, netL=-0.1))


@check("sim")
def cost_larger_than_gross_is_a_loss(E):
    # TP1 then breakeven (gross +0.4) with costPct 5.0: cR = 5 / 100 * 100 / 10 = 0.5 -> R = -0.1.
    # win / gross / loss are decided on R AFTER cost (L330, L336-L338).
    res = sim(E, [FLAT, (101, 111, 100, 108), (104, 106, 99, 100)], longs={0: 10}, cost=5.0)
    expect(res, [trade(1, 0, 2, 100, 10, BAL, 100, "BE/Trail", 0.4, cost=0.5, hits=(True, False, False))],
           stats(n=1, tp1=1, loss=0.1, net=-0.1, maxDd=0.1, costR=0.5, nL=1, netL=-0.1))


@check("sim")
def cost_scales_with_entry_over_risk(E):
    # L(200,4), costPct 0.05: cR = 0.05 / 100 * 200 / 4 = 0.025.  sl 196, tp1 204.
    # bar1 (200,204.5,199,203): hit1 (0.4), sl 200.  bar2 (203,203.5,199.5,200): stop 200, gross 0.4, R = 0.375.
    res = sim(E, [(200, 200, 200, 200), (200, 204.5, 199, 203), (203, 203.5, 199.5, 200)], longs={0: 4}, cost=0.05)
    expect(res, [trade(1, 0, 2, 200, 4, BAL, 200, "BE/Trail", 0.4, cost=0.025, hits=(True, False, False))],
           stats(n=1, tp1=1, win=1, gross=0.375, net=0.375, peak=0.375, costR=0.025, nL=1, netL=0.375))


@check("sim")
def cost_on_reversal_two_trades(E):
    # The reversal scenario with costPct 0.5:
    #   trade 1: cR = 0.005 * 100 / 10 = 0.05  -> R = 0.4 - 0.05 = 0.35
    #   trade 2: cR = 0.005 * 104 / 8  = 0.065 -> R = -1 - 0.065 = -1.065
    # net 0.35 -> -0.715 ; peak 0.35 ; maxDd = 0.35 + 0.715 = 1.065 ; costR = 0.115.
    res = sim(E, [FLAT, (101, 105, 99, 104), (104, 113, 103, 110)], longs={0: 10}, shorts={1: 8}, cost=0.5)
    expect(res, [trade(1, 0, 1, 100, 10, BAL, 104, "Reverse", 0.4, cost=0.05),
                 trade(-1, 1, 2, 104, 8, BAL, 112, "SL", -1.0, cost=0.065)],
           stats(n=2, fullSl=1, win=1, gross=0.35, loss=1.065, net=-0.715, peak=0.35, maxDd=1.065, costR=0.115,
                 nL=1, netL=0.35, nS=1, netS=-1.065))


@check("sim")
def four_trades_stats_peak_and_drawdown(E):
    # A  bar0 L(100,10)     ; bar1 (101,121,100,119): TP1 + TP2 (1.0, openW 0.3, sl 110)
    #    bar2 (118,119,109,112): stop 110 -> +1.3 "BE/Trail"            ; shortSig (dist 8) -> B
    # B  S(112,8): sl 120   ; bar3 (112,121,111,118): high 121 >= 120 -> -1.0 "SL" ; longSig (dist 6) -> C
    # C  L(118,6): sl 112   ; bar4 (109,110,108,109): open 109 <= 112 -> (109-118)/6 = -1.5 "SL" ; shortSig (3) -> D
    # D  S(109,3): sl 112, tp 106 / 103 / 100 ; bar5 (108,109,99,100): TP1 (0.4, sl min(112,109) = 109),
    #    TP2 (1.0, sl min(109,106) = 106), TP3 (low 99 <= 100): +1.9 "TP3"
    # net: 1.3 -> 0.3 -> -1.2 -> 0.7 ; peak 1.3 ; maxDd = 1.3 - (-1.2) = 2.5 ; gross 3.2 ; loss 2.5
    # tp1 = tp2 = 2 (A, D) ; tp3 = 1 ; fullSl = 2 (B, C) ; nL 2, netL = 1.3 - 1.5 = -0.2 ; nS 2, netS = -1 + 1.9 = 0.9
    rows = [FLAT, (101, 121, 100, 119), (118, 119, 109, 112), (112, 121, 111, 118), (109, 110, 108, 109),
            (108, 109, 99, 100)]
    res = sim(E, rows, longs={0: 10, 3: 6}, shorts={2: 8, 4: 3})
    expect(res, [trade(1, 0, 2, 100, 10, BAL, 110, "BE/Trail", 1.3, hits=(True, True, False)),
                 trade(-1, 2, 3, 112, 8, BAL, 120, "SL", -1.0),
                 trade(1, 3, 4, 118, 6, BAL, 109, "SL", -1.5),
                 trade(-1, 4, 5, 109, 3, BAL, 100, "TP3", 1.9, hits=(True, True, True))],
           stats(n=4, tp1=2, tp2=2, tp3=1, fullSl=2, win=2, gross=3.2, loss=2.5, net=0.7, peak=1.3, maxDd=2.5,
                 nL=2, netL=-0.2, nS=2, netS=0.9))


# ════════════════════════════ 2. indicator sanity (ENGINE_SPEC section 2) ════════════════════════════
def f64(x):
    return np.ascontiguousarray(x, dtype=np.float64)


def i_ema(E, x, n):
    return A.ta_ema(f64(x), n) if E is A else B._ema(f64(x), n)


def i_rma(E, x, n):
    return A.ta_rma(f64(x), n) if E is A else B._rma(f64(x), n)


def i_tr(E, h, l, c, handle_na):
    return A.ta_tr(f64(h), f64(l), f64(c), handle_na) if E is A else B._true_range(f64(h), f64(l), f64(c), handle_na)


def i_atr(E, h, l, c, n):
    return A.ta_atr(f64(h), f64(l), f64(c), n) if E is A else B._rma(B._true_range(f64(h), f64(l), f64(c), True), n)


def i_highest(E, x, n):
    return A.ta_highest(f64(x), n) if E is A else B._rolling_max(f64(x), n)


def i_lowest(E, x, n):
    return A.ta_lowest(f64(x), n) if E is A else B._rolling_min(f64(x), n)


def i_rsi(E, c, n):
    return A.ta_rsi(f64(c), n) if E is A else B._rsi(f64(c), n)


def i_dmi(E, h, l, c, n, sm):
    return A.ta_dmi(f64(h), f64(l), f64(c), n, sm) if E is A else B._dmi(f64(h), f64(l), f64(c), n, sm)


def i_supertrend(E, h, l, c, factor, n):
    if E is A:
        return A.ta_supertrend(f64(h), f64(l), f64(c), factor, n)
    return B._supertrend(f64(h), f64(l), f64(c), factor, B._rma(B._true_range(f64(h), f64(l), f64(c), True), n))


# seven hand-checkable bars used by the tr / atr / dmi / supertrend checks
H7 = [10, 12, 13, 12, 15, 14, 11]
L7 = [8, 9, 11, 10, 12, 11, 9]
C7 = [9, 11, 12, 11, 14, 12, 9.5]


@check("indicator")
def ind_ema(E):
    # alpha = 2/(2+1) = 2/3 ; seed = SMA of the first 2 values on bar 1 ; na before.
    #   bar1 (2+4)/2 = 3 ; bar2 2/3*9 + 1/3*3 = 7 ; bar3 2/3*1 + 1/3*7 = 3 ; bar4 2/3*7 + 1/3*3 = 17/3
    close_arr(i_ema(E, [2, 4, 9, 1, 7], 2), [NAN, 3, 7, 3, 17 / 3], what="ema(2)")
    # alpha = 0.5 ; seed SMA(1,2,3) = 2 on bar 2 ; then 3, 4, 5
    close_arr(i_ema(E, [1, 2, 3, 4, 5, 6], 3), [NAN, NAN, 2, 3, 4, 5], what="ema(3)")


@check("indicator")
def ind_rma(E):
    # alpha = 1/3 ; seed SMA(3,6,9) = 6 ; bar3 (12 + 2*6)/3 = 8 ; bar4 (15 + 2*8)/3 = 31/3
    close_arr(i_rma(E, [3, 6, 9, 12, 15], 3), [NAN, NAN, 6, 8, 31 / 3], what="rma(3)")
    # a leading na delays the seed: the first bar with 3 non-na values is bar 3
    close_arr(i_rma(E, [NAN, 3, 6, 9, 12], 3), [NAN, NAN, NAN, 6, 8], what="rma(3) leading na")


@check("indicator")
def ind_tr_atr(E):
    # tr: bar0 high-low = 2 (handle_na) / na ; bar1 max(3, |12-9|, |9-9|) = 3 ; bar2 max(2, |13-11|, 0) = 2 ;
    #     bar3 max(2, 0, |10-12|) = 2 ; bar4 max(3, |15-11|, 1) = 4 ; bar5 max(3, 0, |11-14|) = 3 ; bar6 max(2, 1, 3) = 3
    close_arr(i_tr(E, H7, L7, C7, True), [2, 3, 2, 2, 4, 3, 3], what="tr(true)")
    close_arr(i_tr(E, H7, L7, C7, False), [NAN, 3, 2, 2, 4, 3, 3], what="tr(false)")
    # atr(2) = rma(tr(true), 2): seed (2+3)/2 = 2.5 ; then (tr + prev)/2: 2.25, 2.125, 3.0625, 3.03125, 3.015625
    close_arr(i_atr(E, H7, L7, C7, 2), [NAN, 2.5, 2.25, 2.125, 3.0625, 3.03125, 3.015625], what="atr(2)")


@check("indicator")
def ind_highest_lowest(E):
    x = [3, 1, 4, 1, 5, 9, 2, 6]
    close_arr(i_highest(E, x, 3), [NAN, NAN, 4, 4, 5, 9, 9, 9], what="highest(3)")
    close_arr(i_lowest(E, x, 3), [NAN, NAN, 1, 1, 1, 1, 2, 2], what="lowest(3)")


@check("indicator")
def ind_rsi(E):
    # closes 10 11 10 12 11 13 ; change: na +1 -1 +2 -1 +2 ; u: na 1 0 2 0 2 ; d: na 0 1 0 1 0
    # rma(u,2): bar2 (1+0)/2 = 0.5 ; bar3 (2+0.5)/2 = 1.25 ; bar4 0.625 ; bar5 (2+0.625)/2 = 1.3125
    # rma(d,2): bar2 0.5 ; bar3 0.25 ; bar4 (1+0.25)/2 = 0.625 ; bar5 0.3125
    # rs: 1, 5, 1, 4.2 -> rsi = 100 - 100/(1+rs): 50, 100 - 100/6, 50, 100 - 100/5.2
    close_arr(i_rsi(E, [10, 11, 10, 12, 11, 13], 2), [NAN, NAN, 50, 100 - 100 / 6, 50, 100 - 100 / 5.2], what="rsi(2)")
    # only gains: rma(d) == 0 -> 100 ; only losses: rma(u) == 0 -> 0
    close_arr(i_rsi(E, [1, 2, 3, 4], 2), [NAN, NAN, 100, 100], what="rsi all up")
    close_arr(i_rsi(E, [4, 3, 2, 1], 2), [NAN, NAN, 0, 0], what="rsi all down")


@check("indicator")
def ind_dmi(E):
    # up = change(high):  na  2  1 -1  3 -1 -3      down = -change(low):  na -1 -2  1 -2  1  2
    # plusDM  (up > down and up > 0 ? up : 0):      na  2  1  0  3  0  0
    # minusDM (down > up and down > 0 ? down : 0):  na  0  0  1  0  1  2
    # tr(false):                                    na  3  2  2  4  3  3
    # len 2 -> every rma is "(x + prev)/2", seeded on bar 2 with the mean of bars 1 and 2:
    #   trur:  2.5    2.25   3.125   3.0625   3.03125
    #   rma+:  1.5    0.75   1.875   0.9375   0.46875
    #   rma-:  0      0.5    0.25    0.625    1.3125
    #   plus  = 100*rma+/trur:  60, 100/3, 60, 93.75/3.0625, 46.875/3.03125
    #   minus = 100*rma-/trur:   0, 200/9,  8, 62.5/3.0625, 131.25/3.03125
    #   dx = |plus-minus|/(plus+minus) = |rma+ - rma-|/(rma+ + rma-):  1, 0.2, 13/17, 0.2, 9/19
    #   adx = 100*rma(dx,2): bar3 100*(1+0.2)/2 = 60 ; bar4 100*(13/17+0.6)/2 ; bar5 ; bar6
    plus, minus, adx = i_dmi(E, H7, L7, C7, 2, 2)
    close_arr(plus, [NAN, NAN, 60, 100 / 3, 60, 93.75 / 3.0625, 46.875 / 3.03125], what="+DI")
    close_arr(minus, [NAN, NAN, 0, 200 / 9, 8, 62.5 / 3.0625, 131.25 / 3.03125], what="-DI")
    a4 = (13 / 17 + 0.6) / 2
    a5 = (0.2 + a4) / 2
    a6 = (9 / 19 + a5) / 2
    close_arr(adx, [NAN, NAN, NAN, 60, 100 * a4, 100 * a5, 100 * a6], what="ADX")


@check("indicator")
def ind_dmi_outside_inside_bars(E):
    # len = smoothing = 1 makes every rma the identity, so each bar can be checked on its own.
    #   h 10 11 10.5 12 13 ; l 8 6 7 9 8 ; c 9 7 8 11 10
    # bar1 outside bar: up 1, down 2 -> plusDM 0 (up < down), minusDM 2 ; tr = max(5, |11-9|, |6-9|) = 5
    #       plus 0, minus 40 ; dx = 40/40 = 1 -> adx 100
    # bar2 inside bar: up -0.5, down -1 -> both DM 0 ; tr 3.5 ; plus = minus = 0 ; sum == 0 -> dx = 0/1 -> adx 0
    # bar3: up 1.5, down -2 -> plusDM 1.5 ; tr = max(3, |12-8|, 1) = 4 ; plus 37.5, minus 0 -> adx 100
    # bar4: up 1, down 1 -> neither is strictly greater -> both DM 0 ; tr = max(5, 2, 3) = 5 -> 0, 0, adx 0
    plus, minus, adx = i_dmi(E, [10, 11, 10.5, 12, 13], [8, 6, 7, 9, 8], [9, 7, 8, 11, 10], 1, 1)
    close_arr(plus, [NAN, 0, 0, 37.5, 0], what="+DI")
    close_arr(minus, [NAN, 40, 0, 0, 0], what="-DI")
    close_arr(adx, [NAN, 100, 0, 100, 0], what="ADX")


@check("indicator")
def ind_supertrend(E):
    # factor 1, atr(2) = na 2.5 2.25 2.125 3.0625 3.03125 3.015625 ; hl2 = 9 10.5 12 11 13.5 12.5 10
    # bar0: bands na -> lower = upper = nz(prev) = 0 ; na(atr[1]) -> dir 1 ; st = upper = 0
    # bar1: raw 13 / 8 ; lower 8 > 0 keep ; upper: close[1] 9 > prevUpper 0 -> 13 ; na(atr[1]) -> dir 1 ; st 13
    # bar2: raw 14.25 / 9.75 ; lower 9.75 ; upper: 14.25 < 13 no, close[1] 11 > 13 no -> 13 ;
    #       prevST 13 == prevUpper 13 -> dir = close 12 > 13 ? -1 : 1 = 1 ; st 13
    # bar3: raw 13.125 / 8.875 ; lower: 8.875 > 9.75 no, close[1] 12 < 9.75 no -> 9.75 ; upper 13 ; close 11 -> dir 1
    # bar4: raw 16.5625 / 10.4375 ; lower 10.4375 ; upper 13 ; close 14 > 13 -> dir -1 ; st = lower 10.4375
    # bar5: raw 15.53125 / 9.46875 ; lower stays 10.4375 ; upper: close[1] 14 > 13 -> 15.53125 ;
    #       prevST 10.4375 != prevUpper 13 -> dir = close 12 < 10.4375 ? 1 : -1 = -1 ; st 10.4375
    # bar6: raw 13.015625 / 6.984375 ; lower 10.4375 ; upper 13.015625 < 15.53125 -> 13.015625 ;
    #       close 9.5 < 10.4375 -> dir 1 ; st = upper 13.015625
    st, direction = i_supertrend(E, H7, L7, C7, 1.0, 2)
    close_arr(direction, [1, 1, 1, 1, -1, -1, 1], what="supertrend direction")
    close_arr(st, [0, 13, 13, 13, 10.4375, 10.4375, 13.015625], what="supertrend line")


# ════════════════════════════ 3. profile / cost tables, input checks ════════════════════════════
def mk_market(ticker="TEST", sym_type="stock", tf=3600, htf=14400, mintick=0.01):
    return ds.Market(f"SYN_{ticker}_x", "SYN", ticker, sym_type, "x", tf, htf, mintick)


def e_mgmt(E, p, market):
    return A.management_profile(p, market) if E is A else B.mgmt_of(p, market)


def e_cost(E, p, market):
    return A.round_trip_cost_pct(p, market) if E is A else B.cost_pct(p, market)


@check("table")
def profile_table(E):
    P = E.Params
    stock, crypto = mk_market(), mk_market("BTCUSDT", "crypto")
    assert e_mgmt(E, P(profile="HP"), stock) == HP
    assert e_mgmt(E, P(profile="BAL"), stock) == BAL
    assert e_mgmt(E, P(profile="RUN"), stock) == RUN
    # L208: Auto -> crypto: Trend Runner, everything else: High-Probability
    assert e_mgmt(E, P(), stock) == HP and e_mgmt(E, P(profile="AUTO"), crypto) == RUN
    assert e_mgmt(E, P(profile="HP"), crypto) == HP          # an explicit profile is not overridden
    # Custom defaults (L50-L56): 1R / 2R / 3R, 40% / 30%, cTrail false, cBe true ; trailFrom is 1 (L217)
    assert e_mgmt(E, P(profile="CUS"), stock) == custom(0.4, 0.3)
    got = e_mgmt(E, P(profile="CUS", cTp1=0.5, cTp2=1.5, cTp3=5.0, cW1=25.0, cW2=50.0, cTrail=True, cBe=False), stock)
    assert got == dict(k1=0.5, k2=1.5, k3=5.0, w1=0.25, w2=0.5, trailOn=True, trailFrom=1, beOn=False), got
    # cTrail / cBe only matter for Custom
    assert e_mgmt(E, P(profile="BAL", cTrail=True, cBe=False), stock) == BAL


@check("table")
def cost_table(E):
    P = E.Params
    c = lambda tk, typ="cfd", **kw: e_cost(E, P(**kw), mk_market(tk, typ))  # noqa: E731
    assert c("XAUUSD") == 0.03 and c("EURUSD", "forex") == 0.03 and c("AAPL", "stock") == 0.03
    assert c("XAGUSD") == 0.06 and c("SILVER", "futures") == 0.06 and c("XPTUSD") == 0.06 and c("XCUUSD") == 0.06
    assert c("BTCUSDT", "crypto") == 0.10
    assert c("XAGUSDT", "crypto") == 0.10                    # L195: the crypto test comes first
    assert c("XAGUSD", costMode="Custom") == 0.05 and c("BTCUSDT", "crypto", costMode="Custom", costCustom=0.2) == 0.2


def jump_chart(J, jump_close, n_after=9):
    """Steady decline 300 - 0.5*i for bars 0 .. J-1, one huge up bar J closing at jump_close, then flat bars."""
    rows = []
    for i in range(J):
        c = 300.0 - 0.5 * i
        o = c + 0.25
        rows.append((o, o + 0.1, c - 0.1, c))
    prev = rows[-1][3]
    rows.append((prev, jump_close + 0.1, prev - 0.1, jump_close))
    rows += [(jump_close, jump_close + 0.1, jump_close - 0.1, jump_close)] * n_after
    return chart_of(rows, 3600)


def chart_of(rows, tf):
    a = np.array(rows, dtype=float)
    return {"t": np.arange(len(rows), dtype=np.int64) * tf, "o": a[:, 0].copy(), "h": a[:, 1].copy(),
            "l": a[:, 2].copy(), "c": a[:, 3].copy(), "v": np.zeros(len(rows))}


def mirrored(chart, around=500.0):
    """The same chart with every price p replaced by around - p: longs become shorts, highs become lows."""
    return {"t": chart["t"], "o": around - chart["o"], "h": around - chart["l"], "l": around - chart["h"],
            "c": around - chart["c"], "v": chart["v"]}


def htf_of(chart, seconds=14400):
    return ds.resample_by_key(chart, [int(x) // seconds for x in chart["t"]])


@check("table")
def input_checks(E):
    P = E.Params
    chart = jump_chart(255, 190.0)
    htf = htf_of(chart)
    mkt = mk_market()

    def raises(**kw):
        try:
            E.run(chart, htf, P(**kw), mkt)
        except ValueError:
            return True
        return False

    assert raises(slMinAtr=2.0, slMaxAtr=1.0)                                  # L104
    assert not raises(slMinAtr=1.0, slMaxAtr=1.0)                              # equal is allowed
    assert raises(profile="CUS", cTp1=2.0, cTp2=2.0, cTp3=3.0)                 # L107 strict <
    assert raises(profile="CUS", cTp1=1.0, cTp2=3.0, cTp3=3.0)
    assert raises(profile="CUS", cW1=60.0, cW2=40.5)                           # L109
    assert not raises(profile="CUS", cW1=60.0, cW2=40.0)                       # exactly 100 is allowed
    assert not raises(profile="HP", cTp1=5.0, cTp2=1.0, cW1=90.0, cW2=90.0)    # only checked for Custom (L106)


# ════════════════════════════ 4. run() on synthetic charts ════════════════════════════
# Jump chart (1h, type stock -> Auto profile = HP, cost 0.03%, no small-frame guard):
#   bars 0 .. J-1: close = 300 - 0.5*i, open = close + 0.25, high = open + 0.1, low = close - 0.1
#   bar J:         open = close[J-1], close = jump_close (far above), high = close + 0.1, low = open - 0.1
#   afterwards:    flat at jump_close (high +0.1, low -0.1)
# Hand analysis of bar J (J >= 249):
#   brkUp  : close > highest(high,20)[1] (about 10 above close[J-1]) and close[J-1] <= donHi[J-1]      -> true
#   flipUp : the decline keeps SuperTrend in a down-trend from the first bars (close never exceeds the upper
#            band) ; on bar J the final upper band is still the previous one (about close[J-1] + 2) and the close is
#            far above it -> direction -1 with direction[1] = +1                                         -> true
#   pbUp   : stDir < 0 ; lowest(low - ema21, 5) <= 0 (bar J-1 was ~5 below its EMA21) ; close > high[1] ;
#            close > ema21 ; close > open                                                                -> true
#   before J: no up trigger at all (falling closes, SuperTrend down) ; brkDn is false on every bar because
#            close[1] >= donLo[1] never holds in a steady decline ; pbDn is false (high - ema21 < 0) ; no flipDn.
#   after J : flat closes below the previous high -> no trigger.
# So with minScore = 0 and useTsm = false the only possible signal is a long on bar J.
LOOSE = dict(minScore=0, useTsm=False)


def run_series(E, chart, mkt, **params):
    res = E.run(chart, htf_of(chart, mkt.htf_seconds), E.Params(**params), mkt)
    return res, res["series"]


@check("run")
def warm_is_bar_index_ge_250(E):
    mkt = mk_market()
    # jump on bar 249: warm (L186) is false -> no signal anywhere, no trade
    res, s = run_series(E, jump_chart(249, 189.5), mkt, **LOOSE)
    assert not s["longSig"].any() and not s["shortSig"].any()
    assert res["trades"] == [] and res["open_trade"] is None
    # jump on bar 250: bar_index >= 250 holds -> the long signal fires exactly there
    res, s = run_series(E, jump_chart(250, 189.5), mkt, **LOOSE)
    assert np.flatnonzero(s["longSig"]).tolist() == [250] and not s["shortSig"].any()
    assert res["trades"] == [] and res["open_trade"]["entry_bar"] == 250 and res["open_trade"]["dir"] == 1
    assert res["open_trade"]["entry"] == 189.5 and res["stats"]["n"] == 0
    # mirrored charts (a steady rise, then a crash bar): the same for shortSig (L203)
    res, s = run_series(E, mirrored(jump_chart(249, 189.5)), mkt, **LOOSE)
    assert not s["longSig"].any() and not s["shortSig"].any() and res["open_trade"] is None
    res, s = run_series(E, mirrored(jump_chart(250, 189.5)), mkt, **LOOSE)
    assert np.flatnonzero(s["shortSig"]).tolist() == [250] and not s["longSig"].any()
    assert res["open_trade"]["entry_bar"] == 250 and res["open_trade"]["dir"] == -1


@check("run")
def trigger_name_precedence(E):
    mkt = mk_market()
    chart = jump_chart(280, 190.5)
    cases = [
        (dict(), "BRK"),                                       # all three fire: BRK wins (L183)
        (dict(usePb=False), "BRK"),
        (dict(useFlip=False), "BRK"),
        (dict(useBrk=False), "FLIP"),                          # BRK disabled -> FLIP before PB
        (dict(useBrk=False, usePb=False), "FLIP"),
        (dict(useBrk=False, useFlip=False), "PB"),
        (dict(useFlip=False, usePb=False), "BRK"),
    ]
    for kw, name in cases:
        res, s = run_series(E, chart, mkt, **LOOSE, **kw)
        assert np.flatnonzero(s["longSig"]).tolist() == [280], (kw, np.flatnonzero(s["longSig"]).tolist())
        assert not s["shortSig"].any(), kw
        ot = res["open_trade"]
        assert ot is not None and ot["entry_bar"] == 280 and ot["trig"] == name, (kw, ot)
        assert ot["score"] == int(s["scoreL"][280]), (kw, ot)
    # no trigger enabled -> trigL false (L181) -> no signal
    res, s = run_series(E, chart, mkt, **LOOSE, useBrk=False, useFlip=False, usePb=False)
    assert not s["longSig"].any() and res["open_trade"] is None
    # direction filter (L202-L203)
    res, s = run_series(E, chart, mkt, **LOOSE, dirMode="Short only")
    assert not s["longSig"].any() and res["open_trade"] is None
    res, s = run_series(E, chart, mkt, **LOOSE, dirMode="Long only")
    assert np.flatnonzero(s["longSig"]).tolist() == [280]
    # short side on the mirrored chart: trigNameS (L184) has the same precedence
    crash = mirrored(chart)
    for kw, name in cases:
        res, s = run_series(E, crash, mkt, **LOOSE, **kw)
        assert np.flatnonzero(s["shortSig"]).tolist() == [280] and not s["longSig"].any(), kw
        ot = res["open_trade"]
        assert ot is not None and ot["dir"] == -1 and ot["entry_bar"] == 280 and ot["trig"] == name, (kw, ot)
        assert ot["score"] == int(s["scoreS"][280]), (kw, ot)
    res, s = run_series(E, crash, mkt, **LOOSE, dirMode="Long only")
    assert not s["shortSig"].any() and not s["longSig"].any() and res["open_trade"] is None
    res, s = run_series(E, crash, mkt, **LOOSE, dirMode="Short only")
    assert np.flatnonzero(s["shortSig"]).tolist() == [280]


@check("run")
def tsm_gate_needs_all_four_lookbacks(E):
    # J = 280: close[260] = 170, close[230] = 185, close[180] = 210, close[80] = 260 (L150).
    #   jump close 259.5 -> signs + + + -  -> tsm = 0.5  -> tsmL false
    #   jump close 260.0 -> signs + + + 0  -> tsm = 0.75 -> tsmL false (math.sign(0) = 0)
    #   jump close 260.5 -> signs + + + +  -> tsm = 1    -> tsmL true (L187: tsm >= 1)
    mkt = mk_market()
    for jump_close, fires in ((259.5, False), (260.0, False), (260.5, True)):
        res, s = run_series(E, jump_chart(280, jump_close), mkt, minScore=0)      # useTsm = true (default)
        assert np.flatnonzero(s["longSig"]).tolist() == ([280] if fires else []), (jump_close, s["longSig"].sum())
        res2, s2 = run_series(E, jump_chart(280, jump_close), mkt, minScore=0, useTsm=False)
        assert np.flatnonzero(s2["longSig"]).tolist() == [280], jump_close
        # mirrored: tsm = -0.5 / -0.75 / -1 -> tsmS (L188: tsm <= -1) only in the last case
        res3, s3 = run_series(E, mirrored(jump_chart(280, jump_close)), mkt, minScore=0)
        assert np.flatnonzero(s3["shortSig"]).tolist() == ([280] if fires else []), jump_close
        assert not s3["longSig"].any()


# Ramp-and-pullback chart (1h): only the pullback trigger can fire, and every condition of L178 is isolated.
#   bars 0 .. 269: close = 100 + i, open = close - 1, high = close + 0.2, low = open - 0.2
#       tr = 1.4 on every bar ; ema21 = close - 10 exactly (the SMA seed of a ramp keeps the lag) ;
#       brkUp is FALSE on every ramp bar: close > donHi, but close[1] = c-1 > donHi[1] = c-1.8 (L172 wants <=) ;
#       touchUp is false: low - ema21 = 8.8 > 0 ; SuperTrend(10, 10) turns up on bar 23 and stays up
#       (lower band = hl2 - 10*1.4 = close - 14.5, i.e. 354.5 on bar 269 ; no later close comes near it).
#       donHi stays 369.2 (high of bar 269 / 270) for the rest of the chart -> no further brkUp ; no flip.
#   bar  (open, high, low, close)        ema21    low-ema  pbUp conditions (stDir < 0 holds throughout)
#   270  (369.0, 369.2, 365.8, 366.0)    359.636   6.16    down bar
#   271  (366.0, 366.2, 362.8, 363.0)    359.942   2.86    down bar
#   272  (363.0, 363.2, 358.0, 358.5)    359.811  -1.81    touch ; down bar.  Also close < low[1], close < ema21,
#                                                          close < open, high - ema21 >= 0: everything pbDn (L179)
#                                                          needs EXCEPT stDir > 0 -> no short signal
#   273  (358.5, 358.9, 358.2, 358.6)    359.701  -1.50    touch ; close 358.6 <= high[1] 363.2
#   274  (358.6, 359.3, 358.5, 359.2)    359.655  -1.16    touch, close > high[1] 358.9, close > open, but
#                                                          close 359.2 < ema21                      -> no
#   275  (361.5, 361.7, 360.5, 360.9)    359.769   0.73    close > high[1] 359.3, close > ema21, touch in window,
#                                                          but close < open                         -> no
#   276  (360.9, 361.6, 360.8, 361.5)    359.926   0.87    close > open, > ema21, touch in window, but
#                                                          close 361.5 <= high[1] 361.7             -> no
#   277  (361.5, 361.7, 360.9, 361.1)    360.033   0.87    down bar
#   278  (361.1, 364.7, 361.1, 364.5)    360.439   0.66    close > high[1] 361.7, > ema21, > open ; the window of
#                                                          ta.lowest(low - ema21, 5) is bars 274 .. 278 and bar
#                                                          274 is its only touch                    -> pbUp
#   then two flat bars at 364.5 (close > open fails).
# Variant "late": one more down bar (361.1, 361.3, 360.8, 360.9; ema21 360.112) is inserted before the resume
#   bar, which becomes bar 279 (ema21 360.510 < low 360.9): the last touch (bar 274) is now 5 bars back, outside
#   the window 275 .. 279 -> touchUp false -> no signal at all.
def pullback_chart(late=False):
    rows = []
    for i in range(270):
        c = 100.0 + i
        rows.append((c - 1, c + 0.2, c - 1.2, c))
    rows += [(369.0, 369.2, 365.8, 366.0), (366.0, 366.2, 362.8, 363.0), (363.0, 363.2, 358.0, 358.5),
             (358.5, 358.9, 358.2, 358.6), (358.6, 359.3, 358.5, 359.2), (361.5, 361.7, 360.5, 360.9),
             (360.9, 361.6, 360.8, 361.5), (361.5, 361.7, 360.9, 361.1)]
    if late:
        rows += [(361.1, 361.3, 360.8, 360.9), (360.9, 364.7, 360.9, 364.5)]
    else:
        rows += [(361.1, 364.7, 361.1, 364.5)]
    rows += [(364.5, 364.7, 364.3, 364.5)] * 2
    return chart_of(rows, 3600)


@check("run")
def pullback_trigger_only(E):
    mkt = mk_market()
    chart = pullback_chart()
    for kw in (dict(), dict(useBrk=False, useFlip=False), dict(useBrk=False), dict(useFlip=False)):
        res, s = run_series(E, chart, mkt, stFactor=10.0, **LOOSE, **kw)
        assert np.flatnonzero(s["longSig"]).tolist() == [278], (kw, np.flatnonzero(s["longSig"]).tolist())
        assert not s["shortSig"].any(), (kw, np.flatnonzero(s["shortSig"]).tolist())
        assert res["trades"] == [] and res["open_trade"]["entry_bar"] == 278 and res["open_trade"]["trig"] == "PB"
    res, s = run_series(E, chart, mkt, stFactor=10.0, **LOOSE, usePb=False)
    assert not s["longSig"].any() and not s["shortSig"].any() and res["open_trade"] is None
    # touch 5 bars back: outside ta.lowest(low - ema21, 5)
    res, s = run_series(E, pullback_chart(late=True), mkt, stFactor=10.0, **LOOSE)
    assert not s["longSig"].any() and not s["shortSig"].any() and res["open_trade"] is None
    # the mirrored chart (prices reflected around 500) fires the short pullback pbDn (L179) and nothing else
    res, s = run_series(E, mirrored(chart), mkt, stFactor=10.0, **LOOSE)
    assert np.flatnonzero(s["shortSig"]).tolist() == [278] and not s["longSig"].any()
    assert res["open_trade"]["dir"] == -1 and res["open_trade"]["trig"] == "PB"
    res, s = run_series(E, mirrored(pullback_chart(late=True)), mkt, stFactor=10.0, **LOOSE)
    assert not s["longSig"].any() and not s["shortSig"].any() and res["open_trade"] is None
    res, s = run_series(E, mirrored(chart), mkt, stFactor=10.0, **LOOSE, dirMode="Long only")
    assert not s["shortSig"].any() and res["open_trade"] is None


# Sawtooth chart: an up-trend that breaks its 20-bar high on every second bar.
#   k = bar + phase, m = k // 2
#   even k: close = m + 0.6, open = close - 0.05        odd k: close = m + 0.3, open = close + 0.05
#   high = close + 0.1, low = close - 0.1
# Hand analysis for an even bar i (phase 0, i >= 22):
#   donHi = highest high of bars i-20 .. i-1 = high[i-2] = i/2 - 0.3 ; close = i/2 + 0.6 > donHi ;
#   close[1] = i/2 - 0.7 <= donHi[1] = i/2 - 0.3                                   -> brkUp true on every even bar
#   odd bar: close = (i-1)/2 + 0.3 < donHi = high[i-1] = (i-1)/2 + 0.7             -> brkUp false
#   tr: even bars |high - close[1]| = 1.4, odd bars |low - close[1]| = 0.4
#   atr(14) alternates in steady state: a_even = (13*a_odd + 1.4)/14, a_odd = (13*a_even + 0.4)/14
#       -> a_even = 24.8/27 = 0.918518..., a_odd = 23.8/27 = 0.881481...     ((13/14)^250 ~ 1e-8 from the seed)
#   slDistL on an even bar: lowest(low,10) = low[i-9] = i/2 - 4.8 ; close - (lowest - 0.25*atr) = 5.4 + 0.2296
#       -> clamped to slMaxAtr*atr = 3.5 * 24.8/27 = 86.8/27 = 3.214814...
ATR_EVEN = 24.8 / 27
RISK = 3.5 * ATR_EVEN


def sawtooth_chart(n, tf, phase=0):
    rows = []
    for i in range(n):
        k = i + phase
        m = k // 2
        if k % 2 == 0:
            c = m + 0.6
            o = c - 0.05
        else:
            c = m + 0.3
            o = c + 0.05
        rows.append((o, c + 0.1, c - 0.1, c))
    return chart_of(rows, tf)


@check("run")
def sawtooth_signals_and_first_trades(E):
    mkt = mk_market()                                         # 1h, stock: HP profile, cost 0.03%
    only_brk = dict(minScore=0, useTsm=False, useFlip=False, usePb=False)
    res, s = run_series(E, sawtooth_chart(320, 3600), mkt, **only_brk)
    # signals: every even bar from 250 on, nothing before (warm), never a short
    assert np.flatnonzero(s["longSig"]).tolist() == list(range(250, 320, 2))
    assert not s["shortSig"].any()
    assert abs(s["atr"][250] - ATR_EVEN) < 1e-6 and abs(s["atr"][251] - 23.8 / 27) < 1e-6
    # five of the seven score terms are directional and all favour the long side in this up-trend (HTF trend is
    # +1 on the 4h resample, close > ema200, ema21 > ema55, +DI > -DI, RSI > 50) ; the two ADX terms count for
    # BOTH sides (L160-L161) -> scoreL - scoreS == 5 exactly.
    assert s["htfTrend"][250] == 1.0
    assert int(s["scoreL"][250]) - int(s["scoreS"][250]) == 5 and int(s["scoreL"][250]) >= 6
    # Steady-state ADX of this pattern (every rma(14) of a 2-periodic input x_e, x_o settles at
    # r_e = (13*x_o + 14*x_e)/27, r_o = (13*x_e + 14*x_o)/27):
    #   plusDM 1.3 / 0, minusDM 0 / 0.3 (even / odd) -> dx_even = 14.3/22.1 = 0.6471, dx_odd = 12.7/21.1 = 0.6019
    #   adx_even = 62.53 > adx_odd = 62.36 -> "adx > adx[3]" (L161) is true on even bars, false on odd bars
    # -> scoreL = 7, scoreS = 2 on even bars ; scoreL = 6, scoreS = 1 on odd bars.
    assert int(s["scoreL"][250]) == 7 and int(s["scoreS"][250]) == 2
    assert int(s["scoreL"][251]) == 6 and int(s["scoreS"][251]) == 1
    # so the script's DEFAULT inputs fire as well: scoreL >= minScore holds with equality (7 >= 7, L202) and
    # tsm = 1 (close above its value 20 / 50 / 100 / 200 bars ago) ; no flip / pullback trigger exists here.
    res_d, s_d = run_series(E, sawtooth_chart(320, 3600), mkt)
    assert np.flatnonzero(s_d["longSig"]).tolist() == list(range(250, 320, 2)) and not s_d["shortSig"].any()
    assert [t["entry_bar"] for t in res_d["trades"]] == [250, 276] and res_d["open_trade"]["entry_bar"] == 302
    _, s_6 = run_series(E, sawtooth_chart(320, 3600), mkt, minScore=6, useBrk=True, useFlip=False, usePb=False)
    assert np.flatnonzero(s_6["longSig"]).tolist() == list(range(250, 320, 2))      # odd bars have no trigger
    # shifted by one bar the same pattern breaks out on odd bars: first signal on 251, not 250
    res1, s1 = run_series(E, sawtooth_chart(320, 3600, phase=1), mkt, **only_brk)
    assert np.flatnonzero(s1["longSig"]).tolist() == list(range(251, 320, 2))

    # Trade 1, traced by hand through block 1 of the script:
    #   bar 250: L(125.6, 86.8/27): sl 122.385, tp1 = 125.6 + 0.3*risk = 126.5644, tp2 = 130.4222, tp3 = 138.4593
    #   bar 252 (even): open 126.55 < tp1 ; high 126.7 >= tp1 -> TP1 by range: realized 0.15, openW 0.5, sl = 125.6
    #   bars 253 .. 259: the chandelier (22-bar high - 3*atr, about 2 .. 3 below price) never reaches a low
    #   bar 260 (even): open 130.55 >= tp2 -> TP2 at the OPEN: realized 0.15 + 0.25*1.5 = 0.525, openW 0.25
    #   bar 276 (even): open 138.55 >= tp3 (bar 274 high 137.7 was below) -> TP3 at the open:
    #                   realized = 0.525 + 0.25*4 = 1.525 ; closeTrade(tp3, "TP3")
    #   cR = 0.03/100 * 125.6 / risk
    #   block 2 on bar 276: longSig and na(cur) -> trade 2 = L(138.6, risk), the same path 26 bars later
    #   (TP3 on bar 302), then trade 3 opens on bar 302 and is still open on the last bar 319.
    tr = res["trades"]
    assert len(tr) == 2, tr
    for k, t in enumerate(tr):
        e_bar = 250 + 26 * k
        entry = e_bar / 2 + 0.6
        want = trade(1, e_bar, e_bar + 26, entry, RISK, HP, entry + 4 * RISK, "TP3", 1.525,
                     cost=0.03 / 100 * entry / RISK, hits=(True, True, True), score=int(s["scoreL"][e_bar]))
        for key in TRADE_KEYS:
            g, w = t[key], want[key]
            if isinstance(w, float):
                assert abs(g - w) <= 1e-6 * max(1.0, abs(w)), (k, key, g, w)
            else:
                assert g == w, (k, key, g, w)
    ot = res["open_trade"]
    assert ot["entry_bar"] == 302 and ot["dir"] == 1 and abs(ot["entry"] - 151.6) < 1e-9 and ot["trig"] == "BRK"
    st = res["stats"]
    assert (st["n"], st["tp1"], st["tp2"], st["tp3"], st["fullSl"], st["win"], st["nL"], st["nS"]) == \
        (2, 2, 2, 2, 0, 2, 2, 0)
    cost_sum = 0.03 / 100 * (125.6 + 138.6) / RISK
    assert abs(st["net"] - (3.05 - cost_sum)) < 1e-6 and abs(st["costR"] - cost_sum) < 1e-6
    assert abs(st["gross"] - st["net"]) < 1e-12 and st["loss"] == 0.0 and st["maxDd"] == 0.0
    assert abs(st["peak"] - st["net"]) < 1e-12 and abs(st["netL"] - st["net"]) < 1e-12 and st["netS"] == 0.0

    # Mirrored chart (prices 500 - p): the same path as shorts.  Entry 500 - 125.6 = 374.4 ; slDistS (L192) is
    # the mirror of slDistL ; chandS the mirror of chandL ; tp3 = 374.4 - 4*risk = 361.5 > mintick.
    # Only the cost differs: cR = 0.03/100 * 374.4 / risk (cost is proportional to the entry price).
    res, s = run_series(E, mirrored(sawtooth_chart(320, 3600)), mkt, **only_brk)
    assert np.flatnonzero(s["shortSig"]).tolist() == list(range(250, 320, 2)) and not s["longSig"].any()
    assert s["htfTrend"][250] == -1.0 and int(s["scoreS"][250]) - int(s["scoreL"][250]) == 5
    tr = res["trades"]
    assert len(tr) == 2, tr
    for k, t in enumerate(tr):
        e_bar = 250 + 26 * k
        entry = 500.0 - (e_bar / 2 + 0.6)
        want = trade(-1, e_bar, e_bar + 26, entry, RISK, HP, entry - 4 * RISK, "TP3", 1.525,
                     cost=0.03 / 100 * entry / RISK, hits=(True, True, True), score=int(s["scoreS"][e_bar]))
        for key in TRADE_KEYS:
            g, w = t[key], want[key]
            if isinstance(w, float):
                assert abs(g - w) <= 1e-6 * max(1.0, abs(w)), (k, key, g, w)
            else:
                assert g == w, (k, key, g, w)
    ot = res["open_trade"]
    assert ot["entry_bar"] == 302 and ot["dir"] == -1 and abs(ot["entry"] - 348.4) < 1e-9
    st = res["stats"]
    assert (st["n"], st["tp3"], st["win"], st["nL"], st["nS"]) == (2, 2, 2, 0, 2)
    cost_sum = 0.03 / 100 * (374.4 + 361.4) / RISK
    assert abs(st["netS"] - (3.05 - cost_sum)) < 1e-6 and st["netL"] == 0.0 and abs(st["costR"] - cost_sum) < 1e-6


@check("run")
def small_frame_guard(E):
    # 15m chart (timeframe.in_seconds() = 900 < 3600 -> smallTf, L197).  On the breakout bars slDistL = 3.2148.
    #   cgMinDist = costPct/100 * close / (cgMaxPct/100)                                             (L198)
    #   Auto cost 0.03%:     0.0003 * 125.6 / 0.07 = 0.538 <= 3.2148 -> signals unchanged
    #   Custom cost 0.2%:    0.002  * 125.6 / 0.07 = 3.589 >  3.2148 (and growing with price) -> every signal blocked
    #   Custom 0.2% with smallGuard off, or on a 1h chart: signals back
    #   Custom 0.2% with cgMaxPct = 8: 0.002 * close / 0.08 = 3.14 at bar 250, crossing 3.2148 at close 128.59
    #       -> signals on the even bars 250 .. 254 (close 125.6, 126.6, 127.6), blocked from bar 256 (128.6) on
    only_brk = dict(minScore=0, useTsm=False, useFlip=False, usePb=False)
    evens = list(range(250, 320, 2))
    m15, m60 = mk_market(tf=900), mk_market(tf=3600)
    chart = sawtooth_chart(320, 900)
    sig = lambda mkt, **kw: np.flatnonzero(run_series(E, chart, mkt, **only_brk, **kw)[1]["longSig"]).tolist()  # noqa: E731
    assert sig(m15) == evens
    assert sig(m15, costMode="Custom", costCustom=0.2) == []
    assert sig(m15, costMode="Custom", costCustom=0.2, smallGuard=False) == evens
    assert sig(m60, costMode="Custom", costCustom=0.2) == evens
    assert sig(m15, costMode="Custom", costCustom=0.2, cgMaxPct=8.0) == [250, 252, 254]
    # short side (cgOkS, L200) on the mirrored chart: close = 374.4 on bar 250
    #   Auto 0.03%: 0.0003 * 374.4 / 0.07 = 1.60 <= 3.2148 -> signals ; Custom 0.2%: 10.7 > 3.2148 -> blocked
    mir = mirrored(chart)
    sig_s = lambda mkt, **kw: np.flatnonzero(run_series(E, mir, mkt, **only_brk, **kw)[1]["shortSig"]).tolist()  # noqa: E731
    assert sig_s(m15) == evens
    assert sig_s(m15, costMode="Custom", costCustom=0.2) == []
    assert sig_s(m15, costMode="Custom", costCustom=0.2, smallGuard=False) == evens
    assert sig_s(m60, costMode="Custom", costCustom=0.2) == evens
    # the cost itself is still charged when the guard is off: cR = 0.2/100 * 125.6 / risk
    res, _ = run_series(E, chart, m15, **only_brk, costMode="Custom", costCustom=0.2, smallGuard=False)
    assert abs(res["trades"][0]["cost_R"] - 0.002 * 125.6 / RISK) < 1e-6


def _htf_trend_per_bar(E, htf, ema_len):
    if E is A:
        return np.asarray(A.htfTrendCalc(htf, ema_len), dtype=float)
    return np.asarray(B._htf_trend_calc(f64(htf["h"]), f64(htf["l"]), f64(htf["c"]), ema_len), dtype=float)


@check("run")
def htf_alignment_and_ema_length(E):
    # 60 higher-timeframe bars one "day" (86400 s) apart: closes rise 1 per bar for 40 bars (100 .. 139), then
    # fall 3 per bar (136 .. 79).  open = previous close, high / low = 0.5 beyond open / close.
    #   rising leg: tr = 2 -> atr(10) ~ 2 ; the first upper band (bar 9: 108.5 + 3*1.9 = 114.2) is crossed by the
    #   close on bar 15 -> SuperTrend up ; EMA21 exists from bar 20 (SMA of 100..120 = 110 < close 120)
    #       -> htfTrendCalc(21) = +1 on bars 20 .. 39 ; with EMA50 the EMA is na before bar 49 -> 0 there
    #   falling leg: the close drops under the lower band and the EMA within a few bars -> -1 by bar 45 at the
    #   latest, for EMA21 and (from bar 49: SMA50 = 120.1 > close 109) for EMA50 as well.
    D = 86400
    closes = [100.0 + d for d in range(40)] + [139.0 - 3.0 * (d - 39) for d in range(40, 60)]
    rows = []
    for d, c in enumerate(closes):
        o = closes[d - 1] if d else c
        rows.append((o, max(o, c) + 0.5, min(o, c) - 0.5, c))
    a = np.array(rows)
    htf = {"t": np.arange(60, dtype=np.int64) * D, "o": a[:, 0].copy(), "h": a[:, 1].copy(), "l": a[:, 2].copy(),
           "c": a[:, 3].copy(), "v": np.zeros(60)}
    # chart: six bars per HTF bar (t = d*D + k*14400), prices irrelevant for the alignment
    chart = sawtooth_chart(360, 14400)
    day = (chart["t"] // D).tolist()

    t21 = _htf_trend_per_bar(E, htf, 21)
    t50 = _htf_trend_per_bar(E, htf, 50)
    assert t21[:20].tolist() == [0.0] * 20 and t21[20:40].tolist() == [1.0] * 20, t21.tolist()
    assert t21[45:].tolist() == [-1.0] * 15, t21.tolist()
    # the turn, bar by bar (EMA21: 129.636, 129.942, 129.947, 129.679 ; lower band stays 132.51):
    #   40: close 136 above band and EMA -> +1 ; 41: close 133 -> +1 ; 42: close 130 < band -> SuperTrend down, but
    #   close 130 > EMA 129.947 -> neither condition of L126 -> 0 ; 43: close 127 < EMA and down -> -1
    assert t21[40:45].tolist() == [1.0, 1.0, 0.0, -1.0, -1.0], t21[40:45].tolist()
    assert t50[:49].tolist() == [0.0] * 49 and t50[49:].tolist() == [-1.0] * 11, t50.tolist()

    # A second series for the remaining branch of L126: 40 rising bars, then a slow fade of 0.2 per bar
    # (open = previous close, high = open + 0.5, low = close - 0.5 -> tr 1.2).
    #   c - ema21 = L follows L_n = (10/11) * (L_{n-1} - 0.2), L_0 = 10 (bar 39) -> L_n = -2 + 12 * (10/11)^n:
    #   +0.158 on bar 57 (n = 18), -0.038 on bar 58 (n = 19).  The lower band (132.51 on bar 39, at most 133.17
    #   afterwards) stays below every close (>= 134.0) -> SuperTrend remains up.
    #   -> +1 on bars 20 .. 57 ; from bar 58 on close < ema but direction < 0 -> 0, not -1.
    fade_c = [100.0 + d for d in range(40)] + [139.0 - 0.2 * (d - 39) for d in range(40, 65)]
    fr = []
    for d, c in enumerate(fade_c):
        o = fade_c[d - 1] if d else c
        fr.append((o, max(o, c) + 0.5, min(o, c) - 0.5, c))
    fa = np.array(fr)
    fade = {"t": np.arange(65, dtype=np.int64) * D, "o": fa[:, 0].copy(), "h": fa[:, 1].copy(),
            "l": fa[:, 2].copy(), "c": fa[:, 3].copy(), "v": np.zeros(65)}
    tf21 = _htf_trend_per_bar(E, fade, 21)
    assert tf21.tolist() == [0.0] * 20 + [1.0] * 38 + [0.0] * 7, tf21.tolist()

    def series(tf, htf_s):
        res = E.run(chart, htf, E.Params(), mk_market(tf=tf, htf=htf_s))
        return res["series"]["htfTrend"]

    def check_alignment(got, trend):
        # request.security(..., expr[1], lookahead_on): every chart bar inside HTF bar d shows the value of HTF
        # bar d-1 - from the FIRST chart bar of d on, and never the value of d itself ; na inside HTF bar 0.
        for i in range(360):
            d = day[i]
            if d == 0:
                assert got[i] != got[i], (i, got[i])
            else:
                assert got[i] == trend[d - 1], (i, d, got[i], trend[d - 1])

    # 4h chart, daily HTF: Auto rule L134 -> htf >= 1D -> EMA 21
    g = series(14400, D)
    check_alignment(g, t21)
    assert g[6 * 20] == 0.0 and g[6 * 21] == 1.0 and g[6 * 21 - 1] == 0.0     # bar 20's +1 appears on day 21, bar 0
    # daily chart, weekly HTF (pretend the same bars are weeks): still EMA 21
    check_alignment(series(D, 604800), t21)
    # 1h / 15m chart, 4h HTF: htf < 1D -> EMA 50 (pretend the same bars are 4h bars)
    g = series(3600, 14400)
    check_alignment(g, t50)
    assert g[6 * 26] == 0.0 and g[6 * 51] == -1.0
    check_alignment(series(900, 14400), t50)
    # 5m chart, 1h HTF -> EMA 50
    check_alignment(series(300, 3600), t50)


# ───────────────────────────── runner ─────────────────────────────
def main(argv) -> int:
    verbose = "-v" in argv
    filters = [a for a in argv if not a.startswith("-")]
    failed = 0
    counts: dict = {}
    for section, name, fn in CHECKS:
        if filters and not any(f in name for f in filters):
            continue
        errs = []
        for ename, E in ENGINES:
            try:
                fn(E)
            except Exception as exc:  # noqa: BLE001 - report every failure, keep going
                tb = traceback.format_exc() if verbose or not isinstance(exc, AssertionError) else ""
                errs.append(f"      {ename}: {type(exc).__name__}: {exc}\n{tb}".rstrip())
        ok, bad = counts.get(section, (0, 0))
        counts[section] = (ok + (not errs), bad + bool(errs))
        if errs:
            failed += 1
            print(f"FAIL  [{section}] {name}")
            print("\n".join(errs))
        else:
            print(f"ok    [{section}] {name}")
    total = sum(a + b for a, b in counts.values())
    parts = ", ".join(f"{sec} {a}/{a + b}" for sec, (a, b) in counts.items())
    print(f"\ntest_scenarios: {total - failed}/{total} checks passed in both engines ({parts})"
          f" -> {'PASS' if failed == 0 else 'FAIL'}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
