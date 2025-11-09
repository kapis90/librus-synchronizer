# Librus Synchronizer

A small utility that synchronizes your Librus school schedule with a Google Calendar.

What it does
- Uses the `librus-apix` client to authenticate with Librus and fetch the schedule.
- Prepares Google Calendar all-day events (one per day) for the current and next month.
- Cleans up the configured Google calendar for each month (deletes events from the 1st of the month onward) and re-adds the prepared events.
- Attempts to fetch a detailed description for each event (via `schedule_detail`) and falls back to any short description available.

Requirements
- Python >= 3.12
- The dependencies are declared in `pyproject.toml`; main runtime packages include `gcsa`, `librus-apix`, `python-dateutil` and `retry`.

Environment variables
- `G_SERVICE_ACCOUNT_JSON` (required): the Google service account JSON key, provided as a JSON string in the environment variable. For example on macOS/zsh: `export G_SERVICE_ACCOUNT_JSON="$(cat /path/to/key.json)"`.
	- The service account must be given access to the calendar you plan to use (share the calendar with the service account email).
- `CALENDAR_ID` (required): the Google Calendar ID (typically an email-like id) of the calendar to synchronize.
- `LIBRUS_USERNAME` and `LIBRUS_PASSWORD` (required): credentials for your Librus account.
- `DEBUG` (optional): if set (`1`, `true`, `yes`) enables DEBUG logging.
- `LOG_FILE` (optional): path to a file where logs will also be written (file handler logs at DEBUG level).

How it behaves
- The entrypoint is `execute.py` (callable as `python execute.py`).
- The script authenticates against Librus with retries and then creates a `GoogleCalendarWrapper` using the provided service account JSON and `CALENDAR_ID`.
- It synchronizes two months: the current month and the next month. For each month it:
	1. Fetches the schedule using `librus-apix`.
	2. Builds `gcsa.event.Event` all-day events (summary contains lesson title and subject).
	3. Cleans up (deletes) existing events in the target calendar starting from the 1st day of that month.
	4. Adds prepared events to the target calendar.

Usage (quick)
1. Install dependencies

This project uses `uv` to manage and install dependencies. Make sure `uv` is installed on your system, then run:

```bash
uv sync
```

2. Populate environment variables (example for zsh/macOS):

```bash
export G_SERVICE_ACCOUNT_JSON="$(cat /path/to/service-account-key.json)"
export CALENDAR_ID="your_calendar_id@group.calendar.google.com"
export LIBRUS_USERNAME="your_librus_username"
export LIBRUS_PASSWORD="your_librus_password"
# optional
export DEBUG=1
export LOG_FILE="/tmp/librus-sync.log"
```

3. Run the synchronizer:

```bash
python execute.py
```

Notes and troubleshooting
- G_SERVICE_ACCOUNT_JSON must contain the raw JSON key text. The code reads this environment variable and calls `json.loads` on it.
- Make sure the service account is granted access to the calendar (share the calendar with the service account email found in the JSON key).
- If `G_SERVICE_ACCOUNT_JSON` is missing or malformed the calendar wrapper will log the error and raise an exception.
- The Librus token acquisition is retried up to 3 times for common connection errors (configured with the `retry` decorator).
- The script removes events from the target calendar starting at the 1st day of each synced month; if you use the same calendar for other unrelated events, those may be deleted.

Development
- Linting / formatting: `ruff` is configured in the dev dependency group in `pyproject.toml`.

Security
- Keep your Librus credentials and the service account JSON private. Do not commit them to the repository.

Contact / Contributing
- Feel free to open issues or PRs to improve behavior, add unit tests or safer dry-run modes.
