"""Historical test of pro-scalping-bot (Binance USDT-M futures, 5m, 30 pairs).

Fidelity to the bot:
- Signals come from the bot's own code (pro-scalping-bot/src/strategy.py + indicators.py), evaluated on
  windows of 150 closed candles exactly like the live loop. Every bar where an EMA9/21 cross is possible
  is evaluated with the real `generate()`; a random sample of other bars is checked to confirm none signal.
- Entry: market order at the next candle's open. Stop and target: the absolute prices from the signal.
  If the fill is already beyond the stop the fixed bot closes at once (loss = costs).
- Exits: first candle (from the entry candle on) that touches the stop or the target; stop first when a
  candle touches both; a gap through the stop fills at the open.
- Costs: taker fee per side (default 0.05%) + slippage per side (default 0.01%) on entry and exit.
- Portfolio: max 5 open trades, one per symbol, 1% of equity at risk (sized from the stop like the fixed
  bot), half size after 3 losses in a row, margin cap (free margin × 10 × 0.9), and a 5% daily loss halt
  on realized PnL (the live bot also counts open losses and closes positions — not simulated here).
R = PnL / planned risk (|signal close − stop|), costs included.

Run: python3 fetch_bot_data.py && python3 bot_backtest.py
"""
import heapq
import json
import math
import sys
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "pro-scalping-bot" / "src"))
from indicators import apply_all  # noqa: E402  (the bot's own code)
from strategy import ProScalpingStrategy  # noqa: E402

DATA = ROOT / "data_bot"
OUT = ROOT / "results"
SYMS = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK", "DOT", "LTC", "UNI", "NEAR", "ARB", "OP",
        "SUI", "APT", "INJ", "TIA", "FIL", "ATOM", "FET", "JUP", "PYTH", "WIF", "PEPE", "SHIB", "TRB", "AAVE", "MKR"]
WINDOW = 150          # config.yaml: limit 150 closed candles
MAX_HOLD = 10_000     # bars (~35 days) before a trade is marked "open at end"


@dataclass(frozen=True)
class Signal:
    sym: str
    i: int            # signal candle index (closed)
    side: int         # +1 long, -1 short
    close: float
    sl: float
    tp: float


def load(sym: str) -> pd.DataFrame:
    return pd.read_csv(DATA / f"{sym}_5m.csv.gz")


def signals_for(sym: str, sample_check: int = 2000, seed: int = 7) -> tuple:
    """Exact bot signals: generate() on each 150-candle window where a cross is possible."""
    df = load(sym)
    strat = ProScalpingStrategy()
    full = apply_all(df)
    diff = (full["ema9"] - full["ema21"]).to_numpy()
    scale = np.maximum(np.abs(full["ema21"].to_numpy()), 1e-12)
    rel = diff / scale
    # candidate bars: a cross on full history, or the two EMAs close enough that a 150-bar window could cross
    cand = np.zeros(len(df), bool)
    cand[1:] = (np.sign(diff[1:]) != np.sign(diff[:-1])) | (np.abs(rel[1:]) < 2e-4) | (np.abs(rel[:-1]) < 2e-4)
    cand[:WINDOW] = False
    idx = np.flatnonzero(cand)
    out = []
    for i in idx:
        sig = strat.generate(df.iloc[i - WINDOW + 1:i + 1])
        if sig:
            d = 1 if sig["signal"] == "long" else -1
            out.append(Signal(sym, int(i), d, float(sig["entry"]), float(sig["sl"]), float(sig["tp"])))
    # fidelity check: random non-candidate bars must not signal
    rng = np.random.default_rng(seed)
    pool = np.flatnonzero(~cand)
    pool = pool[pool >= WINDOW]
    misses = 0
    for i in rng.choice(pool, size=min(sample_check, len(pool)), replace=False):
        if strat.generate(df.iloc[i - WINDOW + 1:i + 1]):
            misses += 1
    return sym, out, len(idx), misses, min(sample_check, len(pool))


def outcome(df: pd.DataFrame, s: Signal, fee: float, slip: float) -> dict:
    """Simulate one signal's trade from the next candle's open."""
    o, h, l, c, ts = (df[k].to_numpy() for k in ("open", "high", "low", "close", "ts_ms"))
    n = len(df)
    j0 = s.i + 1
    if j0 >= n:
        return None
    risk = abs(s.close - s.sl)
    entry = o[j0] * (1 + s.side * slip)
    cost_side = fee
    kind = None
    if (s.side == 1 and entry <= s.sl) or (s.side == -1 and entry >= s.sl):
        exit_px, exit_j, kind = entry, j0, "beyond_stop"
    elif (s.side == 1 and entry >= s.tp) or (s.side == -1 and entry <= s.tp):
        exit_px, exit_j, kind = entry, j0, "beyond_target"
    else:
        exit_px, exit_j = None, None
        for j in range(j0, min(n, j0 + MAX_HOLD)):
            if j > j0 and ((s.side == 1 and o[j] <= s.sl) or (s.side == -1 and o[j] >= s.sl)):
                exit_px, exit_j, kind = o[j], j, "stop_gap"
                break
            hit_sl = l[j] <= s.sl if s.side == 1 else h[j] >= s.sl
            hit_tp = h[j] >= s.tp if s.side == 1 else l[j] <= s.tp
            if hit_sl:
                exit_px, exit_j, kind = s.sl, j, "stop"
                break
            if hit_tp:
                exit_px, exit_j, kind = s.tp, j, "target"
                break
        if exit_px is None:
            exit_j = min(n, j0 + MAX_HOLD) - 1
            exit_px, kind = c[exit_j], "open_at_end"
        if kind in ("stop", "stop_gap"):
            exit_px *= (1 - s.side * slip)     # stop-market fills with slippage
        elif kind == "target":
            exit_px *= (1 - s.side * slip)     # take-profit-market also fills at market
    gross = (exit_px - entry) * s.side
    costs = cost_side * (entry + exit_px)
    return dict(sym=s.sym, side=s.side, signal_ts=int(ts[s.i]), entry_ts=int(ts[j0]), exit_ts=int(ts[exit_j]),
                entry=entry, exit=exit_px, sl=s.sl, tp=s.tp, close=s.close, risk_pct=risk / s.close,
                R=(gross - costs) / risk, R_gross=gross / risk, kind=kind, bars=exit_j - j0 + 1)


def outcomes_for(args) -> list:
    sym, sigs, fee, slip = args
    df = load(sym)
    return [r for r in (outcome(df, s, fee, slip) for s in sigs) if r]


def portfolio(trades: pd.DataFrame, start: float = 10_000.0, risk: float = 0.01, max_pos: int = 5,
              leverage: int = 10, margin_frac: float = 0.9, daily_limit: float = 0.05,
              consec_n: int = 3) -> tuple:
    order = {s: k for k, s in enumerate(SYMS)}
    t = trades.assign(o=trades["sym"].map(order)).sort_values(["entry_ts", "o"]).reset_index(drop=True)
    equity = start
    open_heap = []          # (exit_ts, seq, trade dict with pnl, notional)
    open_syms = set()
    consec = 0
    day, day_start, day_pnl, halted = None, equity, 0.0, False
    taken, skipped_pos, skipped_halt, skipped_margin, halts = [], 0, 0, 0, 0
    curve = []
    seq = 0

    def close_until(ts_):
        nonlocal equity, consec, day_pnl
        while open_heap and open_heap[0][0] <= ts_:
            _, _, tr = heapq.heappop(open_heap)
            equity += tr["pnl"]
            open_syms.discard(tr["sym"])
            consec = 0 if tr["pnl"] > 0 else consec + 1
            if pd.Timestamp(tr["exit_ts"], unit="ms").date() == day:
                day_pnl += tr["pnl"]
            curve.append((tr["exit_ts"], equity))

    for row in t.itertuples(index=False):
        close_until(row.entry_ts)
        d = pd.Timestamp(row.entry_ts, unit="ms").date()
        if d != day:
            day, day_start, day_pnl, halted = d, equity, 0.0, False
        if not halted and day_pnl <= -daily_limit * day_start:
            halted, halts = True, halts + 1
        if halted:
            skipped_halt += 1
            continue
        if row.sym in open_syms:
            continue
        if len(open_syms) >= max_pos:
            skipped_pos += 1
            continue
        r = risk * (0.5 if consec >= consec_n else 1.0)
        qty = equity * r / abs(row.close - row.sl)
        used = sum(tr["notional"] for _, _, tr in open_heap) / leverage
        max_notional = max(0.0, equity - used) * leverage * margin_frac
        if qty * row.entry > max_notional:
            if max_notional <= 0:
                skipped_margin += 1
                continue
            qty = max_notional / row.entry
        pnl = qty * abs(row.close - row.sl) * row.R
        tr = dict(sym=row.sym, exit_ts=row.exit_ts, pnl=pnl, notional=qty * row.entry)
        seq += 1
        heapq.heappush(open_heap, (row.exit_ts, seq, tr))
        open_syms.add(row.sym)
        taken.append(dict(row._asdict(), pnl=pnl, risk_used=qty * abs(row.close - row.sl) / equity))
    close_until(float("inf"))
    info = dict(skipped_max_positions=skipped_pos, skipped_halted=skipped_halt, skipped_margin=skipped_margin,
                halted_days=halts, final_equity=equity)
    return pd.DataFrame(taken), pd.DataFrame(curve, columns=["ts", "equity"]), info


def summary(tr: pd.DataFrame, col: str = "R") -> dict:
    R = tr[col].to_numpy()
    if len(R) == 0:
        return dict(n=0)
    wins, losses = R[R > 0].sum(), -R[R < 0].sum()
    return dict(n=len(R), win=float((R > 0).mean()), avgR=float(R.mean()),
                se=float(R.std(ddof=1) / math.sqrt(len(R))) if len(R) > 1 else float("nan"),
                pf=float(wins / losses) if losses > 0 else float("inf"),
                target=float((tr["kind"] == "target").mean()), stop=float(tr["kind"].isin(["stop", "stop_gap"]).mean()))


if __name__ == "__main__":
    fee, slip = 0.0005, 0.0001
    with ProcessPoolExecutor(4) as ex:
        res = list(ex.map(signals_for, SYMS))
    sigs = {sym: s for sym, s, *_ in res}
    fidelity = {sym: dict(candidates=nc, sample=ns, sample_signals=m) for sym, _, nc, m, ns in res}
    print("signals:", sum(len(v) for v in sigs.values()), "| non-candidate sample signals:",
          sum(v["sample_signals"] for v in fidelity.values()), "of", sum(v["sample"] for v in fidelity.values()))
    rows = {}
    for label, f_, s_ in [("costs 0.05%+0.01%", fee, slip), ("fees only 0.05%", fee, 0.0), ("no costs", 0.0, 0.0)]:
        with ProcessPoolExecutor(4) as ex:
            tr = pd.DataFrame([r for chunk in ex.map(outcomes_for, [(k, v, f_, s_) for k, v in sigs.items()]) for r in chunk])
        rows[label] = tr
    base = rows["costs 0.05%+0.01%"]
    base.to_csv(OUT / "bot_signals_outcomes.csv.gz", index=False, compression="gzip")
    out = {"fidelity": fidelity, "all_signals": {k: summary(v) for k, v in rows.items()}}
    for k, v in out["all_signals"].items():
        print(f"ALL SIGNALS [{k:18s}] " + " ".join(f"{a}={b:.3f}" if isinstance(b, float) else f"{a}={b}" for a, b in v.items()))
    taken, curve, info = portfolio(base)
    eq = curve.set_index(pd.to_datetime(curve["ts"], unit="ms"))["equity"]
    dd = float(((eq.cummax() - eq) / eq.cummax()).max()) if len(eq) else 0.0
    out["portfolio"] = dict(summary(taken), **info, total_return=info["final_equity"] / 10_000 - 1, max_drawdown=dd)
    print("PORTFOLIO", json.dumps(out["portfolio"], default=float))
    taken.to_csv(OUT / "bot_portfolio_trades.csv.gz", index=False, compression="gzip")
    by = lambda g: pd.DataFrame({k: summary(x) for k, x in g}).T
    sym_tab = by(taken.groupby("sym")).sort_values("avgR")
    side_tab = by(taken.groupby("side"))
    taken["month"] = pd.to_datetime(taken["entry_ts"], unit="ms").dt.to_period("M").astype(str)
    month_tab = taken.groupby("month").agg(n=("R", "size"), win=("R", lambda x: (x > 0).mean()), pnl=("pnl", "sum"))
    out["by_side"] = side_tab.to_dict(orient="index")
    out["by_symbol"] = sym_tab.to_dict(orient="index")
    out["by_month"] = month_tab.to_dict(orient="index")
    out["risk_pct_median"] = float(base["risk_pct"].median())
    out["exit_kinds"] = base["kind"].value_counts().to_dict()
    json.dump(out, open(OUT / "bot_backtest.json", "w"), indent=1, default=float)
    pd.set_option("display.width", 200)
    print(side_tab.round(3).to_string()); print(sym_tab.round(3).to_string()); print(month_tab.round(3).to_string())
    print("median stop distance % of price:", round(out["risk_pct_median"] * 100, 3), "| exits:", out["exit_kinds"])
