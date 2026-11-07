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
| `v2_lab.py`, `v2_run1-4.py`, `v3_mr.py`, `v3_maxwin.py` | v2 research: pullback limit entry, Asian-range sweep / London breakout, candle & range filters, volatility floor, RSI(2) pullback, Max Win-Rate profile |
| `final_config_v2.py` | **shipped defaults (v2.1)**: execution pack below 1H + Max Win-Rate; v1 execution + High Win-Rate on 1H+ |
| `validate_final.py` | definitive tables for the shipped defaults → `results/validation_final.csv`, monthly, per setup, trade lists |
| `htf_align_check.py` | sensitivity to the 4H bar anchor (17:00 vs 18:00 New York) |

```bash
pip install pandas numpy
python3 validate_final.py  # shipped defaults (v2.1), 5m / 15m / 1h
python3 validate.py        # v1 results table
python3 report_tables.py   # supplementary tables
```

Simulation rules: entry at the signal bar close, management from the next bar, opening gaps through the
stop fill at the open, stop-first when a bar touches stop and target, round-trip cost (default 0.03 %)
subtracted from every trade. Results are an OHLC simulation, not broker fills.
