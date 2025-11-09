# -*- coding: utf-8 -*-
from typing import List, Optional
from gcsa.event import Event
from librus_apix.client import Client
from librus_apix.schedule import get_schedule, schedule_detail


from datetime import date, datetime

from google_calendar_wrapper import GoogleCalendarWrapper
import logging

logger = logging.getLogger(__name__)


class LibrusSynchronizer:
    def __init__(self, librus_client: Client, calendar: GoogleCalendarWrapper):
        self.calendar = calendar
        self.librus_client = librus_client

    def get_events_for_month(self, month: str, year: str) -> List[Event]:
        """Build and return a list of `gcsa.event.Event` objects for the
        given month/year using the configured `librus_client`.

        This method only prepares the events and does not modify the
        calendar. It can be used to inspect or test event generation before
        performing cleanup/add operations.
        """
        logger.debug("Fetching schedule for month=%s year=%s", month, year)
        schedule = get_schedule(self.librus_client, month, year)
        events = []
        for day in schedule:
            for librus_event in schedule[day]:
                logger.debug("Processing raw event: %s (day=%s)", getattr(librus_event, 'title', repr(librus_event)), day)
                description = self._get_description(librus_event)
                try:
                    day_int = int(day)
                    month_int = int(month)
                    year_int = int(year)
                except (TypeError, ValueError):
                    # if any of the date parts are invalid, skip this event
                    logger.warning("Skipping event with invalid date (%s): %s", day, repr(librus_event))
                    continue

                gcsa_event = Event(
                    summary=f"{librus_event.title}: {librus_event.subject}",
                    description=description,
                    start=date(year_int, month_int, day_int),
                )
                events.append(gcsa_event)
                logger.info("Prepared event: %s", gcsa_event)

        return events

    def _get_description(self, librus_event) -> Optional[str]:
        """Attempt to fetch detailed description via `schedule_detail`.

        Falls back to the description available in `librus_event.data` if any
        error occurs or the detailed description is missing.
        """
        try:
            # href is expected to contain something like "prefix/href"
            prefix, href = librus_event.href.split("/")
            details = schedule_detail(self.librus_client, prefix, href)
            # prefer the detailed description if present
            desc = details.get("Opis", librus_event.data.get("Opis", ""))
            logger.debug("Fetched detailed description for href=%s: %s", librus_event.href, bool(desc))
            return desc
        except (KeyError, ValueError) as exc:
            # Any problem retrieving details -> fallback
            logger.debug("Unable to fetch detailed description for event=%s: %s", getattr(librus_event, 'href', repr(librus_event)), exc)
            return librus_event.data.get("Opis", "")

    def fill_calendar(self, month: str, year: str) -> None:
        """Generate events for the month, clean up calendar and add them.

        This method now prepares the event collection first (so callers can
        inspect it), then performs the calendar cleanup and adds events.
        """
        logger.info("Preparing events for calendar for %s-%s", month, year)
        events = self.get_events_for_month(month, year)

        # cleanup for the month start
        start_date = datetime(int(year), int(month), 1)
        logger.info("Cleaning up calendar starting from %s", start_date.isoformat())
        self.calendar.cleanup_calendar(start_date)

        for event in events:
            try:
                self.calendar.add_event(event)
                logger.info("Event added to calendar: %s", event)
            except Exception:
                logger.exception("Failed to add event to calendar: %s", event)
