# Repository Guidelines

## Project Structure & Module Organization
Primary source lives at the repo root with feature-focused packages such as `alerts/`, `charts/`, `scheduler/`, `services/`, `userbot/`, `ui/`, `db/`, `models/`, `config/`, and `utils/`. Database migrations are in `migrations/`, tests in `tests/`, and operational docs in `RUNBOOK.md`. There is also a duplicated app tree under `main/` (including `main/gain_alert_standalone/` and `main/app/`); confirm which tree you are modifying before editing.

## Build, Test, and Development Commands
- `python cli.py run` starts the service from the repo root.
- `python cli.py health` runs health checks and exits with a non-zero status on failure.
- The runbook also references `python -m gain_alert_standalone.cli run|health` when running the package as a module.
- Migrations are stored in `migrations/` and are applied on startup per `RUNBOOK.md`; review them when changing schema.

## Coding Style & Naming Conventions
Follow the existing Python style: 4-space indentation, type hints, and explicit `async`/`await` flows. Keep modules under ~1000 lines and favor small, testable functions (per `README.md`). Use `snake_case` for functions/variables, `PascalCase` for classes, and `UPPER_SNAKE_CASE` for constants.

## Testing Guidelines
Tests use pytest-style functions in `tests/` (e.g., `test_guardrails.py`). Run them with `python -m pytest tests` (install `pytest` if needed). Name new tests `test_*.py` and keep assertions focused on one behavior.

## Commit & Pull Request Guidelines
The Git history currently contains only “Initial commit - Gain Alert Tracker,” so there is no established convention. Use concise, imperative summaries and add a scope when helpful (e.g., “alerts: tighten guardrails”). PRs should include a clear description, test results, and any operational impacts. If you add config or env vars, update `.env.sample`; if you change alert text or UI templates, include before/after examples.

## Security & Configuration Tips
Do not commit secrets. Store tokens and database URLs in environment variables, with defaults documented in `.env.sample`. Configuration is centralized in `config/`, so changes there should be reflected in the sample env file and runbook where applicable.

## Agent-Specific Notes
Automation and task protocols live in `CLAUDE.md` and `.claude/`. If you use the sessions system, keep `.claude/state/current_task.json` updated as described there.
