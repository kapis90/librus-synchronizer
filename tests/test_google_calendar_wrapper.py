import json
from unittest.mock import MagicMock, patch, call
from datetime import datetime
import pytest

from google_calendar_wrapper import GoogleCalendarWrapper


class TestGetServiceAccountCredentials:
    @patch("google_calendar_wrapper.Credentials.from_service_account_info")
    @patch("google_calendar_wrapper.os.getenv")
    def test_loads_credentials_from_env(self, mock_getenv, mock_from_svc):
        mock_getenv.return_value = '{"client_email": "test@test.com"}'
        mock_cred = MagicMock()
        mock_from_svc.return_value = mock_cred

        wrapper = GoogleCalendarWrapper.__new__(GoogleCalendarWrapper)
        result = wrapper._get_service_account_credentials()

        mock_from_svc.assert_called_once_with(
            {"client_email": "test@test.com"},
            scopes=["https://www.googleapis.com/auth/calendar"],
        )
        assert result == mock_cred

    @patch("google_calendar_wrapper.os.getenv")
    def test_raises_on_invalid_json(self, mock_getenv):
        mock_getenv.return_value = "not valid json"

        wrapper = GoogleCalendarWrapper.__new__(GoogleCalendarWrapper)
        with pytest.raises(json.JSONDecodeError):
            wrapper._get_service_account_credentials()


class TestWrapperDelegation:
    def _make_wrapper(self):
        wrapper = GoogleCalendarWrapper.__new__(GoogleCalendarWrapper)
        wrapper._secondary_calendar = "test_cal_id"
        wrapper._google_calendar = MagicMock()
        return wrapper

    def test_add_event_delegates_to_google_calendar(self):
        wrapper = self._make_wrapper()
        mock_event = MagicMock()
        wrapper.add_event(mock_event)

        wrapper._google_calendar.add_event.assert_called_once_with(
            mock_event, calendar_id="test_cal_id"
        )

    def test_get_events_delegates_to_google_calendar(self):
        wrapper = self._make_wrapper()
        time_min = datetime(2025, 1, 1)
        wrapper.get_events(time_min)

        wrapper._google_calendar.get_events.assert_called_once_with(
            time_min=time_min, calendar_id="test_cal_id"
        )

    def test_cleanup_calendar_deletes_all_events(self):
        wrapper = self._make_wrapper()
        mock_event1 = MagicMock()
        mock_event2 = MagicMock()
        wrapper.get_events = MagicMock(return_value=[mock_event1, mock_event2])

        wrapper.cleanup_calendar(datetime(2025, 3, 1))

        wrapper._google_calendar.delete_event.assert_has_calls(
            [
                call(mock_event1, calendar_id="test_cal_id"),
                call(mock_event2, calendar_id="test_cal_id"),
            ]
        )

    def test_cleanup_calendar_continues_on_delete_failure(self):
        wrapper = self._make_wrapper()
        mock_event1 = MagicMock()
        mock_event2 = MagicMock()
        wrapper.get_events = MagicMock(return_value=[mock_event1, mock_event2])
        wrapper._google_calendar.delete_event.side_effect = [Exception("fail"), None]

        wrapper.cleanup_calendar(datetime(2025, 3, 1))

        assert wrapper._google_calendar.delete_event.call_count == 2
