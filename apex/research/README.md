# APEX research toolkit

Everything needed to reproduce the numbers in `apex/REPORT.md`: a Python port of the indicator's signal and
trade engine, the market-data fetchers, the test suites and the studies.

## Layout

| File | Purpose |
|---|---|
| `ENGINE_SPEC.md` | Interface and Pine built-in semantics every engine port follows |
| `engine_a.py` | Reference port: pure Python, one statement per Pine statement (the readable oracle) |
| `engine_b.py` / `apex_engine.py` | Fast port of the script as received (numpy + numba) |
| `engine_v2.py` | The same engine plus the v2 simulation rule (`closeStop`) and the intrabar replay (`magnify`) |
| `apex_v2.py` | Maps the v2 inputs (Direction Auto, Shield / Sniper profiles) onto the engine inputs |
| `datasets.py` | CSV loading, market metadata, higher-timeframe selection, data-quality rules |
| `research_lib.py` | Universe, train/test protocol, evaluation helpers (Wilson intervals, profit factor, drawdown) |
| `test_parity.py` | Differential test: both ports must agree on every dataset and parameter set |
| `test_scenarios.py` | Hand-derived micro-scenarios for the trade state machine |
| `test_v2.py` | v2 kernel equals the v1 kernel with the rule off; scenarios for the rule and the replay |
| `test_tv_reference.py` | Indicator maths versus values published by TradingView |
| `study_baseline.py` | The script as received, on the whole universe |
| `study_v2.py` | v1 versus v2, management profiles, the win-rate frontier, gold, 5-minute charts |
| `study_edge.py` | Script signals versus random entries (where the edge comes from) |
| `study_filters.py` | Quintile analysis of 15 candidate entry filters |
| `build_tables.py` | Generates every table of the report into `results/tables.md` |
| `build_report.py` | Fills `report_template.md` with those tables and writes `apex/REPORT.md` |
| `results/` | Raw printed output of the tests and studies behind the report |

## Data

Market data is not stored in the repository (`data/` is git-ignored).

* `tv_ingest.py` converts TradingView MCP `get_ohlcv` results (saved by the Claude Code harness) into CSVs.
  TradingView serves about 4 weeks of 5m, 3 months of 15m, 10 months of 1h, 3-4 years of 4h and decades of 1D.
* `fetch_yahoo.py` adds 60 days of 5m/15m and about 2 years of 1h for futures and FX (second, independent feed).
* `fetch_binance.py` adds deep crypto history (up to 100 000 bars per series) from Binance's public mirror.

```
python3 fetch_yahoo.py && python3 fetch_binance.py     # network required
python3 datasets.py                                    # list what is available
```

## Protocol

Fixed before any tuning (see the docstring of `research_lib.py`):

* one feed per (underlying, timeframe) is primary; the other feed is only a replica check;
* instruments are split into TUNE and HOLDOUT groups; every series is split 60% / 40% in time;
* decisions use TRAIN = TUNE × first 60% only; TEST_TIME (TUNE × last 40%) and TEST_INSTR (HOLDOUT, all
  periods) are reported and never tuned on;
* a trade belongs to the segment that contains its entry bar; win = net R after cost > 0.

## Run

```
pip install numpy numba
python3 test_tv_reference.py && python3 test_scenarios.py && python3 test_v2.py && python3 test_parity.py
python3 study_baseline.py; python3 study_v2.py; python3 study_edge.py; python3 study_filters.py
python3 build_tables.py && python3 build_report.py
```

## How the simulation rules relate

| Rule (`mgmt["closeStop"]`) | Meaning | Used for |
|---|---|---|
| 0 | script as received: a stop raised by a fill inside a bar is not looked at again on that bar | every "original" row |
| 1 | the remainder exits at the raised stop when that bar closes at or through it (the certain case) | every "v2" row; the Pine input `closeStop` |
| 2 | any touch of the raised stop inside that bar counts as a hit (pessimistic bound) | bracketing only |
| replay | rule 1 applied bar by bar on finer data of the same feed | `magnify`, the Pine input `intrabar` |

## Limits of the simulation

* Entries at the signal bar's close, exits from OHLC bars with stop-first ordering inside a bar: this is the
  script's own model, not broker execution. Slippage beyond the fixed round-trip cost is not modelled.
* Costs are the script's Auto values (0.10% crypto, 0.06% silver/platinum/copper, 0.03% otherwise) unless a
  study says otherwise.
* Intraday history is short (5m: 1-2 months outside crypto), so intraday conclusions rest on fewer trades.
* The Pine script itself could not be compiled in this environment; the port is validated against the
  script's source and against TradingView's published indicator values, not against chart output.
