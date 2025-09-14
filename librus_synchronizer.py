# -*- coding: utf-8 -*-
from gcsa.event import Event
from librus_apix.client import Client
from librus_apix.schedule import get_schedule, schedule_detail
from librus_apix.homework import get_homework


from datetime import date, datetime

from google_calendar_wrapper import GoogleCalendarWrapper


class LibrusSynchronizer:
    def __init__(self, librus_client: Client, calendar: GoogleCalendarWrapper):
        self.calendar = calendar
        self.librus_client = librus_client

    def fill_calendar(self, month: str, year: str):
        self.calendar.cleanup_calendar(datetime(int(year), int(month), 1))
        schedule = get_schedule(self.librus_client, month, year)
        for day in schedule:
            for event in schedule[day]:
                print(event.title)
                prefix, href = event.href.split("/")
                details = schedule_detail(self.librus_client, prefix, href)
                try:
                    description = details["Opis"]
                except KeyError:
                    description = event.data["Opis"] # if details description is missing, use the one from the event
                event = Event(
                    summary=f"{event.title}: {event.subject}",
                    description=description,
                    start=date(int(year), int(month), int(day)),
                )
                self.calendar.add_event(event)
                print(f"Event added: {event}")
