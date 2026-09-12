"""Session-sized trash for the message archive (design §2.4).

A soft delete only hides rows. The tombstoned people, their hidden messages
and the undo step that knows their token are the *trash*: Ctrl+Z can reach
them only while the app run that created them is still alive. So the trash
dies with the run:

* `SESSION_TOKEN` is stamped into the world the first time this run opens it;
* `begin_session` erases the trash of a world whose stamp is older (a world
  left behind by a closed run) and stamps it with this run's token;
* `purge_tokens` erases exactly the rows one dropped undo step kept alive;
* `purge_trash` sweeps one person or the whole world;
* `open_world` is `begin_session` for the open / switch paths, where a failed
  sweep must be a warning rather than a world that will not open.

The functions take the `HistoryService` as `host` — the same collaborator
style the `runtime.py` split uses — so the service's method count does not
grow (`services/history/__init__.py` keeps the four public entry points as
one-line delegates). Imports point down only: nothing here imports
`services/undo_*`, `bridge/` or Qt.
"""

from __future__ import annotations

import logging
from uuid import uuid4

log = logging.getLogger("chatbot")

#: one token per app RUN: a world whose stored token differs was last opened
#: by a previous run, so the trash it still hides belongs to a closed session
#: and is erased on open (Ctrl+Z reaches back only within a session)
SESSION_TOKEN = uuid4().hex


async def begin_session(host) -> dict:
    """Open this world for THIS app run; erase a closed run's trash once."""
    if await host.db.get_meta("session", "") == SESSION_TOKEN:
        return {"persons": 0, "messages": 0}
    erased = await forget_old_trash(host)
    await host.db.set_meta("session", SESSION_TOKEN)
    return erased


async def open_world(host) -> None:
    """`begin_session` for the open / switch paths: a sweep never blocks them.

    Erasing a closed session's trash must not stop a world from opening or a
    switch from completing — the rows are unreachable anyway, so a failed
    sweep is a warning, not an error.
    """
    try:
        await begin_session(host)
    except Exception as exc:                            # noqa: BLE001
        log.warning("trash sweep on %s failed: %s", host.db.path, exc)


async def forget_old_trash(host) -> dict:
    """A world that was closed keeps neither its trash nor a way back to it.

    The hidden rows and tombstones go, and so do the archive undo entries
    that pointed at them — otherwise a later Ctrl+Z would promise a restore
    the rows can no longer deliver.
    """
    erased = await purge_trash(host, "")
    await host.db.execute("DELETE FROM undo_history WHERE kind='archive'")
    await host.db.commit()
    if erased["persons"] or erased["messages"]:
        log.info("world reopened: erased %d person(s) and %d hidden "
                 "message(s) left by a closed session",
                 erased["persons"], erased["messages"])
    return erased


async def purge_trash(host, nick: str = "") -> dict:
    """Erase what a soft delete only hid; `nick` narrows it to one person.

    With a nick the sweep covers that person's hidden messages and their
    tombstone; without one it is the whole world. Returns
    ``{"persons": n, "messages": m}``.
    """
    clean = " ".join(str(nick or "").split()).strip()
    people = await _trash_persons(host, clean)
    messages = int(await host.repo.purge_deleted(clean))
    _forget_labels(host, people)
    return {"persons": len(people), "messages": messages}


async def purge_tokens(host, tokens: list) -> dict:
    """Erase the rows kept alive by undo steps that are now gone.

    Called when the timeline drops an archive entry (the cap, or a new edit
    after an undo truncating the redo branch): nothing can reach those rows
    any more — above the undo memory, the data is lost.
    """
    clean = [str(t) for t in dict.fromkeys(tokens or []) if t]
    if not clean:
        return {"persons": 0, "messages": 0}
    marks = ",".join("?" * len(clean))
    params = tuple(clean)
    people = await host.db.fetchdicts(
        f"SELECT nick FROM persons WHERE deleted_at IN ({marks})", params)
    messages = int(await host.db.scalar(
        f"SELECT COUNT(*) FROM messages WHERE deleted_at IN ({marks})",
        params, 0))
    for row in people:                          # the person + their hidden rows
        await host.repo.purge_deleted(str(row["nick"]))
    await host.db.execute(
        f"DELETE FROM messages WHERE deleted_at IN ({marks})", params)
    await host.db.commit()
    _forget_labels(host, people)
    return {"persons": len(people), "messages": messages}


def _forget_labels(host, people: list) -> None:
    """Erased people leave no label rows behind."""
    for row in people:
        if host._labels is not None:
            host._labels.forget(row["nick"])


async def _trash_persons(host, nick: str) -> list:
    """The tombstoned persons a purge will erase (count + label cleanup)."""
    sql = "SELECT id, nick FROM persons WHERE deleted_at<>''"
    params: tuple = ()
    if nick:
        sql += " AND nick=?"
        params = (nick,)
    return await host.db.fetchdicts(sql, params)
