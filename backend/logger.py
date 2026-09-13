"""Logging setup with rotating file and console output."""

import logging
import os
from logging.handlers import RotatingFileHandler
from datetime import datetime


def setup_logger(log_dir: str = "logs", level: int = logging.INFO) -> logging.Logger:
    """Configure and return the application logger."""
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f"{datetime.now():%Y-%m-%d}.log")

    logger = logging.getLogger("chatbot")
    logger.setLevel(level)
    logger.handlers.clear()

    fmt = logging.Formatter(
        "[%(asctime)s] %(levelname)s %(message)s", datefmt="%H:%M:%S"
    )

    fh = RotatingFileHandler(log_file, maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    fh.setLevel(level)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    ch = logging.StreamHandler()
    ch.setLevel(level)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    logger.info("Logger initialized → %s", log_file)
    return logger


def report_and_log(report: "Callable | None", message: str,
                   level: str = "info") -> None:
    """Say it in the run console AND in the log file.

    RULE 5's shape: the user sees progress in the console, the log keeps the
    record. A `report` callback that raises is swallowed on purpose — a UI
    error must never abort the backend operation that was merely narrating
    itself — but the log line is still written, so nothing is lost silently.

    `backend/media_handler.py` and `backend/message_injector.py` each carried a
    byte-identical private copy of this (clone group, span 7); it lives here
    because this module owns logging for the backend.
    """
    if report:
        try:
            report(message, level)
        except Exception:           # noqa: BLE001 — see docstring
            pass
    logging.getLogger("chatbot").log(
        getattr(logging, level.upper(), logging.INFO), "%s", message)
