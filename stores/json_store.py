"""`JsonFileStore` — the one lifecycle every config-file store shares.

Design ref: docs/REFACTOR_2026-09-09_AREA_B_DESIGN.md §1.1 (plan P1-3).

Seven stores in this package each own one small JSON file, and each had grown
its own dialect of the same three operations: two constructor spellings
(`path` for `ConfigManager`, `AtomicJsonStore` for the store tests — so
`SessionStore(atomic)` died with a `TypeError`), three names for "persist"
(`save`, `flush`, or none at all), and `save()` returning a `Result` in one
file and a `bool` in another. `backend/config_manager.py` had to remember
which store spoke which dialect. This base is that memory, written down once:

  * **construction** — `Store(atomic | path, *, data=None)`; the payload of a
    borrowed `AtomicJsonStore` is deliberately re-read from disk, because the
    *file* is the contract, not the object;
  * **state** — the live payload is `self._data` (a subclass owns its
    projections of it), and every read hands out a deep copy;
  * **`load()` / `reload()`** — read from disk, clear `dirty`;
  * **`save(force=False)` / `flush()`** — a `bool` answering "does the file
    match memory now?"; `SAVE_ALWAYS` stores (the two that used to write
    inside every mutation) persist unconditionally, the overlay stores only
    when they are dirty or `force` is set.

A store adds its own API on top and overrides `_coerce` to normalise what it
read. It must not override `save`/`flush`/`load`: that is the whole point.
"""

from __future__ import annotations

import copy
import os
from typing import Any

from stores.atomic import AtomicJsonStore, _coerce_path
from stores.jsonio import load_json

class JsonFileStore:
    """Load / mutate / atomic-save one JSON file."""

    #: the file used when the caller names none (the pre-split single file)
    DEFAULT_FILE = "config.json"
    #: the shape of a fresh install
    DEFAULTS: dict[str, Any] = {}
    #: True for the stores whose every write used to hit the disk at once
    SAVE_ALWAYS = False

    def __init__(self, atomic: Any = None, path: str = "",
                 *, data: Any = None) -> None:
        self._dirty = False
        self._data: dict[str, Any] = {}
        # Another store may be passed to share its handle, and a path may be
        # passed in either slot (`Store("config.json")` is what
        # `ConfigManager` has always done).
        if isinstance(atomic, JsonFileStore):
            atomic, path = atomic._borrowed or atomic._owned, atomic._path
        self._borrowed: AtomicJsonStore | None = \
            atomic if isinstance(atomic, AtomicJsonStore) else None
        self._owned: AtomicJsonStore | None = None
        self._path = (self._borrowed.path if self._borrowed is not None
                      else _coerce_path(atomic if self._borrowed is None
                                        and atomic not in (None, "") else path,
                                        self.DEFAULT_FILE))
        # Construction reads the FILE — never the borrowed handle's memory:
        # an unsaved change in somebody else's `AtomicJsonStore` is not this
        # store's state until it has been written (B1-03). `load()` below goes
        # through the handle, so a borrowed one stays in step afterwards.
        self._data = (self._coerce(load_json(self._path, default={}))
                      if data is None else self._coerce(data))

    def _file(self) -> AtomicJsonStore:
        """The atomic handle this store reads and writes through.

        A borrowed `AtomicJsonStore` is used as given, so a write lands in the
        object the caller is watching. Otherwise the handle follows
        `self._path`, which keeps re-pointing a store (the way
        `tests/test_stores_split.py` does to prove one file cannot damage
        another) working exactly as it reads.
        """
        if self._borrowed is not None:
            return self._borrowed
        if self._owned is None or self._owned.path != self._path:
            self._owned = AtomicJsonStore(self._path)
        return self._owned

    # ── normalisation ────────────────────────────────────────────
    def _coerce(self, raw: Any) -> dict[str, Any]:
        """The payload as stored. A non-dict file is an empty one."""
        return copy.deepcopy(raw) if isinstance(raw, dict) \
            else copy.deepcopy(self.DEFAULTS)

    # ── the shared lifecycle ─────────────────────────────────────
    @property
    def path(self) -> str:
        return os.fspath(self._path)

    @property
    def dirty(self) -> bool:
        """True while memory holds a change the file has not seen."""
        return self._dirty

    def data(self) -> dict[str, Any]:
        """A copy of the whole payload — the caller cannot corrupt the store."""
        return copy.deepcopy(self._data)

    def load(self) -> None:
        """Re-read from disk (unsaved work in a borrowed atomic is not ours)."""
        self._data = self._coerce(self._file().load())
        self._dirty = False

    def reload(self) -> None:
        """`load()` under the name `ConfigManager.load()` uses for some stores."""
        self.load()

    def save(self, force: bool = False) -> bool:
        """Persist the payload. True when the file now matches memory."""
        if not (force or self.SAVE_ALWAYS or self._dirty):
            return True
        handle = self._file()
        handle.replace(copy.deepcopy(self._data))
        if handle.save().is_ok:
            self._dirty = False
            return True
        return False

    def flush(self) -> bool:
        """`save()` under the name `ConfigManager.save()` uses for some stores."""
        return self.save()

    # ── mutation bookkeeping for subclasses ──────────────────────
    @staticmethod
    def _wants_save(save: Any, save_now: Any = None,
                    default: bool = True) -> bool:
        """Resolve the two spellings of "persist this write now".

        `core/interfaces.py` documents `save=`, the ConfigManager facade has
        always passed `save_now=`; an explicit `False` on either wins over the
        default.
        """
        wanted = save if save is not None else (
            save_now if save_now is not None else default)
        return bool(wanted)

    def _touch(self) -> None:
        """Memory moved: mark it, and (for the inline writers) persist now."""
        self._dirty = True
        if self.SAVE_ALWAYS:
            self.save()
