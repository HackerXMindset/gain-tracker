# Standalone Gain Alert Service

## Conventions
- Keep each module under 1000 lines; split by responsibility if it grows.
- Prefer small, testable functions over monolithic handlers.

## Run
- `python -m gain_alert_standalone.cli run`
- `python -m gain_alert_standalone.cli health`
- `python gain_alert_standalone/runner.py`
