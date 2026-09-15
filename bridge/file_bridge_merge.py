"""File bridge merge — extracted from file_bridge_orchestration (H-C5 split)

Library merge, ≤80 LOC.
"""

from __future__ import annotations

import logging

log = logging.getLogger("chatbot")


def merge_library(bridge: "FileBridge", entries) -> "tuple[int, int]":
    if not entries or bridge.ctx.config is None:
        return 0, 0
    store = bridge.ctx.config.blocks
    items = store.all()
    added = replaced = 0
    for entry in entries:
        name = entry.get("name", "")
        existed = any(b.get("name") == name for b in items)
        result = store.save_custom_block(name, entry["block"])
        if result.is_err:
            bridge._log(f"⚠ Block “{name}” not saved: {result.err().detail}", "warn")
            continue
        if existed:
            replaced += 1
        else:
            added += 1
    if added or replaced:
        bridge.ctx.config.save()
    return added, replaced
