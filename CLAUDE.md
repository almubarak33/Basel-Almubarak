# Sabika — gold/silver trading system

Goal: TradingView indicator alerts → Python bridge on the owner's Windows PC → MetaTrader 5 orders, under hard risk limits.
Demo first (XM, MT5 demo). The real account (Capital.com, MT5) comes later and only when the owner decides in their own words.
The owner writes in Arabic; answer in clear Arabic, decision first, short, no flattery, facts separated from inference.

## Rules that do not bend
- Never place, modify or close an order on a REAL account. Never set `mode = "live"` or `live_armed = true` unless the owner asks for exactly that.
- Every position carries a broker-side stop-loss. No grid, martingale, averaging down, or hidden stops.
- No profitability promises. Report results as measured, including failures. A test whose rules were fixed in advance is judged by those rules.
- Strategy parameters live in the TradingView scripts: changing one is a new experiment that must be re-tested and logged.
  Risk settings (`config.toml`) may be changed freely, inside the hard ceilings enforced in `sabika_bridge/config.py`.
- Do not copy code from the MQL5 Code Base (it carries no licence); re-implement ideas only.
- Never print or commit secrets (webhook secret, account numbers, passwords, tokens).

## Layout
- `sabika/bridge/` — the bridge (stdlib only, Python 3.11+). `python -m unittest discover -s tests` must stay green.
  `engine.py` decides (gates → sizing from loss at the stop → order with SL/TP → journal), `server.py` is the HTTP ingress
  (answers 202 at once, one worker thread), `broker_mt5.py` is the MetaTrader 5 adapter (needs `pip install MetaTrader5`,
  Windows, a running logged-in terminal) and has NOT yet been run against a terminal, `broker_sim.py` is the test broker.
- `sabika/bridge/config.example.toml` — copy to `config.toml` (git-ignored). Start in `mode = "monitor"` (no orders).
- `sabika/mt5/Scripts/Sabika_Probe.mq5` — read-only MQL5 script that reports broker symbol facts (not yet compiled anywhere).
- `sabika/research/` — evidence: Code Base feature catalog, market research, simulations, pre-registered tests and results.

## Signal sources (owner's TradingView account, chart `CAPITALCOM:XAUUSD`, 5 minutes)
- `GOLD V2 BR` = "Basel Gold — Clean Scalp V2 — Bridge Alerts": entry message on the first tick of the entry bar
  (`src: GOLDV2`, entry/sl/tp1..tp3/expire) plus a heartbeat every 5 minutes with ledger counters.
- `APEX SK BR` = "APEX SK Patterns v1 — Bridge Alerts": entry message on the close of the bar that broke level A
  (`src: APEXSK`, entry/ref/sl/tp1..tp4). Its own source header reports an edge close to zero on 5-minute gold.
- Message contract v1 is defined in `sabika_bridge/signals.py`. Webhook URL shape: `https://<public-host>/tv/<secret>`.
- TradingView cancels a webhook after 3 seconds and does not retry; exits therefore never depend on a later message.

## Known results so far
- A pre-registered first-pass test of a pre-New-York range breakout FAILED (`research/s1_first_pass_result.json`); it is not built.
- A burst-cycle "97% win rate" basket bot wipes the account in most runs (`research/cycle_bot_simulation.py`).

## Next steps
1. On the PC: confirm Python, the MetaTrader5 package and the XM demo terminal; read the gold/silver symbol specs (read-only).
2. Run the bridge in `monitor` mode against the XM demo terminal; verify `broker_mt5.py` read calls, then one 0.01-lot demo
   order with SL/TP and its close, then the fault cases (kill and restart with a position open, rejected stop, duplicate signal).
3. Expose `/tv/<secret>` to TradingView (ports 80/443 only) and have the owner create the two alerts with the webhook URL.
4. Demo forward test for weeks; compare alert log, journal and broker history before any talk of a real account.
