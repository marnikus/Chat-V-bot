"""One-time migration: the single legacy config.json → config/*.json.

Runs on first start after the split. Idempotent and fail-safe:

* no legacy file, or config/ already has store files → nothing to do;
* unreadable legacy JSON → nothing is written or renamed;
* every written file is atomic, and the legacy file is only RENAMED
  (``config.json.migrated-<ts>``), never deleted — the user's data is
  always recoverable by hand.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime

from stores.jsonio import save_json

log = logging.getLogger("chatbot")

#: top-level keys of the legacy file claimed by a dedicated store
CLAIMED_SECTIONS = frozenset({
    "url_presets", "stack_presets", "template_presets",
    "custom_blocks", "labels", "state",
})


def _store_files_present(config_dir: str) -> bool:
    if not os.path.isdir(config_dir):
        return False
    names = {"settings.json", "presets.json", "bookmarks.json",
             "blocks.json", "labels.json", "session.json", "undo.json"}
    return any(os.path.exists(os.path.join(config_dir, n))
               for n in names)


def migrate_legacy_config(legacy_path: str, config_dir: str) -> bool:
    """Split `legacy_path` into the seven store files under `config_dir`.

    Returns True when the legacy file was consumed (renamed away).
    """
    if not legacy_path or not os.path.exists(legacy_path):
        return False
    if _store_files_present(config_dir):
        return False              # already migrated (or user-provided)
    try:
        with open(legacy_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("legacy config %s unreadable (%s) — starting fresh",
                    legacy_path, exc)
        return False
    if not isinstance(data, dict):
        log.warning("legacy config %s is not an object — starting fresh",
                    legacy_path)
        return False

    os.makedirs(config_dir, exist_ok=True)
    state = data.get("state") if isinstance(data.get("state"), dict) else {}

    # 1 — settings: every dict section nobody else claims
    settings = {key: value for key, value in data.items()
                if key not in CLAIMED_SECTIONS}
    save_json(os.path.join(config_dir, "settings.json"), settings)

    # 2 — presets
    presets = {
        "stack_presets": data.get("stack_presets")
        if isinstance(data.get("stack_presets"), dict) else {},
        "template_presets": data.get("template_presets")
        if isinstance(data.get("template_presets"), dict) else {},
    }
    save_json(os.path.join(config_dir, "presets.json"), presets)

    # 3 — bookmarks
    bookmarks = (data.get("url_presets")
                 if isinstance(data.get("url_presets"), list) else [])
    save_json(os.path.join(config_dir, "bookmarks.json"), bookmarks)

    # 4 — custom blocks
    blocks = (data.get("custom_blocks")
              if isinstance(data.get("custom_blocks"), list) else [])
    save_json(os.path.join(config_dir, "blocks.json"), blocks)

    # 5 — labels (legacy config-backed section; live labels live in the
    #     world DB since the unified-DB redesign — this file is the
    #     migration source and the offline fallback)
    labels = data.get("labels")
    save_json(os.path.join(config_dir, "labels.json"),
              labels if isinstance(labels, dict) else {})

    # 6 — session state (everything except the undo timeline)
    session = {key: value for key, value in state.items()
               if key not in ("undo_history", "undo_history_index")}
    save_json(os.path.join(config_dir, "session.json"), session)

    # 7 — the undo timeline
    undo = {
        "history": state.get("undo_history")
        if isinstance(state.get("undo_history"), list) else [],
        "index": state.get("undo_history_index", -1)
        if isinstance(state.get("undo_history_index"), int) else -1,
    }
    save_json(os.path.join(config_dir, "undo.json"), undo)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    archived = f"{legacy_path}.migrated-{stamp}"
    try:
        os.replace(legacy_path, archived)
    except OSError as exc:
        log.warning("legacy config could not be renamed (%s) — it stays "
                    "next to config/ and is ignored from now on", exc)
    log.info("config.json split into config/ (original archived as %s)",
             os.path.basename(archived))
    return True


# Compatibility alias expected by newer callers.
migrate = migrate_legacy_config
