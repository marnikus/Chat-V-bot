"""The archive's settings and the My Nick detection.

Part of the `history_bridge` family (facade: `bridge/history_bridge.py`,
Round H step H-B1). Settings live on the archive when it is running (so
the collector sees them immediately) and fall back to the shared config
file when it is not — the two must agree, and they do because the archive
loads from that same config.

`detect_my_nick` reads the LIVE page state through the archive's parser
and answers on `history_stats_ready` (the frontend already listens there
for stats; detection is the same "tell me who is in this chat" question).
"""

from __future__ import annotations

import json

from core.events import LogMessage


def get_settings(bridge) -> str:
    if bridge.ctx.archive is None:
        return json.dumps(bridge.ctx.config.get_copy("history", default={}))
    return json.dumps(bridge.ctx.archive.settings(), ensure_ascii=False)


def save_settings(bridge, patch: dict) -> None:
    if bridge.ctx.archive is None:
        stored = bridge.ctx.config.get_copy("history", default={})
        stored.update(patch)
        bridge.ctx.config.set("history", stored)
        bridge.ctx.config.save()
        return
    bridge.ctx.archive.apply_settings(patch)
    bridge.ctx.bus.emit(LogMessage(message="💾 Archive settings saved",
                                   level="info"))


async def detect_my_nick(bridge, req_id: str) -> None:
    state = await bridge.ctx.archive.parser.state()
    bridge.history_stats_ready.emit(req_id, json.dumps(
        {"req_id": req_id, "detected": state.get("me") or "",
         "partner": state.get("partner") or ""},
        ensure_ascii=False))
