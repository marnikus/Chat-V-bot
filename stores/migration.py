"""Migration — split legacy single-file config.json into new stores.

Idempotent: if the new layout already exists, nothing is overwritten.
Legacy file is backed up to config.json.bak.<timestamp> before mutation.
"""

from __future__ import annotations

import os
import json
import copy
import shutil
from datetime import datetime
from typing import Any

from stores.atomic import AtomicJsonStore
from stores.bookmark_store import DEFAULT_BOOKMARKS
from stores.jsonio import save_json
from stores.labels_file_store import LABELS_DEFAULT

# legacy defaults mirrored from backend/config_manager.py
LEGACY_DEFAULTS: dict[str, Any] = {
    "chrome": {"host": "127.0.0.1", "port": 9222},
    "scroll": {"scroll_delta_y": 300},
    "delays": {"global_pre_action_ms": 500},
    "ui": {"theme": "dark"},
    "url_presets": ["https://ru.virt-chat.com/chat"],
    "history": {"enabled": True, "db_path": "history.db"},
    "collector": {"enabled": True, "my_nick": ""},
    "labels": {"defs": [], "assign": {}, "filter": {"include": [], "exclude": []}, "next_id": 0},
    "stack_presets": {},
    "template_presets": {},
    "custom_blocks": [],
    "state": {"undo_history": [], "undo_history_index": -1, "grid_layout": None},
}

# new per-file mapping (still sharing one JSON file in phase 1; future: separate files)
SLICE_KEYS = {
    "settings": ["chrome", "scroll", "delays", "ui", "history", "collector", "labels"],
    "bookmarks": ["url_presets"],
    "blocks": ["stack_presets", "template_presets", "custom_blocks"],
    "session": ["state"],
}


def migrate(path: str = "config.json", dry_run: bool = False) -> dict[str, Any]:
    """Migrate legacy config.json to new store layout.

    Returns {"migrated": bool, "backup": str | None, "added": list[str]}.
    """
    if not os.path.exists(path):
        # create fresh file with defaults so new installs start clean
        atomic = AtomicJsonStore(path)
        if not atomic.data():
            atomic._data = copy.deepcopy(LEGACY_DEFAULTS)
            if not dry_run:
                atomic.save()
            return {"migrated": True, "backup": None, "added": ["fresh_defaults"]}
        return {"migrated": False, "backup": None, "added": []}

    with open(path, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            return {"migrated": False, "backup": None, "added": [], "error": "invalid json"}

    # backup
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    backup = f"{path}.bak.{stamp}"
    added: list[str] = []
    migrated = False

    # Ensure each top-level key exists (no data loss: missing keys are added, existing ones kept)
    for key, default in LEGACY_DEFAULTS.items():
        if key not in data:
            data[key] = copy.deepcopy(default)
            added.append(key)
            migrated = True

    # Ensure state sub-keys
    state = data.get("state", {})
    if isinstance(state, dict):
        for k, v in LEGACY_DEFAULTS["state"].items():
            if k not in state:
                state[k] = copy.deepcopy(v)
                added.append(f"state.{k}")
                migrated = True
        data["state"] = state

    if migrated and not dry_run:
        try:
            shutil.copy2(path, backup)
        except OSError:
            backup = None
        atomic = AtomicJsonStore(path)
        atomic._data = data
        atomic.save()
    else:
        backup = None

    return {"migrated": migrated, "backup": backup, "added": added}


def needs_migration(path: str = "config.json") -> bool:
    res = migrate(path, dry_run=True)
    return bool(res.get("migrated"))


# ── phase 2: legacy single file → 7 split files ──────────────────────
# Sections owned by settings.json (mirrors SettingsStore.DEFAULTS slices).
_SETTINGS_SECTIONS = ("chrome", "scroll", "delays", "ui", "history",
                      "collector")


def migrate_legacy_config(legacy_abspath: str,
                          config_dir: str) -> dict[str, Any]:
    """Split a legacy single-file config.json into the 7 store files.

    Idempotent: once ``settings.json`` exists the legacy file is left
    untouched (stores win). A missing/unreadable legacy file is a fresh
    install (nothing written); a corrupt one is kept for repair. On
    success the legacy file is renamed to
    ``config.json.migrated-<UTC-stamp>`` — archived, never deleted.

    Returns ``{"migrated": bool, "archived": str | None}``.
    """
    done = {"migrated": False, "archived": None}
    if os.path.exists(os.path.join(config_dir, "settings.json")):
        return done  # already migrated — stores win, legacy untouched
    try:
        with open(legacy_abspath, "r", encoding="utf-8") as fh:
            legacy = json.load(fh)
    except (OSError, ValueError, UnicodeDecodeError):
        return done  # missing or corrupt — fresh defaults, file kept
    if not isinstance(legacy, dict):
        legacy = {}

    settings = {k: legacy[k] for k in _SETTINGS_SECTIONS if k in legacy}
    bookmarks = legacy.get("url_presets")
    if not isinstance(bookmarks, list):
        bookmarks = list(DEFAULT_BOOKMARKS)
    blocks = legacy.get("custom_blocks")
    if not isinstance(blocks, list):
        blocks = []
    stack = legacy.get("stack_presets")
    template = legacy.get("template_presets")
    presets = {"stack_presets": stack if isinstance(stack, dict) else {},
               "template_presets": (template if isinstance(template, dict)
                                    else {})}
    labels = legacy.get("labels")
    labels = {**copy.deepcopy(LABELS_DEFAULT),
              **(labels if isinstance(labels, dict) else {})}
    state = legacy.get("state")
    state = state if isinstance(state, dict) else {}
    session = {k: v for k, v in state.items()
               if k not in ("undo_history", "undo_history_index")}
    history = state.get("undo_history")
    try:
        index = int(state.get("undo_history_index", -1))
    except (TypeError, ValueError):
        index = -1
    undo = {"history": list(history) if isinstance(history, list) else [],
            "index": index}

    save_json(os.path.join(config_dir, "settings.json"), settings)
    save_json(os.path.join(config_dir, "bookmarks.json"), bookmarks)
    save_json(os.path.join(config_dir, "blocks.json"), blocks)
    save_json(os.path.join(config_dir, "presets.json"), presets)
    save_json(os.path.join(config_dir, "labels.json"), labels)
    save_json(os.path.join(config_dir, "session.json"), session)
    save_json(os.path.join(config_dir, "undo.json"), undo)

    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    archived = os.path.join(os.path.dirname(os.path.abspath(legacy_abspath)),
                            f"config.json.migrated-{stamp}")
    try:
        os.rename(legacy_abspath, archived)
    except OSError:
        archived = None
    return {"migrated": True, "archived": archived}
