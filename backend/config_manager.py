"""Configuration facade over the split stores (config/*.json).

The 2026-09-09 refactor split the single config.json into seven
purpose-named files, each owned by exactly one store (stores/ package)
with atomic saves. This class keeps the historical ConfigManager API —
`get/set/get_copy/save/get_state/set_state/named_*/validate`, `DEFAULTS`,
`MAX_STACK_HISTORY`, `_path` — and routes every access to the owning
store, so the six backend consumers and every existing test keep working
unchanged. New code receives the specific store it needs via DI instead.

The parts (Round J step J-3) live next door, and the imports go one way:

* `backend/config_defaults.py` — the shipped tree (`DEFAULTS`), the undo cap,
  `SECTION_ROUTES`, and the two pure tree helpers;
* `backend/config_owners.py` — the `_Owner` family: which store holds a
  section and how it keeps it;
* `backend/config_view.py` — `ConfigView`, the base class holding the
  whole-tree read and the `state.*` surface.

What stays here: construction (the stores, the owners, the one-time legacy
migration), `load`/`save`, the section-level verbs and `validate`.

File map (see stores/migration.py):
    config/settings.json    chrome/scroll/delays/ui/history/collector
    config/presets.json     stack_presets, template_presets
    config/bookmarks.json   url_presets
    config/blocks.json      custom_blocks
    config/labels.json      the legacy labels section (offline fallback)
    config/session.json     state.* (except the undo timeline)
    config/undo.json        state.undo_history + undo_history_index
"""

# ideal-size: the facade keeps the constructor and the section-level verbs;
# the defaults, the owners and the merged view are in config_defaults.py /
# config_owners.py / config_view.py (Round J step J-3). The historical
# public names (`DEFAULTS`, `MAX_STACK_HISTORY`, `json_dumps`) and the two
# private ones the tests inspect (`_OWNERS`, `_SECTION_ROUTES`) are re-exported
# below, because that is where the rest of the tree has always imported them.

from __future__ import annotations

import copy
import logging
import os
from typing import Any

from stores.jsonio import config_dir_for
from stores.migration import migrate_legacy_config
from stores.settings_store import SettingsStore
from stores.bookmark_store import BookmarkStore
from stores.block_store import BlockStore
from stores.session_store import SessionStore
from stores.undo_store import UndoStore
from stores.labels_file_store import LabelsFileStore
from stores.preset_store import PresetStore
from stores.window_preset_store import WindowPresetStore

from backend import config_owners as owners
from backend import config_defaults
from backend.config_defaults import (                      # noqa: F401
    DEFAULTS, MAX_STACK_HISTORY, SECTION_ROUTES as _SECTION_ROUTES,
)
from backend.config_owners import OWNERS as _OWNERS         # noqa: F401
from backend.config_view import ConfigView

log = logging.getLogger("chatbot")


class ConfigManager(ConfigView):
    """Load, access, and persist configuration across the split stores."""

    def __init__(self, path: str = "config.json"):
        self._path = path
        self._dir = config_dir_for(path)
        # one-time split of a legacy single-file install
        try:
            migrate_legacy_config(os.path.abspath(path), self._dir)
        except Exception as exc:                      # noqa: BLE001
            log.warning("config migration skipped: %s", exc)
        os.makedirs(self._dir, exist_ok=True)
        self.settings = SettingsStore(os.path.join(self._dir,
                                                   "settings.json"))
        self.bookmarks = BookmarkStore(os.path.join(self._dir,
                                                    "bookmarks.json"))
        self.blocks = BlockStore(os.path.join(self._dir, "blocks.json"))
        self.session = SessionStore(os.path.join(self._dir,
                                                 "session.json"))
        self.undo = UndoStore(os.path.join(self._dir, "undo.json"))
        self.labels_file = LabelsFileStore(os.path.join(self._dir,
                                                        "labels.json"))
        # PresetStore caches per path, so this is the same instance the
        # bridge constructs with PresetStore(config=self)
        self.presets = PresetStore(config=self)
        self.window_presets = WindowPresetStore(config=self)
        self._owners = owners.build(self)
        log.info("Config loaded from %s", self._dir)

    # ── persistence ──────────────────────────────────────────────
    def load(self) -> None:
        """Re-read every store file from disk."""
        self.settings.load()
        self.bookmarks.load()
        self.blocks.load()
        self.session.load()
        self.undo.reload()
        self.labels_file.reload()
        self.presets.load()
        self.window_presets.load()

    def save(self) -> None:
        """Flush every dirty store (each save is atomic per file)."""
        self.settings.save()
        self.bookmarks.save()
        self.blocks.save()
        self.session.save()
        self.undo.flush()
        self.labels_file.flush()
        self.presets.save()
        self.window_presets.save()

    # ── access ───────────────────────────────────────────────────
    def get(self, *keys: str, default: Any = None) -> Any:
        if not keys:
            return default
        section, rest = keys[0], keys[1:]
        return owners.owner_for(self, section).read(section, rest, default)

    def get_copy(self, *keys: str, default: Any = None) -> Any:
        """Deep copy of the value so callers can mutate it safely."""
        return copy.deepcopy(self.get(*keys, default=default))

    def set(self, *keys_and_value: Any) -> None:
        *keys, value = keys_and_value
        if not keys:
            return
        section, rest = keys[0], keys[1:]
        owners.owner_for(self, section).write(section, rest, value)

    # ── named sub-stores (presets keyed by name) ─────────────────
    def named_all(self, section: str) -> dict[str, Any]:
        return owners.owner_for(self, section).named_all(section)

    def named_get(self, section: str, name: str, default: Any = None) -> Any:
        return owners.owner_for(self, section).named_get(section, name, default)

    def named_set(self, section: str, name: str, value: Any,
                  save: bool = True) -> None:
        owners.owner_for(self, section).named_set(section, name, value)
        if save:
            self.save()

    def named_delete(self, section: str, name: str,
                     save: bool = True) -> bool:
        ok = owners.owner_for(self, section).named_delete(section, name)
        if ok and save:
            self.save()
        return ok

    # ── validation ───────────────────────────────────────────────
    def validate(self) -> list[str]:
        return self.settings.validate()

    # ── the routing questions, answered by the owners module ─────
    def _owner_for(self, section: str):
        """The owner of a section. Part of the tested surface (the owners are
        per-store singletons and `named_*` routes on identity), so the private
        name stays on the class as a delegation."""
        return owners.owner_for(self, section)

    def _store_for(self, section: str):
        """Legacy name kept for tests and the bridge: it answers with the raw
        store behind a section, through the owner that knows how to read it."""
        return owners.store_for(self, section)


def json_dumps(data: Any) -> str:
    """The project's JSON spelling, for the callers that import it from here.

    Defined rather than re-imported: the API snapshot records it as this
    module's public function, and the implementation still has exactly one
    home (`config_defaults.json_dumps`).
    """
    return config_defaults.json_dumps(data)


__all__ = ["ConfigManager", "DEFAULTS", "MAX_STACK_HISTORY", "json_dumps"]
