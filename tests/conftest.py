from unittest.mock import MagicMock
import pytest


@pytest.fixture
def mock_schedule_event():
    def _make_event(title="Math", subject="Algebra", href="prefix/12345", data=None):
        event = MagicMock()
        event.title = title
        event.subject = subject
        event.href = href
        event.data = data or {"Opis": ""}
        return event

    return _make_event


@pytest.fixture
def mock_librus_client():
    return MagicMock()
