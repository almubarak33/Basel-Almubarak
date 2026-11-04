# trader/

Working folder for the trader skills. Each skill reads what the last one wrote.

| file | written by | read by |
| --- | --- | --- |
| config.json | you | every skill (budget, limits, sec_user_agent) |
| targets.json | trader-copycat | trader-budget, trader-rebalance |
| orders.json | trader-budget / trader-rebalance / trader-tax | trader-risk, trader-broker |
| prices.json | trader-alerts | trader-budget, trader-risk, trader-tax, trader-rebalance |
| metrics.json | trader-analyst | trader-screener |
| portfolio.json | trader-broker (fills) | trader-tax, trader-rebalance, trader-news |

Before first use: put your real name and email in `sec_user_agent` in config.json.
SEC EDGAR refuses requests without it. Broker API keys go in environment
variables, never in this folder.
