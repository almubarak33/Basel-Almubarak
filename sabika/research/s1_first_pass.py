"""First-pass test of candidate strategy S1 (pre-New-York session range breakout).

Implements exactly the rule, costs, null model and verdict rules fixed in
prereg_S1_first_pass.json (committed before this file).

Usage: python3 s1_first_pass.py <XAU klines folder> <XAG klines folder> <output json>
Each folder holds Binance monthly 1-minute kline zips (XAUUSDT-1m-YYYY-MM.zip / XAGUSDT-...).
"""
import sys, os, glob, zipfile, json, datetime as dt
from zoneinfo import ZoneInfo
import numpy as np

NY = ZoneInfo("America/New_York")
COSTS = {"XAU": dict(spread=0.30, slip_e=0.10, slip_x=0.10),
         "XAG": dict(spread=0.03, slip_e=0.01, slip_x=0.01)}
TP_CELLS = [1.0, 1.5, 2.0]          # primary cell first
RANGE_START, RANGE_END = 180, 480   # 03:00 .. 08:00 New York, minutes of day
TRIG_FIRST_OPEN, TRIG_LAST_OPEN = 480, 645   # M15 bars opening 08:00 .. 10:45
TIME_EXIT = 945                     # 15:45 New York
MIN_RANGE_BARS = 270
BUFFER_W = 0.10
GATE_LO, GATE_HI = 0.15, 0.70
ATR_N = 14
NULL_SEEDS = 1000


def load(folder, prefix):
    rows = []
    for f in sorted(glob.glob(os.path.join(folder, prefix + "-1m-*.zip"))):
        with zipfile.ZipFile(f) as z:
            txt = z.read(z.namelist()[0]).decode()
        for line in txt.splitlines():
            p = line.split(",")
            if not p[0].isdigit():
                continue
            rows.append((int(p[0]), float(p[1]), float(p[2]), float(p[3]), float(p[4])))
    a = np.array(rows, dtype=np.float64)
    t = a[:, 0].astype(np.int64) // 1000
    if t.max() > 4e10:
        t = t // 1000
    order = np.argsort(t)
    return t[order], a[order, 1], a[order, 2], a[order, 3], a[order, 4]


def market_open_mask(t):
    wd = ((t // 86400) + 3) % 7          # 0 = Monday
    hr = (t % 86400) // 3600
    closed = ((wd == 4) & (hr >= 22)) | (wd == 5) | ((wd == 6) & (hr < 23))
    return ~closed


def ny_fields(t):
    """New York calendar date (ordinal), minute of day and weekday for every bar."""
    # compute the UTC offset once per UTC hour bucket (offsets only change on DST days)
    hours = np.unique(t // 3600)
    off = {}
    for h in hours:
        d = dt.datetime.fromtimestamp(int(h) * 3600, dt.timezone.utc).astimezone(NY)
        off[int(h)] = int(d.utcoffset().total_seconds())
    offs = np.array([off[int(h)] for h in (t // 3600)], dtype=np.int64)
    loc = t + offs
    day = loc // 86400                    # days since epoch in NY local time
    minute = (loc % 86400) // 60
    wd = (day + 3) % 7                    # 0 = Monday
    return day, minute, wd, loc


def simulate(direction, e, x_end, O, H, L, stop_price, tp_mult, c):
    """Return (result in R, exit kind, R size in price, bars held). x_end = index of the time-exit bar."""
    s, slip_e, slip_x = c["spread"], c["slip_e"], c["slip_x"]
    if direction > 0:
        fill = O[e] + s / 2 + slip_e
        R = fill - stop_price
        if R <= 0:
            return None
        target = fill + tp_mult * R
        for j in range(e, x_end):
            if L[j] - s / 2 <= stop_price:                  # stop first (pessimistic)
                return (-(R + slip_x) / R, "stop", R, j - e + 1)
            if H[j] - s / 2 >= target:
                return (tp_mult, "target", R, j - e + 1)
        px = O[x_end] - s / 2
        return ((px - fill) / R, "time", R, x_end - e)
    else:
        fill = O[e] - s / 2 - slip_e
        R = stop_price - fill
        if R <= 0:
            return None
        target = fill - tp_mult * R
        for j in range(e, x_end):
            if H[j] + s / 2 >= stop_price:
                return (-(R + slip_x) / R, "stop", R, j - e + 1)
            if L[j] + s / 2 <= target:
                return (tp_mult, "target", R, j - e + 1)
        px = O[x_end] + s / 2
        return ((fill - px) / R, "time", R, x_end - e)


def run_symbol(sym, folder, prefix):
    c = COSTS[sym]
    t, O, H, L, C = load(folder, prefix)
    m = market_open_mask(t)
    t, O, H, L, C = t[m], O[m], H[m], L[m], C[m]
    day, minute, wd, loc = ny_fields(t)

    # New-York-close daily sessions (17:00 boundary): session id = NY day of (local time + 7h)
    sess = (loc + 7 * 3600) // 86400
    sess_ids = np.unique(sess)
    s_hi, s_lo, s_cl = {}, {}, {}
    for sid in sess_ids:
        ix = np.nonzero(sess == sid)[0]
        s_hi[sid], s_lo[sid], s_cl[sid] = H[ix].max(), L[ix].min(), C[ix[-1]]
    tr = {}
    prev = None
    for sid in sess_ids:
        if prev is not None:
            tr[sid] = max(s_hi[sid] - s_lo[sid], abs(s_hi[sid] - s_cl[prev]), abs(s_lo[sid] - s_cl[prev]))
        prev = sid

    days = np.unique(day)
    stats = dict(days_total=0, void_missing_bars=0, void_no_atr=0, gate_too_narrow=0, gate_too_wide=0,
                 gate_spread=0, no_trigger=0, no_exit_bar=0, signals=0)
    trades = []
    for d in days:
        ix_day = np.nonzero(day == d)[0]
        if wd[ix_day[0]] > 4:
            continue
        stats["days_total"] += 1
        mins = minute[ix_day]
        rg = ix_day[(mins >= RANGE_START) & (mins < RANGE_END)]
        if len(rg) < MIN_RANGE_BARS:
            stats["void_missing_bars"] += 1
            continue
        # ATR from the last ATR_N completed sessions; the session that contains 08:00 of day d has id d
        done = [sid for sid in sess_ids if sid < d and sid in tr]
        if len(done) < ATR_N:
            stats["void_no_atr"] += 1
            continue
        atr = float(np.mean([tr[sid] for sid in done[-ATR_N:]]))
        r_hi, r_lo = H[rg].max(), L[rg].min()
        W = r_hi - r_lo
        ratio = W / atr
        if ratio < GATE_LO:
            stats["gate_too_narrow"] += 1
            continue
        if ratio > GATE_HI:
            stats["gate_too_wide"] += 1
            continue
        if W < 10 * c["spread"]:
            stats["gate_spread"] += 1
            continue
        # time-exit bar: first bar of the day at or after 15:45
        late = ix_day[mins >= TIME_EXIT]
        direction, entry = 0, None
        for m0 in range(TRIG_FIRST_OPEN, TRIG_LAST_OPEN + 1, 15):
            b = ix_day[(mins >= m0) & (mins < m0 + 15)]
            if len(b) < 10:
                continue
            cl = C[b[-1]]
            if cl > r_hi + BUFFER_W * W:
                direction = 1
            elif cl < r_lo - BUFFER_W * W:
                direction = -1
            if direction != 0:
                nxt = ix_day[mins >= m0 + 15]
                if len(nxt) > 0:
                    entry = int(nxt[0])
                break
        if direction == 0 or entry is None:
            stats["no_trigger"] += 1
            continue
        if len(late) == 0 or int(late[0]) <= entry:
            stats["no_exit_bar"] += 1
            continue
        x_end = int(late[0])
        mid = (r_hi + r_lo) / 2.0
        d0 = abs(O[entry] - mid)                       # same stop distance for both sides (null model)
        stats["signals"] += 1
        rec = dict(date=str(dt.date(1970, 1, 1) + dt.timedelta(days=int(d))), dir=direction,
                   entry_minute=int(minute[entry]), W=float(W), atr=atr, ratio=float(ratio), price=float(O[entry]))
        ok = True
        for tp in TP_CELLS:
            rl = simulate(+1, entry, x_end, O, H, L, O[entry] - d0, tp, c)
            rs = simulate(-1, entry, x_end, O, H, L, O[entry] + d0, tp, c)
            if rl is None or rs is None:
                ok = False
                break
            rec["tp%.1f" % tp] = dict(long=rl, short=rs)
        if ok:
            trades.append(rec)

    out = dict(symbol=sym, bars=int(len(t)), first=str(dt.datetime.fromtimestamp(int(t[0]), dt.timezone.utc)),
               last=str(dt.datetime.fromtimestamp(int(t[-1]), dt.timezone.utc)), day_stats=stats, cells={})
    for tp in TP_CELLS:
        key = "tp%.1f" % tp
        act = np.array([(r[key]["long"] if r["dir"] > 0 else r[key]["short"])[0] for r in trades])
        kinds = [(r[key]["long"] if r["dir"] > 0 else r[key]["short"])[1] for r in trades]
        rsize = np.array([(r[key]["long"] if r["dir"] > 0 else r[key]["short"])[2] for r in trades])
        held = np.array([(r[key]["long"] if r["dir"] > 0 else r[key]["short"])[3] for r in trades])
        dirs = np.array([r["dir"] for r in trades])
        both = np.array([[r[key]["long"][0], r[key]["short"][0]] for r in trades])
        n = len(act)
        cell = dict(trades=n)
        if n > 0:
            rng = np.random.default_rng(20261114)
            picks = rng.integers(0, 2, size=(NULL_SEEDS, n))
            null_means = both[np.arange(n)[None, :], picks].mean(axis=1)
            mean_r = float(act.mean())
            months = {}
            for r, a in zip(trades, act):
                k = r["date"][:7]
                mm = months.setdefault(k, dict(trades=0, sum_R=0.0))
                mm["trades"] += 1
                mm["sum_R"] = round(mm["sum_R"] + float(a), 3)
            cell.update(
                mean_R=round(mean_r, 4), median_R=round(float(np.median(act)), 4), total_R=round(float(act.sum()), 2),
                std_R=round(float(act.std(ddof=1)), 4) if n > 1 else None,
                t_stat=round(mean_r / (float(act.std(ddof=1)) / np.sqrt(n)), 2) if n > 1 else None,
                win_rate=round(float((act > 0).mean()), 4), breakeven_win_rate_no_cost=round(1.0 / (1.0 + tp), 4),
                exits={k: kinds.count(k) for k in ("target", "stop", "time")},
                long=dict(n=int((dirs > 0).sum()), mean_R=round(float(act[dirs > 0].mean()), 4) if (dirs > 0).any() else None),
                short=dict(n=int((dirs < 0).sum()), mean_R=round(float(act[dirs < 0].mean()), 4) if (dirs < 0).any() else None),
                null=dict(p05=round(float(np.percentile(null_means, 5)), 4), p50=round(float(np.percentile(null_means, 50)), 4),
                          p95=round(float(np.percentile(null_means, 95)), 4),
                          actual_percentile=round(float((null_means < mean_r).mean() * 100), 1)),
                median_R_size_price=round(float(np.median(rsize)), 3),
                median_R_size_pct_of_price=round(float(np.median(rsize / np.array([r["price"] for r in trades])) * 100), 3),
                median_minutes_held=float(np.median(held)), months=months)
        out["cells"][key] = cell
    return out


def verdict(g):
    c = g["cells"]["tp1.0"]
    if c["trades"] < 60:
        return "INCONCLUSIVE"
    ok = (c["mean_R"] > 0 and c["mean_R"] >= c["null"]["p95"]
          and c["long"]["mean_R"] is not None and c["long"]["mean_R"] >= -0.05
          and c["short"]["mean_R"] is not None and c["short"]["mean_R"] >= -0.05)
    return "PASS" if ok else "FAIL"


if __name__ == "__main__":
    xau = run_symbol("XAU", sys.argv[1], "XAUUSDT")
    xag = run_symbol("XAG", sys.argv[2], "XAGUSDT")
    res = dict(prereg="prereg_S1_first_pass.json", gold=xau, silver=xag, verdict_gold_primary_cell=verdict(xau))
    with open(sys.argv[3], "w") as f:
        json.dump(res, f, indent=1)
    for s in (xau, xag):
        print("=====", s["symbol"], s["bars"], "bars", s["first"], "->", s["last"])
        print("  days:", s["day_stats"])
        for k, c in s["cells"].items():
            if c["trades"] == 0:
                print("  ", k, "no trades")
                continue
            print("  %s: trades %d | mean R %+.3f (t %s) | win %.1f%% (breakeven %.1f%%) | total %+.1f R | exits %s" % (
                k, c["trades"], c["mean_R"], c["t_stat"], 100 * c["win_rate"], 100 * c["breakeven_win_rate_no_cost"], c["total_R"], c["exits"]))
            print("       long n=%d mean %s | short n=%d mean %s | null p05 %+.3f p50 %+.3f p95 %+.3f | actual at %.1f pct" % (
                c["long"]["n"], c["long"]["mean_R"], c["short"]["n"], c["short"]["mean_R"], c["null"]["p05"], c["null"]["p50"], c["null"]["p95"], c["null"]["actual_percentile"]))
            print("       median R size %.3f (%.3f%% of price) | median minutes held %.0f" % (
                c["median_R_size_price"], c["median_R_size_pct_of_price"], c["median_minutes_held"]))
        print("  months (primary cell):", s["cells"]["tp1.0"].get("months"))
    print("VERDICT (gold, primary cell):", res["verdict_gold_primary_cell"])
