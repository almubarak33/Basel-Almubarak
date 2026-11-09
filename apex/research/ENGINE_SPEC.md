# APEX research engine — port specification

Goal: a Python port of the TradingView indicator `apex/APEX_Focus_original.pine` that reproduces, bar for bar,
the script's **signals**, **internal trade simulation** and **Stats** object. The Pine file is the single source of
truth; this document only fixes the interface and the semantics of Pine built-ins that the port must imitate.

## 1. Execution model

* Historical bars only: the script body runs once per bar at the bar's close, `barstate.isconfirmed` is true on
  every bar, `barstate.islast` drawing code is irrelevant. Ignore every drawing/label/plot/alert side effect.
* `bar_index` starts at 0 on the first row of the chart dataset.
* `na` semantics (Pine v6): arithmetic with `na` gives `na`; **any comparison with `na` is false**; `math.sign(na)`
  is `na`; `nz(x)` is 0 for `na`; `x[n]` is `na` when fewer than n previous bars exist.
* `and` / `or` short-circuit (v6), so `not na(cur) and cur.x` never touches a missing object.

## 2. Pine built-ins (reference implementations to imitate exactly)

```
ta.tr(true)      = na(high[1]) ? high - low : max(high - low, abs(high - close[1]), abs(low - close[1]))
ta.rma(src, n)   : alpha = 1/n ; first value = SMA(src, n) on the first bar where n non-na values exist (na before);
                   then rma = alpha*src + (1-alpha)*rma[1]
ta.ema(src, n)   : alpha = 2/(n+1); first value = SMA(src, n) on the first bar where n values exist (na before);
                   then ema = alpha*src + (1-alpha)*ema[1]
ta.atr(n)        = ta.rma(ta.tr(true), n)
ta.highest(s, n) / ta.lowest(s, n): window of the last n bars INCLUDING the current one; na until n values exist
ta.rsi(src, n)   : u = max(change(src),0), d = max(-change(src),0); rs = rma(u,n)/rma(d,n);
                   rsi = rma(d)==0 ? 100 : rma(u)==0 ? 0 : 100 - 100/(1+rs)
ta.dmi(len, sm)  : up = change(high); down = -change(low)
                   plusDM  = na(up)   ? na : (up > down and up > 0 ? up : 0)
                   minusDM = na(down) ? na : (down > up and down > 0 ? down : 0)
                   trur  = rma(ta.tr(false) , len)        // note: ta.tr(false) is na on the first bar
                   plus  = fixnan(100 * rma(plusDM, len) / trur)
                   minus = fixnan(100 * rma(minusDM, len) / trur)
                   sum   = plus + minus
                   adx   = 100 * rma(abs(plus - minus) / (sum == 0 ? 1 : sum), sm)
                   returns [plus, minus, adx]
ta.supertrend(factor, atrPeriod):
                   src = hl2 ; atr = ta.atr(atrPeriod)
                   upperBand = src + factor*atr ; lowerBand = src - factor*atr
                   prevLowerBand = nz(lowerBand[1]) ; prevUpperBand = nz(upperBand[1])
                   lowerBand := lowerBand > prevLowerBand or close[1] < prevLowerBand ? lowerBand : prevLowerBand
                   upperBand := upperBand < prevUpperBand or close[1] > prevUpperBand ? upperBand : prevUpperBand
                   if na(atr[1])                              direction := 1
                   else if prevSuperTrend == prevUpperBand    direction := close > upperBand ? -1 : 1
                   else                                       direction := close < lowerBand ? 1 : -1
                   superTrend := direction == -1 ? lowerBand : upperBand
                   returns [superTrend, direction]            // direction < 0 means UP-trend
```

`[lowerBand[1], upperBand[1], prevSuperTrend]` refer to the FINAL (already adjusted) values of the previous bar.

## 3. Higher-timeframe trend (`request.security(..., htfTrendCalc(len)[1], lookahead = barmerge.lookahead_on)`)

* `htfTrendCalc(len)` is evaluated on the higher-timeframe (HTF) bars: SuperTrend(3.0, 10) direction `d` and
  `e = EMA(close, len)`; result `0` if `e` or `d` is na, `+1` if `close > e and d < 0`, `-1` if `close < e and d > 0`, else `0`.
* With `[1]` + `lookahead_on` every chart bar receives the value computed on the HTF bar **before** the HTF bar that
  contains the chart bar: `j = searchsorted(htf_t, chart_t, side="right") - 1` is the containing HTF bar, the value
  is `trend[j-1]` (`na` when `j-1 < 0`, and a `na` trend never equals +1/-1).
* EMA length (script's Auto mode): `21` when the HTF is one day or longer (`htf_seconds >= 86400`), otherwise `50`.
* If the HTF is not longer than the chart timeframe the script uses the chart timeframe itself (previous chart bar).

## 4. Public interface (identical in every port)

```python
from dataclasses import dataclass

@dataclass
class Params:                      # defaults == the Pine input defaults
    useBrk: bool = True;  donLen: int = 20
    useFlip: bool = True; stFactor: float = 3.0; stLen: int = 10
    usePb: bool = True
    minScore: int = 7;    adxMin: float = 25.0;  useTsm: bool = True
    dirMode: str = "Both"          # "Both" | "Long only" | "Short only"
    profile: str = "AUTO"          # "AUTO" | "HP" | "BAL" | "RUN" | "CUS"
    swingLook: int = 10;  slBuf: float = 0.25;   slMinAtr: float = 0.8;  slMaxAtr: float = 3.5
    cTp1: float = 1.0;    cW1: float = 40.0;     cTp2: float = 2.0;      cW2: float = 30.0;  cTp3: float = 3.0
    cTrail: bool = False; cBe: bool = True
    chLen: int = 22;      chMult: float = 3.0
    smallGuard: bool = True; cgMaxPct: float = 7.0
    costMode: str = "Auto"; costCustom: float = 0.05

def run(chart: dict, htf: dict, params: Params, market) -> dict: ...
```

* `chart`, `htf`: dicts of numpy arrays `t, o, h, l, c, v` (see `datasets.py`; `t` = bar open, unix seconds UTC).
* `market`: `datasets.Market` (fields `ticker`, `sym_type`, `tf_seconds`, `htf_seconds`, `mintick`).
  `syminfo.type == "crypto"` ⇔ `market.sym_type == "crypto"`; `syminfo.pointvalue` is not needed.
* Return value:

```python
{
  "trades": [ {                     # CLOSED trades only, in closing order
      "dir": 1 | -1, "entry_bar": int, "exit_bar": int, "trig": "BRK"|"FLIP"|"PB", "score": int,
      "entry": float, "sl0": float, "risk": float, "tp1": float, "tp2": float, "tp3": float | None,
      "hit1": bool, "hit2": bool, "hit3": bool,
      "exit_px": float,             # the px passed to closeTrade
      "reason": str,                # the reason passed to closeTrade: "SL","Remaining SL","BE/Trail","TP","TP3","Reverse"
      "gross_R": float,             # t.realized after closeTrade
      "cost_R": float, "R": float   # R = gross_R - cost_R (what closeTrade returns)
  }, ... ],
  "open_trade": None | {...same keys without exit fields...},   # trade still open after the last bar
  "stats": {"n","tp1","tp2","tp3","fullSl","win","gross","loss","net","peak","maxDd","costR","nL","netL","nS","netS"},
  "series": {"scoreL": int array, "scoreS": int array, "longSig": bool array, "shortSig": bool array,
             "atr": float array, "htfTrend": float array (nan for na)}
}
```

`stats` mirrors the Pine `Stats` object field for field after the last bar.

## 5. Things that are easy to get wrong

* The management block (`// 1)`) runs **before** the new-signal block (`// 2)`) on every bar, and only for
  `bar_index > cur.entryBar`. A trade stopped on a bar can be replaced by a new signal on the same bar.
* Order inside the management block is exactly the Pine order: trail update from the PREVIOUS bar's chandelier →
  opening-stop check → opening target fills → trail update again → range stop check (stop first) → range targets.
* Targets hit by the bar's range do not re-check the (possibly moved) stop on the same bar.
* The trail only ever tightens (`max` for longs, `min` for shorts) and only after `hit1` (or `hit2` for Trend Runner).
* `closeTrade` adds the remaining open weight at `px`, subtracts the cost in R and updates every Stats field.
* A long signal while a long trade is open is ignored; an opposite signal closes at `close` with reason "Reverse"
  and opens the new trade on the same bar.
* `trigName` precedence: BRK, then FLIP, then PB (and it is the name even if that trigger's toggle logic differs).
* Profile "AUTO": crypto → Trend Runner, everything else → High-Probability.

## 6. Low-level trade simulator (must also be public — used by hand-built scenario tests)

```python
def simulate(o, h, l, c,                 # float arrays, one row per bar
             longSig, shortSig,          # bool arrays: the script's longSig / shortSig on each bar
             slDistL, slDistS,           # float arrays: stop distance used if a trade opens on that bar
             chandL, chandS,             # float arrays: chandelier values (nan = na)
             mgmt: dict,                 # {"k1","k2","k3","w1","w2","trailOn": bool,"trailFrom": 1|2,"beOn": bool}
             costPct: float,             # round-trip cost in PERCENT of price (e.g. 0.03)
             mintick: float = 0.01,
             trigL=None, trigS=None,     # optional arrays of trigger names ("BRK"/"FLIP"/"PB"); default "BRK"
             scoreL=None, scoreS=None    # optional int arrays; default 7
             ) -> dict:                  # {"trades": [...], "open_trade": ..., "stats": {...}} exactly as in §4
```

`run()` must be a thin wrapper: compute the per-bar series from the chart/HTF data, then call `simulate`.
The simulator contains the whole `// 1)` management block, the `// 2)` new-signal block, `openTrade`,
`closeTrade`, `activeStopReason` and the Stats bookkeeping — nothing else.
