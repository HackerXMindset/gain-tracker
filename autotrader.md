# AutoTrader – 6-Phase Implementation Plan

## Phase 1 – Design & Config
- Define config flags/env (enable_autotrader, freshness_secs=15, max_retries=10, coin_cap_per_run).
- Add DB schema for autotrader runs, positions, executions, reports, and per-run settings (reuse existing migrations style).
- Extend settings UI: new “AutoTrader” entry point + destination selector (DM or gain-alert chats).

## Phase 2 – Command & UI Flow
- Add “AutoTrader” button (and command) that walks user through: budget, per-coin spend, channels (single/multi/all), start time or “run now/forever,” hold time, coin cap (e.g., next 100), stop rules (end time/target/bankrupt), report interval, breakout/bankrupt thresholds, alert destinations.
- Persist run configuration; show confirmation summary before start.

## Phase 3 – Data & Freshness Layer
- Reuse /invest data stores: poll cache + snapshot MC history; require latest tick ≤15s.
- Implement fetch-with-retry (≥10 attempts, backoff) before declaring “stale” and logging a skip.
- When a coin is already polled for /invest, read the freshest stored tick; otherwise trigger an immediate poll with retries.

## Phase 4 – Trading Engine
- Scheduler loop: prioritize newest coins; enforce per-run coin cap and budget/per-coin spend (invest remainder when < spend, notify).
- Place simulated buys using current MC/liquidity (10% MC rule, same slippage/fee model as /invest).
- Track positions, realized P&L; reinvest only after initial budget is deployed.
- Schedule sells at hold time per run; value using freshest tick (≤15s) or retry before marking stale.

## Phase 5 – Alerts & Reports
- Time-based reports (paginated when large): transactions, P&L, cash, open positions, skips with reasons.
- Event alerts: breakout (configurable multiples), bankrupt, low-funds, remainder-used.
- Destination routing per run (chosen chat or DM); reuse existing alert dispatcher.

## Phase 6 – Observability & Hardening
- Settings overview panel: “AutoTrader Errors/Misses” showing stale>15s, fetch_fail, no_liquidity, budget_exhausted, retry_exceeded.
- Metrics/logging for attempts vs successes; ensure retries align with “never miss” goal.
- Smoke tests: start/stop run, coin-cap stop, stale-data skip path, reinvest after realized P&L, multi-channel selection, report pagination.
