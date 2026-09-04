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
