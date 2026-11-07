# APEX Fusion — research & backtest

Python mirror of `indicators/APEX_Fusion_Pro.pine`, used to design and test the indicator on gold.

| file | purpose |
|---|---|
| `fetch_data.py` | downloads the datasets in `data/` (Binance public archive: XAUUSDT, XAGUSDT, PAXGUSDT; Yahoo: GC=F) |
| `engine.py` | Pine `ta.*` replicas, all setups from APEX + GBB, the trade simulator, statistics |
| `baseline.py` | the two original indicators with their own defaults |
| `research_is.py`, `analyze_is.py`, `excursion.py`, `experiments.py`, `hours.py`, `grid*.py`, `exp_mid.py` | in-sample design research (PAXG 2022–Jun 2025, XAUUSDT Dec 2025–May 2026) |
| `final_config.py` | the frozen Fusion configuration |
| `validate.py` | out-of-sample, cross-timeframe and cross-asset validation → `results/validation.csv` |
| `report_tables.py` | cost sensitivity, monthly, per-setup, 4H tables → `results/` |

```bash
pip install pandas numpy
python3 validate.py        # main results table
python3 report_tables.py   # supplementary tables
```

Simulation rules: entry at the signal bar close, management from the next bar, opening gaps through the
stop fill at the open, stop-first when a bar touches stop and target, round-trip cost (default 0.03 %)
subtracted from every trade. Results are an OHLC simulation, not broker fills.
