"""Run hooks levels — constants and normalize (H-C5 split)

≤100 LOC.
"""

from __future__ import annotations

import inspect

USER_SCOPED_BLOCKS = frozenset({"SCROLL_PARSE", "CONDITIONAL_SKIP", "CLICK_USER", "TYPE_MESSAGE", "CLICK_SEND", "ATTACH_IMAGE"})
STANDALONE_NICK = "—"
RETIRED_BLOCK_KEYS = frozenset({"use_panel_filters", "skip_if_backlog", "backlog_threshold"})
_LEVEL_MAP = {
    "ok": "success", "success": "success", "done": "success",
    "info": "info", "debug": "info", "warn": "warn",
    "warning": "warn", "error": "error", "fail": "error",
}


def normalize_blocks(blocks) -> list[dict]:
    clean = []
    for block in blocks or []:
        if not isinstance(block, dict):
            continue
        item = {k: v for k, v in block.items() if k not in RETIRED_BLOCK_KEYS and not str(k).startswith("_")}
        item.setdefault("enabled", True)
        if item["enabled"] is None:
            item["enabled"] = True
        clean.append(item)
    return clean


def norm_level(level: str) -> str:
    return _LEVEL_MAP.get((level or "info").lower(), "info")


async def maybe_await(value) -> None:
    if inspect.isawaitable(value):
        await value
