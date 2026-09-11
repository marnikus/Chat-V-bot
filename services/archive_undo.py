"""Re-applying / reversing archive delete ops — the undo side of the
tombstone model (RULE 14).

A soft delete hides rows under one operation token; an undo entry of kind
"archive" carries that token. This module re-applies (redo) or reverses
(undo) exactly one such op and announces EVERY outcome on the bus:

* success  → `UserDbChanged` (the windows refresh) +
             `ArchiveUndoApplied(ok=True)`;
* a state that can no longer be re-applied (the person row is gone, or
  its tombstone no longer matches the token — something changed after
  the delete) → an ERROR line + `UserDbChanged(action="undo_failed")` +
  `ArchiveUndoApplied(ok=False)`. Never a silent false success (bug
  report 2026-09-11: "undo reports success but silently fails").

The module stays deliberately small — this whole story should fit one
screen (RULE 18). `UndoService` keeps the timeline; the repo keeps the
rows; this is the honest in-between.
"""

import json

from core.events import (ArchiveUndoApplied, UserDbChanged)
from services.service_log import emit_log

#: the person row is gone for good (purged / world switched in between)
PERSON_GONE = "the person no longer exists in this database"

#: the rows are hidden under a different token now (state changed after
#: the delete — the HRP-13 guard in `restore_person` refuses)
TOMBSTONE_MISMATCH = ("the row's tombstone no longer matches this delete "
                      "(state changed after the delete)")


def _failure_line(forward: bool, op: str, nick: str, reason: str) -> str:
    return (f"❌ {'Redo' if forward else 'Undo'} failed for “{nick}” "
            f"({op}): {reason}")


async def re_hide_message(repo, value: dict, nick: str):
    """Redo of a single-message delete (its own token + row lookup)."""
    token = str(value.get("token") or "")
    if not await repo.soft_delete_message(
            nick, int(value.get("message_id") or 0), token=token):
        return ("", f"⚠ Redo found nothing to hide for “{nick}” — "
                    "the row is already gone")
    return ("", "")


async def apply_delete_forward(repo, value: dict):
    """Re-apply a delete (redo). Returns (failure_reason, warning)."""
    op = str(value.get("op") or "")
    nick = str(value.get("nick") or "")
    if op == "delete_message":
        return await re_hide_message(repo, value, nick)
    token = str(value.get("token") or "")
    if op == "clear_history":
        if not await repo.soft_delete_history(nick, token=token):
            return ("", f"⚠ Redo found no visible messages for “{nick}”")
    elif op == "delete_person":
        if not await repo.delete_person(nick, hard=False, token=token):
            return (PERSON_GONE, "")
    return ("", "")


async def apply_delete_restore(repo, value: dict):
    """Reverse a delete (undo). Returns (failure_reason, warning)."""
    op = str(value.get("op") or "")
    nick = str(value.get("nick") or "")
    token = str(value.get("token") or "")
    if op == "delete_person":
        if not await repo.get_person(nick):
            return (PERSON_GONE, "")
        if not await repo.restore_person(nick, token=token):
            return (TOMBSTONE_MISMATCH, "")
        return ("", "")
    restored = await repo.restore_deleted(nick, token)
    if not await repo.get_person(nick):
        return (PERSON_GONE, "")
    if not restored and token:
        # a token is only minted when ≥1 row was hidden; 0 back means the
        # rows were re-collected or purged while hidden — say so, don't
        # call it an error (the person and the rest of the state survive)
        return ("", f"⚠ Undo restored 0 messages for “{nick}” — the "
                    "hidden rows no longer exist (re-collected or "
                    "purged)")
    return ("", "")


async def apply_archive_op(bus, repo, value: dict, forward: bool) -> None:
    """Re-apply or reverse one archive delete op, announcing every
    outcome (see the module docstring for the success/failure events)."""
    op = str(value.get("op") or "")
    nick = str(value.get("nick") or "")
    if forward:
        failure, warning = await apply_delete_forward(repo, value)
    else:
        failure, warning = await apply_delete_restore(repo, value)
    if failure:
        emit_log(bus, _failure_line(forward, op, nick, failure), "error")
        bus.emit(UserDbChanged(payload=json.dumps(
            {"action": "undo_failed", "op": op, "nick": nick,
             "reason": failure}, ensure_ascii=False)))
        bus.emit(ArchiveUndoApplied(forward=forward, op=op, nick=nick,
                                    ok=False))
        return
    if warning:
        emit_log(bus, warning, "warn")
    bus.emit(UserDbChanged(payload=json.dumps(
        {"action": "undo" if not forward else "redo", "op": op,
         "nick": nick}, ensure_ascii=False)))
    bus.emit(ArchiveUndoApplied(forward=forward, op=op, nick=nick))
