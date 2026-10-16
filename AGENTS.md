# Librus Synchronizer — AGENTS.md

## Project structure

Single flat Python project (no packages/monorepo). Modules declared in `pyproject.toml` `[tool.setuptools] py-modules`. Two independent entrypoints, both under `if __name__ == "__main__":`.

## Commands

```sh
uv sync                  # install dependencies (including dev: ruff)
uv run execute.py        # run the calendar synchronizer
uv run get_unread_messages.py  # run the unread-messages script
ruff check               # lint (CI runs this on PRs)
ruff format --check      # formatting check (CI: `--check --diff`)
ruff format              # auto-format
```

## Tests

```sh
uv run pytest                                              # run all tests
uv run pytest --cov --cov-branch --cov-report=term-missing  # full coverage report
```

Tests mock external APIs (Librus, Google Calendar). No real credentials needed.

## Entrypoints

| File | Purpose |
|------|---------|
| `execute.py` | Syncs Librus schedule (current + next month) to Google Calendar |
| `get_unread_messages.py` | Fetches unread Librus messages, prints JSON to stdout |

Both share `logging_config.py` for logging setup.

## Required env vars

| Var | Source |
|-----|--------|
| `LIBRUS_USERNAME` | Librus credentials |
| `LIBRUS_PASSWORD` | Librus credentials |
| `CALENDAR_ID` | Google Calendar ID |
| `G_SERVICE_ACCOUNT_JSON` | Raw Google service account JSON string |

Optional: `DEBUG` (`1`/`true`/`yes`), `LOG_FILE`.

`.env` is gitignored but VSCode launch config reads it automatically (`envFile`). Never commit credentials.

## CI

- **Cron sync** (`.github/workflows/run_synchronization.yml`): runs hourly (`42 * * * *`) with matrix for two users (`Tosia`/`Dorota`), using `secrets.LIBRUS_USERNAME_T` / `secrets.LIBRUS_USERNAME_D` and corresponding calendar secrets.
- **Unread messages** (`get-unread-messages.yml`): manual trigger (`workflow_dispatch`) with `who` input to select user.
- **Tests** (`tests_pr.yml`): `uv run pytest --cov --cov-branch --cov-report=term-missing` on every PR.
- **Ruff** (`ruff_pr.yml`): `check --output-format=github` + `format --check --diff` on every PR.

## Quirks

- `librus_apix` token acquisition is wrapped with `@retry(tries=3, delay=2)` for connection errors.
- `fill_calendar(month, year)` cleans up ALL calendar events from the 1st of that month onward before re-adding. Do not use the target calendar for unrelated events.
- `get_unread_messages.py` calls `message_content()` for each unread message — this is one HTTP request per unread message.
- No ruff config file exists; uses default rules.

## VSCode

`.vscode/settings.json` sets `python.analysis.typeCheckingMode: "basic"`. Launch config reads `.env` and sets `DEBUG=0`, `LOG_FILE`.
