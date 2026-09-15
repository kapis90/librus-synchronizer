import logging
import pytest
from logging_config import setup_logging


@pytest.fixture(autouse=True)
def _clean_root_logger():
    """Reset root logger before and after each test."""
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
        try:
            h.close()
        except Exception:
            pass
    root.setLevel(logging.WARNING)
    yield
    for h in list(root.handlers):
        root.removeHandler(h)
        try:
            h.close()
        except Exception:
            pass
    root.setLevel(logging.WARNING)


class TestSetupLogging:
    def test_sets_info_level_by_default(self):
        setup_logging()
        assert logging.getLogger().level == logging.INFO

    def test_sets_debug_level_when_debug_true(self):
        setup_logging(debug=True)
        assert logging.getLogger().level == logging.DEBUG

    def test_adds_file_handler_when_log_file_given(self, tmp_path):
        log_file = tmp_path / "test.log"
        setup_logging(log_file=str(log_file))

        root = logging.getLogger()
        file_handlers = [h for h in root.handlers if isinstance(h, logging.FileHandler)]
        assert len(file_handlers) == 1
        assert file_handlers[0].baseFilename == str(log_file)
