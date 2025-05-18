# -*- coding: utf-8 -*-
from datetime import datetime
import os
from typing import Iterable

from gcsa.event import Event
from gcsa.google_calendar import GoogleCalendar
from google.oauth2.service_account import Credentials
import json


class GoogleCalendarWrapper:
    def __init__(self, calendar_id: str):
        self._google_calendar = GoogleCalendar(
            credentials=self._get_service_account_credentials(),  # type: ignore
        )
        self._secondary_calendar = calendar_id

    def _get_service_account_credentials(self) -> Credentials:
        service_account_info = json.loads(str(os.getenv("G_SERVICE_ACCOUNT_JSON")))
        scopes = ["https://www.googleapis.com/auth/calendar"]
        creds = Credentials.from_service_account_info(
            service_account_info, scopes=scopes
        )
        return creds

    def get_events(self, time_min: datetime) -> Iterable[Event]:
        return self._google_calendar.get_events(
            time_min=time_min, calendar_id=self._secondary_calendar
        )

    def add_event(self, event: Event) -> None:
        self._google_calendar.add_event(event, calendar_id=self._secondary_calendar)

    def cleanup_calendar(self, start_date: datetime) -> None:
        """Cleanup calendar by removing all events after a certain date"""
        events = self.get_events(time_min=start_date)
        for event in events:
            self._google_calendar.delete_event(
                event, calendar_id=self._secondary_calendar
            )
