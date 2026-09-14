"""Deleting from the archive — person, message, trash, merge (RULE 12).

Part of the `history_bridge` family (facade: `bridge/history_bridge.py`,
Round H step H-B1). Every deletion here is REVERSIBLE through the undo
timeline, except the two paths that say so on purpose: `hard` (the rows are
erased, the label store forgets the person) and `purge_deleted` (the trash
is emptied). The undo tickets carry everything a reverse operation needs —
the op token, and for a person deletion the `people` table before and
after — and every outcome is announced on the bridge's `userdb_changed`
signal, which is what the windows watch.

Refusals (empty nick, bad message id, no archive) are the facade's job:
the @Slot has to answer `False` synchronously, before any of this runs.
"""

from __future__ import annotations

import json
import logging

from core.events import LogMessage, PeopleChanged

log = logging.getLogger("chatbot")


def _refresh_people(bridge) -> None:
    bridge.ctx.bus.emit(PeopleChanged(reason="archive"))


async def people_snapshot(bridge):
    """The people table as the User Memory shows it, or None when it cannot
    be read (no memory service, or the read fails)."""
    if bridge.ctx.memory is None:
        return None
    try:
        return await bridge.ctx.people.rows()
    except Exception as exc:                         # noqa: BLE001
        log.debug("people snapshot unavailable: %s", exc)
        return None


async def delete_person(bridge, clean: str, hard: bool) -> None:
    """Remove a person WITH their history (soft: one Ctrl+Z brings both
    halves back; hard: erased, and the label store forgets the person)."""
    archive = bridge.ctx.archive
    repo = archive.repo
    token = repo.new_op_token()
    people_before = await people_snapshot(bridge)
    ok = await repo.delete_person(clean, hard=bool(hard), token=token)
    if people_before is not None:
        try:
            await bridge.ctx.memory.delete_user(clean)
        except Exception as exc:                  # noqa: BLE001
            log.debug("people row for %s not removed: %s", clean, exc)
    people_after = await people_snapshot(bridge)
    if ok and not hard:
        entry = {"op": "delete_person", "nick": clean, "token": token}
        if people_before is not None and people_after is not None:
            entry["people"] = {"before": people_before,
                               "after": people_after}
        bridge.ctx.undo.push("archive", entry)
        bridge.ctx.bus.emit(LogMessage(
            message=f"🗑 “{clean}” and their history removed — "
                    "Ctrl+Z restores both", level="warn"))
    elif ok and hard:
        bridge.ctx.label_store().forget(clean)
        bridge.ctx.bus.emit(LogMessage(
            message=f"🔥 “{clean}” erased permanently "
                    "(not undoable)", level="warn"))
    bridge.userdb_changed.emit(json.dumps(
        {"action": "deleted", "nick": clean, "hard": bool(hard), "ok": ok},
        ensure_ascii=False))
    _refresh_people(bridge)


async def clear_person(bridge, clean: str) -> None:
    """Hide a person's messages without touching the person themselves."""
    archive = bridge.ctx.archive
    repo = archive.repo
    token = await repo.soft_delete_history(clean)
    if not token:
        if await repo.get_person(clean):
            await repo.reset_cursor(clean)
        bridge.ctx.bus.emit(LogMessage(
            message=f"ℹ “{clean}” has no messages to clear", level="info"))
    else:
        bridge.ctx.undo.push("archive", {
            "op": "clear_history", "nick": clean, "token": token})
        bridge.ctx.bus.emit(LogMessage(
            message=f"🧹 History of “{clean}” cleared — the person "
                    "stays in the database and the chat is "
                    "re-collected from scratch (Ctrl+Z restores "
                    "the messages)", level="warn"))
    collector = getattr(archive, "collector", None)
    if collector is not None:
        try:
            collector.person_cleared(clean)
        except Exception:                          # noqa: BLE001
            pass
    bridge.userdb_changed.emit(json.dumps(
        {"action": "cleared", "nick": clean, "ok": bool(token)},
        ensure_ascii=False))


async def delete_message(bridge, clean: str, mid: int) -> None:
    token = await bridge.ctx.archive.repo.soft_delete_message(clean, mid)
    if not token:
        bridge.ctx.bus.emit(LogMessage(
            message="⚠ That message is already gone", level="warn"))
        return
    bridge.ctx.undo.push("archive", {
        "op": "delete_message", "nick": clean, "token": token,
        "message_id": mid})
    bridge.ctx.bus.emit(LogMessage(
        message=f"🗑 One message removed from “{clean}” "
                "(Ctrl+Z restores it)", level="info"))
    bridge.userdb_changed.emit(json.dumps(
        {"action": "message_deleted", "nick": clean, "id": mid},
        ensure_ascii=False))


async def purge_deleted(bridge, nick: str) -> None:
    gone = await bridge.ctx.archive.repo.purge_deleted(
        " ".join(str(nick or "").split()).strip())
    bridge.ctx.bus.emit(LogMessage(
        message=f"🔥 {gone} hidden message(s) erased permanently",
        level="warn"))
    bridge.userdb_changed.emit(json.dumps(
        {"action": "purged", "nick": nick, "count": gone},
        ensure_ascii=False))


async def restore_person(bridge, nick: str) -> None:
    ok = await bridge.ctx.archive.repo.restore_person(nick)
    bridge.userdb_changed.emit(json.dumps(
        {"action": "restored", "nick": nick, "ok": ok},
        ensure_ascii=False))
    _refresh_people(bridge)


async def merge_persons(bridge, from_nick: str, into_nick: str) -> None:
    moved = await bridge.ctx.archive.repo.merge_persons(from_nick, into_nick)
    bridge.userdb_changed.emit(json.dumps(
        {"action": "merged", "nick": into_nick, "from": from_nick,
         "moved": moved}, ensure_ascii=False))
