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
