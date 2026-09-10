"""LG# — `backend/logger.py`, the one function the whole app's logging rests on.

`setup_logger()` is called once by `main.py` and then never again, so nothing in
the suite exercised it: no rotation limits, no file name, no "the previous
handlers are gone" guarantee. These cases pin all of that, because every log
line the debugger pane shows depends on it.

The "chatbot" logger is global, so each case runs through `restore_logger`:
whatever it changes, it hands back the way it found it.
"""

from __future__ import annotations

import importlib
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytest

from backend.logger import setup_logger


@pytest.fixture
def restore_logger():
    """Leave the real "chatbot" logger exactly as it was."""
    logger = logging.getLogger("chatbot")
    saved = (list(logger.handlers), logger.level, logger.propagate)
    try:
        yield logger
    finally:
        for handler in list(logger.handlers):
            if isinstance(handler, logging.Handler):
                handler.close()
        handlers, level, propagate = saved
        logger.handlers[:] = handlers
        logger.setLevel(level)
        logger.propagate = propagate


def handlers_of(logger, kind):
    return [h for h in logger.handlers if isinstance(h, kind)]


# ── the files it writes ──────────────────────────────────────────────
def test_the_log_dir_is_created_when_missing(tmp_path, restore_logger):
    target = tmp_path / "deep" / "nested" / "logs"
    assert not target.exists()
    setup_logger(log_dir=str(target))
    assert target.is_dir()


def test_the_file_is_named_after_today(tmp_path, restore_logger):
    from datetime import datetime
    logger = setup_logger(log_dir=str(tmp_path))
    expected = f"{datetime.now():%Y-%m-%d}.log"
    files = [p.name for p in tmp_path.iterdir()]
    assert files == [expected]
    active = handlers_of(logger, RotatingFileHandler)[0]
    assert Path(active.baseFilename).name == expected


def test_records_land_in_the_file(tmp_path, restore_logger):
    logger = setup_logger(log_dir=str(tmp_path))
    logger.info("hello from LG#")
    for handler in logger.handlers:
        handler.flush()
    body = (tmp_path / next(iter(p.name for p in tmp_path.iterdir()))).read_text(
        encoding="utf-8")
    assert "hello from LG#" in body
    # the opening line the setup itself writes
    assert "Logger initialized →" in body


# ── the handlers it installs ─────────────────────────────────────────
def test_exactly_two_handlers_rotating_file_plus_console(tmp_path,
                                                          restore_logger):
    logger = setup_logger(log_dir=str(tmp_path))
    assert len(logger.handlers) == 2
    file_handlers = handlers_of(logger, RotatingFileHandler)
    assert len(file_handlers) == 1
    # (RotatingFileHandler IS a StreamHandler, so the console one is whatever
    # is left over — that is the pair the file's docstring promises.)
    console = [h for h in logger.handlers if h not in file_handlers]
    assert len(console) == 1
    assert type(console[0]) is logging.StreamHandler
    import sys
    assert console[0].stream is sys.stderr


def test_rotation_limits(tmp_path, restore_logger):
    logger = setup_logger(log_dir=str(tmp_path))
    fh = handlers_of(logger, RotatingFileHandler)[0]
    assert fh.maxBytes == 2_000_000
    assert fh.backupCount == 5
    assert fh.encoding == "utf-8"


def test_one_format_for_both_handlers(tmp_path, restore_logger):
    logger = setup_logger(log_dir=str(tmp_path))
    formats = [h.formatter._fmt for h in logger.handlers]
    datefmts = [h.formatter.datefmt for h in logger.handlers]
    assert formats == ["[%(asctime)s] %(levelname)s %(message)s"] * 2
    assert datefmts == ["%H:%M:%S"] * 2


# ── levels ──────────────────────────────────────────────────────────
def test_the_requested_level_reaches_every_handler(tmp_path, restore_logger):
    logger = setup_logger(log_dir=str(tmp_path), level=logging.WARNING)
    assert logger.level == logging.WARNING
    assert [h.level for h in logger.handlers] == [logging.WARNING] * 2


def test_info_is_the_default_level(tmp_path, restore_logger):
    logger = setup_logger(log_dir=str(tmp_path))
    assert logger.level == logging.INFO


def test_debug_lines_are_dropped_at_info_and_kept_at_debug(tmp_path,
                                                            restore_logger):
    log_file = lambda d: next(iter(Path(d).glob("*.log")))

    setup_logger(log_dir=str(tmp_path))
    logging.getLogger("chatbot").debug("quiet detail")
    for handler in logging.getLogger("chatbot").handlers:
        handler.flush()
    assert "quiet detail" not in log_file(tmp_path).read_text(encoding="utf-8")

    logger = setup_logger(log_dir=str(tmp_path), level=logging.DEBUG)
    logger.debug("loud detail")
    for handler in logger.handlers:
        handler.flush()
    assert "loud detail" in log_file(tmp_path).read_text(encoding="utf-8")


# ── re-running it ────────────────────────────────────────────────────
def test_repeated_setup_never_duplicates_the_handlers(tmp_path,
                                                       restore_logger):
    setup_logger(log_dir=str(tmp_path))
    second = setup_logger(log_dir=str(tmp_path))
    assert len(second.handlers) == 2, "double logging would follow every line"
    # the foreign handler is gone as well, not just counted
    probe = logging.Handler()
    second.addHandler(probe)
    third = setup_logger(log_dir=str(tmp_path))
    assert probe not in third.handlers


def test_the_module_stays_stdlib_only(tmp_path, restore_logger):
    """No third-party logging dependency: the file must import with stdlib alone.

    The app runs under PySide6's event loop, where an external logging backend
    (loguru, structlog) would fight the Qt handlers — so this module is the
    one place the plan wants plain `logging`, and it is pinned here.
    """
    source = Path("backend/logger.py").read_text(encoding="utf-8")
    imports = [line for line in source.splitlines()
               if line.startswith(("import ", "from "))]
    assert imports, "expected import lines to check"
    allowed = {"logging", "os", "sys", "datetime", "pathlib", "typing"}
    for line in imports:
        root = (line.split()[1] if line.startswith("import ")
                else line.split()[1]).split(".")[0]
        assert root in allowed, f"unexpected dependency in backend/logger: {line}"
    assert importlib.import_module("backend.logger").setup_logger is setup_logger
