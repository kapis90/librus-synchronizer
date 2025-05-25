# -*- coding: utf-8 -*-
import os
from datetime import datetime

from dateutil.relativedelta import relativedelta
from librus_apix.client import Client, Token, new_client

from google_calendar_wrapper import GoogleCalendarWrapper
from librus_synchronizer import LibrusSynchronizer


def main():
    client: Client = new_client()
    _token: Token = client.get_token(
        str(os.getenv("LIBRUS_USERNAME")), str(os.getenv("LIBRUS_PASSWORD"))
    )
    calendar = GoogleCalendarWrapper(
        calendar_id=str(os.getenv("CALENDAR_ID")),
    )
    client.token = _token
    librus_synchronizer = LibrusSynchronizer(
        librus_client=client,
        calendar=calendar,
    )
    today = datetime.today()
    next_month = today + relativedelta(months=1)
    librus_synchronizer.fill_calendar(str(today.month), str(today.year))
    librus_synchronizer.fill_calendar(str(next_month.month), str(next_month.year))


if __name__ == "__main__":
    main()
