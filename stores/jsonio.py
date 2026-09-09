"""Atomic JSON file I/O — the only place config files are written.

A save writes to `<file>.tmp`, flushes, then `os.replace`s onto the target:
a reader either sees the whole previous file or the whole new one, never a
half-written one. A failed label save can therefore never corrupt presets —
they are different files.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

log = logging.getLogger("chatbot")


def load_json(path: str, default: Any = None) -> Any:
    """Read `path`; on missing file or bad JSON return `default` (a copy)."""
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        # UnicodeDecodeError is a ValueError, not an OSError: a file with
        # invalid bytes (disk corruption, a crash mid-write of an older
        # version) must degrade to the default exactly like bad JSON —
        # it used to escape and crash ConfigManager construction.
        log.warning("config read failed for %s (%s) — using default",
                    path, exc)
        return default


def save_json(path: str, data: Any) -> bool:
    """Atomically write `data` as JSON. Returns False (and logs) on failure."""
    tmp = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        return True
    except OSError as exc:
        log.error("config save failed for %s: %s", path, exc)
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        return False


def config_dir_for(legacy_path: str) -> str:
    """`…/config.json` → `…/config/` — where the split store files live."""
    return os.path.join(os.path.dirname(os.path.abspath(legacy_path or
                                                        "config.json")),
                        "config")
