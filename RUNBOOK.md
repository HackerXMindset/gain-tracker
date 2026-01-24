# Standalone Gain Alert Service Runbook

## Setup
- Create a dedicated Postgres database for the standalone service.
- Apply migrations from `gain_alert_standalone/migrations` (the app will run them on startup).
- Populate `bots` with userbot session strings and `monitored_sources` with chat/user config.
- Add chart request groups in `chart_request_groups` if chart images are required.
- Configure environment variables (see `gain_alert_standalone/.env.sample`).

## Run
- Start service: `python -m gain_alert_standalone.cli run`
- Health check: `python -m gain_alert_standalone.cli health`

## Common Issues
- No alerts: verify `monitored_sources` entries and that userbots are connected.
- No charts: ensure `chart_request_groups` has at least one negative chat ID and a chart bot ID is configured.
- Dex data missing: check network access to Jupiter/DexScreener endpoints.
- DB errors: confirm `GAIN_ALERT_DB_URL` and that migrations ran successfully.

## Data Integrity
- Active tokens live in `tokens_tracked` with `status='active'`.
- Per-chat tracking is stored in `token_group_alerts`.
- Alert send outcomes are recorded in `alert_queue`.
