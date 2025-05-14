# -*- coding: utf-8 -*-
from datetime import datetime
import os
from pathlib import Path
from typing import Iterable

from gcsa.event import Event
from gcsa.google_calendar import GoogleCalendar
from google.oauth2.credentials import Credentials

from create_token_pickle import create_token_pickle

# TOKEN_PATH = Path(__file__).parent / ".credentials" / "token.pickle"
CREDENTIALS = Credentials(
    token=os.getenv("G_TOKEN"),
    refresh_token=os.getenv("G_REFRESH_TOKEN"),
    token_uri="https://oauth2.googleapis.com/token",
    client_id=os.getenv("G_CLIENT_ID"),
    client_secret=os.getenv("G_CLIENT_SECRET"),
)


class GoogleCalendarWrapper:
    def __init__(self, email_address: str, calendar_id: str):
        # create_token_pickle(TOKEN_PATH)
        self._google_calendar = GoogleCalendar(email_address, credentials=CREDENTIALS)
        self._secondary_calendar = calendar_id

    def get_events(self, time_min: datetime) -> Iterable[Event]:
        return self._google_calendar.get_events(
            time_min=time_min, calendar_id=self._secondary_calendar
        )

    def add_event(self, event: Event) -> Event:
        event = self._google_calendar.add_event(event)
        return self._google_calendar.move_event(
            event, destination_calendar_id=self._secondary_calendar
        )

    def cleanup_calendar(self, start_date: datetime) -> None:
        """Cleanup calendar by removing all events after a certain date"""
        events = self.get_events(time_min=start_date)
        for event in events:
            self._google_calendar.delete_event(
                event, calendar_id=self._secondary_calendar
            )
