"""Fetch Librus announcements and print them as JSON for webhook use.

Stdout contains only the JSON payload (logs go to stderr), so a workflow
can safely redirect stdout to a file and POST it.
"""

import json
import logging
import os
import sys

from librus_apix.announcements import get_announcements
from librus_apix.client import Client, Token, new_client
from retry import retry
from urllib3.exceptions import ConnectionError, MaxRetryError, ProtocolError

from logging_config import setup_logging

logger = logging.getLogger(__name__)


@retry(exceptions=(MaxRetryError, ConnectionError, ProtocolError), tries=3, delay=2)
def __acquire_librus_token(client: Client, username: str, password: str) -> Token:
    """Acquire Librus token for the given credentials."""
    return client.get_token(username, password)


def _require_env(name: str) -> str:
    """Return an environment variable or exit with a clear error."""
    value = os.getenv(name)
    if not value:
        logger.error("Missing required environment variable: %s", name)
        sys.exit(1)
    return value


def main() -> None:
    debug = os.getenv("DEBUG", "false").lower() in ("1", "true", "yes")
    log_file = os.getenv("LOG_FILE")
    setup_logging(debug=debug, log_file=log_file)

    username = _require_env("LIBRUS_USERNAME")
    password = _require_env("LIBRUS_PASSWORD")

    client: Client = new_client()
    __acquire_librus_token(client, username, password)

    announcements = get_announcements(client)
    logger.info("Fetched %d announcement(s)", len(announcements))

    payload = {
        "announcements": [
            {
                "title": announcement.title,
                "author": announcement.author,
                "description": announcement.description,
                "date": announcement.date,
            }
            for announcement in announcements
        ]
    }
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
