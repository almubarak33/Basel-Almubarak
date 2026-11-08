# CLAUDE.md

This repo is a library of project-local Claude Code skills plus one trading bot.
There is no app to build and no test suite.

## Layout

- `.claude/skills/trader-*`: 11 day-trading skills (US stocks, long only). Each is a `SKILL.md` plus one stdlib-only Python script, run as `python3 "${CLAUDE_SKILL_DIR}/<script>.py"`.
- `.claude/skills/replica-*`: 11 skills for cloning an app, from recon to deploy.
- `replica/`: output of `replica-entrepreneur` for TikTok (reviews, themes, fix plan).
- `pro-scalping-bot/`: a Binance USDT-M futures bot (ccxt, pandas). Deployed on Railway (`railway.json`, `Procfile`). Settings live in `config.yaml` and can be overridden by environment variables.

## Trader pipeline (run in this order)

Each step reads the previous step's file under `trader/` (git-ignored runtime state):

1. `trader-scanner` writes `trader/watchlist.json`
2. `trader-news` checks headlines and 8-Ks for the watchlist
3. `trader-entry` writes `trader/entry.json` when a setup triggers
4. `trader-exit` writes `trader/plan.json` (stop and target)
5. `trader-timemachine` simulates the plan
6. `trader-budget` sizes it and writes `trader/orders.json` (config in `trader/config.json`)
7. `trader-risk` gives PASS or BLOCK. **Always run it before the broker.**
8. `trader-broker` places the order. Paper trading by default, and only after an explicit yes.

`trader-alerts` (writes `trader/prices.json`), `trader-analyst` and `trader-pelosi` are side tools.

## Replica pipeline

recon → architect → design → build → backend → test → diff → entrepreneur → brand → launch → deploy

## Rules

- Never place a live (non-paper) order or switch the bot off testnet/paper without the user's explicit request in that message.
- Never write API keys into files. Read `BINANCE_API_KEY`, `BINANCE_API_SECRET`, `ALPACA_*` from environment variables. A PreToolUse hook (`.claude/hooks/protect_secrets.py`) blocks `.env` edits and literal keys.
- Don't raise `leverage`, `risk_pct` or `max_daily_loss` in `pro-scalping-bot/config.yaml` unless asked.
- Keep skill scripts stdlib-only. Check edits with `python3 -m py_compile <file>`.
