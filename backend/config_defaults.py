"""The shipped configuration tree and the pure helpers that shape it.

Part of the `config_*` family (facade: `backend/config_manager.py`, Round J
step J-3). Three things live here, and none of them touch a file:

* `DEFAULTS` / `MAX_STACK_HISTORY` — the compatibility default tree (the merged
  view of every store's defaults) and the undo-history cap. Both keep their
  historical `backend.config_manager` import path via a re-export there, which
  is what the snapshot records;
* `SECTION_ROUTES` — which section belongs to which store, the one table the
  facade's dispatch reads. `history_query`'s `SORT_COLUMNS` and this dict are
  the same idea in two places: *the section name is a whitelist, not a path*;
* `deep_merge` / `set_nested` — the two tree operations the settings owner and
  the merged view need. They are total on purpose: a value that a human edited
  into the wrong shape degrades to something usable instead of raising.

The private names keep their underscore: `SECTION_ROUTES` is the facade's and
its owners' business, and `UNSET` is the not-found sentinel both of them
compare identity against.
"""

from __future__ import annotations

import copy
import json
from typing import Any

#: re-exported: the owners fall back to it per key, and one import of the
#: store's defaults is enough for the whole family
from stores.settings_store import SETTINGS_DEFAULTS
from stores.bookmark_store import DEFAULT_BOOKMARKS
from stores.labels_file_store import LABELS_DEFAULT

MAX_STACK_HISTORY = 100

#: Compatibility default tree — the merged view of all store defaults.
#: Kept because bridge code and tests import DEFAULTS to reason about
#: fallbacks; writes never go here.
DEFAULTS: dict[str, Any] = dict(SETTINGS_DEFAULTS)
DEFAULTS.update({
    "url_presets": list(DEFAULT_BOOKMARKS),
    "stack_presets": {},
    "template_presets": {},
    "custom_blocks": [],
    "labels": copy.deepcopy(LABELS_DEFAULT),
    "state": {
        "undo_history": [],
        "db_recent": [],
        "my_nick_recent": [],
        "undo_history_index": -1,
        "grid_layout": None,
        "block_config_pinned": False,
        "window_states": {"closed": [], "minimized": []},
        "window_geometry": None,
        "grid_layout_history": [],
        "grid_layout_history_index": -1,
    },
})

#: state keys owned by the undo store rather than the session store
UNDO_STATE_KEYS = ("undo_history", "undo_history_index")

#: Top-level keys routed away from the settings store, to the STORE that owns
#: them (the attribute name on `ConfigManager`, which is also the key of
#: `_OWNERS` below). An unlisted section belongs to `settings.json`.
SECTION_ROUTES = {
    "url_presets": "bookmarks",
    "custom_blocks": "blocks",
    "labels": "labels_file",
    "stack_presets": "presets",
    "template_presets": "presets",
    # named things the AI feature lets the user create, edit and delete;
    # `presets.json` is this repo's ONE mechanism for exactly that.
    "ai_connections": "presets",
    "prompt_presets": "presets",
}

UNSET = object()


# ── section owners ───────────────────────────────────────────────
#
# Every store answers the same three verbs, so the facade dispatches once
# instead of re-deriving "which store is this, and what shape does it keep
# data in" inside `get()` and `set()`. That dispatch used to be a five-branch
# `if/elif` chain in each of them (nesting 14 in `set()`), which is exactly
# where the "a section is a string now" class of bug lived: the chain had to
# know each store's quirks, and adding a section meant editing both.
#
# `read()`/`write()` take the REST of the key path (the section is already
# routed away) and are total: a hostile path degrades to the caller's
# default instead of raising, because these values come out of a file a human
# may have edited.

def deep_merge(base: dict, overlay: Any) -> dict:
    """`overlay` on top of `base`, dict by dict.

    A non-dict in the overlay wins wholesale — that is how a section that a
    malformed `set()` flattened into a scalar stays visible instead of
    crashing the merge.
    """
    if not isinstance(overlay, dict):
        return overlay
    out = dict(base)
    for key, value in overlay.items():
        current = out.get(key)
        out[key] = (deep_merge(current, value)
                    if isinstance(current, dict) and isinstance(value, dict)
                    else value)
    return out


def set_nested(tree: Any, path, value) -> bool:
    """Write `value` at `path` inside `tree`, creating the dicts on the way."""
    node = tree
    for key in path[:-1]:
        if not isinstance(node, dict):
            return False
        if not isinstance(node.get(key), dict):
            node[key] = {}
        node = node[key]
    if not isinstance(node, dict):
        return False
    node[path[-1]] = value
    return True


def json_dumps(data: Any) -> str:
    """The project's JSON spelling: un-escaped non-ASCII, compact separators.

    One place decides it, because the same tree is written to a file, sent
    over the wire and logged — and a Cyrillic nick should be readable in all
    three.
    """
    return json.dumps(data, ensure_ascii=False)
