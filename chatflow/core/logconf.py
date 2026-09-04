"""Rotating file logging with retention pruning (main thread)."""
from __future__ import annotations

import logging
import logging.handlers
import re
from datetime import datetime, timedelta
from pathlib import Path

_ROOT = "chatflow"


def setup_logging(log_dir: str, level: str = "INFO", retention_days: int = 7) -> logging.Logger:
    root = logging.getLogger(_ROOT)
    root.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    if not any(isinstance(h, logging.handlers.TimedRotatingFileHandler) for h in root.handlers):
        d = Path(log_dir)
        d.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.TimedRotatingFileHandler(
            d / "chatflow.log", when="midnight", backupCount=0, encoding="utf-8")
        handler.suffix = "%Y-%m-%d"
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
        root.addHandler(handler)
        _prune(d, retention_days)
    return root


def _prune(log_dir: Path, retention_days: int) -> None:
    cutoff = datetime.now() - timedelta(days=max(retention_days, 1))
    pattern = re.compile(r"chatflow\.log\.(\d{4}-\d{2}-\d{2})$")
    for f in log_dir.glob("chatflow.log.*"):
        m = pattern.match(f.name)
        if not m:
            continue
        try:
            stamp = datetime.strptime(m.group(1), "%Y-%m-%d")
        except ValueError:
            continue
        if stamp < cutoff:
            try:
                f.unlink()
            except OSError:
                pass


def get(name: str) -> logging.Logger:
    return logging.getLogger(f"{_ROOT}.{name}")
