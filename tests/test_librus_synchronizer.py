from unittest.mock import MagicMock, patch, call
from datetime import date
from gcsa.event import Event

from librus_synchronizer import LibrusSynchronizer


class TestGetEventsForMonth:
    @patch("librus_synchronizer.get_schedule")
    @patch("librus_synchronizer.schedule_detail")
    def test_returns_events_for_valid_schedule(
        self,
        mock_schedule_detail,
        mock_get_schedule,
        mock_schedule_event,
        mock_librus_client,
    ):
        event = mock_schedule_event()
        # real get_schedule returns int day keys
        mock_get_schedule.return_value = {15: [event]}
        mock_schedule_detail.return_value = {"Opis": "Detailed lesson description"}

        synchronizer = LibrusSynchronizer(
            librus_client=mock_librus_client, calendar=MagicMock()
        )
        result = synchronizer.get_events_for_month("3", "2025")

        assert len(result) == 1
        assert result[0].summary == "Math: Algebra"
        assert result[0].start == date(2025, 3, 15)
        assert result[0].description == "Detailed lesson description"
        mock_get_schedule.assert_called_once_with(mock_librus_client, "3", "2025")

    @patch("librus_synchronizer.get_schedule")
    def test_returns_empty_list_for_empty_schedule(
        self, mock_get_schedule, mock_librus_client
    ):
        mock_get_schedule.return_value = {}

        synchronizer = LibrusSynchronizer(
            librus_client=mock_librus_client, calendar=MagicMock()
        )
        result = synchronizer.get_events_for_month("3", "2025")

        assert result == []

    @patch("librus_synchronizer.get_schedule")
    @patch("librus_synchronizer.schedule_detail")
    def test_skips_events_with_invalid_date(
        self,
        mock_schedule_detail,
        mock_get_schedule,
        mock_schedule_event,
        mock_librus_client,
    ):
        event = mock_schedule_event()
        mock_get_schedule.return_value = {"invalid_day": [event]}

        synchronizer = LibrusSynchronizer(
            librus_client=mock_librus_client, calendar=MagicMock()
        )
        result = synchronizer.get_events_for_month("3", "2025")

        assert result == []
        mock_schedule_detail.assert_not_called()

    @patch("librus_synchronizer.get_schedule")
    @patch("librus_synchronizer.schedule_detail")
    def test_skips_events_with_out_of_range_date(
        self,
        mock_schedule_detail,
        mock_get_schedule,
        mock_schedule_event,
        mock_librus_client,
    ):
        # "32" parses as int but date(2025, 3, 32) is invalid;
        # Feb 30 is another out-of-range example.
        event = mock_schedule_event()
        mock_get_schedule.return_value = {"32": [event]}

        synchronizer = LibrusSynchronizer(
            librus_client=mock_librus_client, calendar=MagicMock()
        )
        result = synchronizer.get_events_for_month("3", "2025")

        assert result == []
        mock_schedule_detail.assert_not_called()


class TestGetDescription:
    @patch("librus_synchronizer.schedule_detail")
    def test_returns_detail_when_available(
        self, mock_schedule_detail, mock_schedule_event, mock_librus_client
    ):
        event = mock_schedule_event(href="prefix/12345", data={"Opis": ""})
        mock_schedule_detail.return_value = {"Opis": "Detailed description"}

        synchronizer = LibrusSynchronizer(
            librus_client=mock_librus_client, calendar=MagicMock()
        )
        result = synchronizer._get_description(event)

        assert result == "Detailed description"
        mock_schedule_detail.assert_called_once_with(
            mock_librus_client, "prefix", "12345"
        )

    @patch("librus_synchronizer.schedule_detail")
    def test_falls_back_to_event_data_on_schedule_detail_failure(
        self, mock_schedule_detail, mock_schedule_event, mock_librus_client
    ):
        event = mock_schedule_event(href="prefix/12345", data={"Opis": "Fallback desc"})
        mock_schedule_detail.side_effect = ValueError("API error")

        synchronizer = LibrusSynchronizer(
            librus_client=mock_librus_client, calendar=MagicMock()
        )
        result = synchronizer._get_description(event)

        assert result == "Fallback desc"

    @patch("librus_synchronizer.schedule_detail")
    def test_falls_back_on_generic_schedule_detail_error(
        self, mock_schedule_detail, mock_schedule_event, mock_librus_client
    ):
        # schedule_detail raises ParseError (not ValueError/KeyError) on
        # unparseable HTML, plus network errors may surface here.
        from librus_apix.exceptions import ParseError

        event = mock_schedule_event(href="prefix/12345", data={"Opis": "Fallback desc"})
        mock_schedule_detail.side_effect = ParseError("parse failed")

        synchronizer = LibrusSynchronizer(
            librus_client=mock_librus_client, calendar=MagicMock()
        )
        result = synchronizer._get_description(event)

        assert result == "Fallback desc"

    @patch("librus_synchronizer.schedule_detail")
    def test_falls_back_to_event_data_when_detail_has_no_opis(
        self, mock_schedule_detail, mock_schedule_event, mock_librus_client
    ):
        event = mock_schedule_event(href="prefix/12345", data={"Opis": "From data"})
        mock_schedule_detail.return_value = {"OtherField": "no opis here"}

        synchronizer = LibrusSynchronizer(
            librus_client=mock_librus_client, calendar=MagicMock()
        )
        result = synchronizer._get_description(event)

        assert result == "From data"

    @patch("librus_synchronizer.schedule_detail")
    def test_returns_empty_string_when_nothing_available(
        self, mock_schedule_detail, mock_schedule_event, mock_librus_client
    ):
        event = mock_schedule_event(href="prefix/12345", data={"Opis": ""})
        mock_schedule_detail.return_value = {"OtherField": "no opis here"}

        synchronizer = LibrusSynchronizer(
            librus_client=mock_librus_client, calendar=MagicMock()
        )
        result = synchronizer._get_description(event)

        assert result == ""

    def test_falls_back_on_malformed_href(
        self, mock_schedule_event, mock_librus_client
    ):
        event = mock_schedule_event(href="", data={"Opis": "No href desc"})

        synchronizer = LibrusSynchronizer(
            librus_client=mock_librus_client, calendar=MagicMock()
        )
        result = synchronizer._get_description(event)

        assert result == "No href desc"

    @patch("librus_synchronizer.schedule_detail")
    def test_handles_href_with_extra_slashes(
        self, mock_schedule_detail, mock_schedule_event, mock_librus_client
    ):
        event = mock_schedule_event(href="prefix/a/b", data={"Opis": "Fallback"})
        mock_schedule_detail.return_value = {"Opis": "Detailed"}

        synchronizer = LibrusSynchronizer(
            librus_client=mock_librus_client, calendar=MagicMock()
        )
        result = synchronizer._get_description(event)

        assert result == "Detailed"
        mock_schedule_detail.assert_called_once_with(
            mock_librus_client, "prefix", "a/b"
        )

    @patch("librus_synchronizer.schedule_detail")
    def test_falls_back_when_detail_opis_empty(
        self, mock_schedule_detail, mock_schedule_event, mock_librus_client
    ):
        event = mock_schedule_event(href="prefix/12345", data={"Opis": "Fallback"})
        mock_schedule_detail.return_value = {"Opis": ""}

        synchronizer = LibrusSynchronizer(
            librus_client=mock_librus_client, calendar=MagicMock()
        )
        result = synchronizer._get_description(event)

        assert result == "Fallback"


class TestFillCalendar:
    def test_cleans_up_and_adds_events(self, mock_librus_client):
        mock_calendar = MagicMock()
        real_event1 = Event(summary="Math: Algebra", start=date(2025, 3, 1))
        real_event2 = Event(summary="Physics: Mechanics", start=date(2025, 3, 2))

        synchronizer = LibrusSynchronizer(
            librus_client=mock_librus_client, calendar=mock_calendar
        )

        with patch.object(
            synchronizer,
            "get_events_for_month",
            return_value=[real_event1, real_event2],
        ) as mock_get:
            synchronizer.fill_calendar("3", "2025")

            mock_get.assert_called_once_with("3", "2025")
            mock_calendar.cleanup_calendar.assert_called_once()
            call_args = mock_calendar.cleanup_calendar.call_args
            assert call_args[0][0].isoformat().startswith("2025-03-01")
            assert mock_calendar.add_event.call_count == 2
            mock_calendar.add_event.assert_has_calls(
                [
                    call(real_event1),
                    call(real_event2),
                ]
            )
