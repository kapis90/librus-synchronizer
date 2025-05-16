# -*- coding: utf-8 -*-
import os
from datetime import datetime

from librus_apix.client import Client, Token, new_client
from google_calendar_wrapper import GoogleCalendarWrapper
from librus_synchronizer import LibrusSynchronizer


def main():
    client: Client = new_client()
    _token: Token = client.get_token(
        str(os.getenv("LIBRUS_USERNAME")), str(os.getenv("LIBRUS_PASSWORD"))
    )
    antosia_calendar = GoogleCalendarWrapper(
        email_address=str(os.getenv("EMAIL_ADDRESS")),
        calendar_id=str(os.getenv("ANTOSIA_CALENDAR_ID")),
    )
    client.token = _token
    librus_synchronizer = LibrusSynchronizer(
        librus_client=client,
        calendar=antosia_calendar,
    )
    librus_synchronizer.fill_calendar(
        str(datetime.today().month), str(datetime.today().year)
    )
    librus_synchronizer.fill_calendar(
        str(datetime.today().month + 1), str(datetime.today().year)
    )


if __name__ == "__main__":
    main()
