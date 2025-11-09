# -*- coding: utf-8 -*-
import os
from datetime import datetime
import logging

from dateutil.relativedelta import relativedelta
from librus_apix.client import Client, Token, new_client
from retry import retry
from urllib3.exceptions import MaxRetryError

from google_calendar_wrapper import GoogleCalendarWrapper
from librus_synchronizer import LibrusSynchronizer
from logging_config import setup_logging

logger = logging.getLogger(__name__)


@retry(exceptions=MaxRetryError, tries=3, delay=2)
def __aquire_librus_token(client: Client) -> Token:
    """Aquire Librus token using environment variables LIBRUS_USERNAME and LIBRUS_PASSWORD."""
    return client.get_token(
        str(os.getenv("LIBRUS_USERNAME")), str(os.getenv("LIBRUS_PASSWORD"))
    )

def main():
    # configure logging early; allow DEBUG by environment flag
    debug = os.getenv("DEBUG", "false").lower() in ("1", "true", "yes")
    log_file = os.getenv("LOG_FILE")
    setup_logging(debug=debug, log_file=log_file)

    logger.info("Starting Librus synchronizer (debug=%s)", debug)

    client: Client = new_client()
    _token: Token = __aquire_librus_token(client)
    calendar = GoogleCalendarWrapper(calendar_id=str(os.getenv("CALENDAR_ID")),)
    client.token = _token
    librus_synchronizer = LibrusSynchronizer(librus_client=client, calendar=calendar,)
    today = datetime.today()
    next_month = today + relativedelta(months=1)

    try:
        librus_synchronizer.fill_calendar(str(today.month), str(today.year))
        librus_synchronizer.fill_calendar(str(next_month.month), str(next_month.year))
        logger.info("Finished synchronizing calendars for current and next month")
    except Exception:
        logger.exception("Unhandled error during calendar synchronization")


if __name__ == "__main__":
    main()
