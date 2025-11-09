# -*- coding: utf-8 -*-
"""Central logging configuration for the synchronizer.

Provides a simple setup function that configures a console handler and an
optional file handler. Call `setup_logging()` early in the application's
startup (for example in `execute.py`).
"""
from __future__ import annotations

import logging
from logging import StreamHandler, FileHandler, Formatter
from typing import Optional


def setup_logging(debug: bool = False, log_file: Optional[str] = None) -> None:
    """Configure root logger.

    Args:
        debug: if True set level to DEBUG, otherwise INFO.
        log_file: optional path to a file to also write logs to (keeps DEBUG level).
    """
    level = logging.DEBUG if debug else logging.INFO

    root = logging.getLogger()
    # Clear existing handlers to avoid duplicate logs when reloading
    if root.handlers:
        for h in list(root.handlers):
            root.removeHandler(h)

    root.setLevel(level)

    fmt = "%(asctime)s %(levelname)-8s [%(name)s:%(lineno)d] %(message)s"
    formatter = Formatter(fmt)

    sh = StreamHandler()
    sh.setLevel(level)
    sh.setFormatter(formatter)
    root.addHandler(sh)

    if log_file:
        fh = FileHandler(log_file, encoding="utf-8")
        # keep file handler debug-level so it records everything
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(formatter)
        root.addHandler(fh)
