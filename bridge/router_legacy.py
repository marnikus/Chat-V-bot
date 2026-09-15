"""Router legacy surface — the compat half of the wire object.

Part of the `router` family (entry point: `bridge/router.py`, Round J step
J-5). Everything here exists because the test suite (and, historically, the
pre-Router `Bridge`) is the contract, and the QWebChannel object has to keep
answering to it:

* the write-through properties (`_config`, `_memory`, `_cdp`, … onto the
  shared `BridgeContext`), so `Bridge.__new__` plus manual attribute injection
  still works and a later `sync_services()` still sees the change;
* `label_store` / `db_manager` / `_undo_pendings`, which reach through the
  context instead of owning state;
* the instance methods the tests drive directly (`_refresh_users`,
  `_do_delete_*`, `_get_/`_set_`/`_push_` history and undo shims) — one-line
  delegations to the domain bridge or the undo service.

Nothing here holds state, and nothing here is a slot the JS page calls: the
live wire surface lives in `bridge/router.py`, the class itself is assembled in
`bridge/router_assembly.py`. This module registers into that module's
`_ROUTER_METHODS` at import time; `bridge/router.py` imports it *before* it
builds the class, which is the only ordering constraint in the family.
"""

from __future__ import annotations

from bridge.label_bridge import LabelBridge
from bridge.people_bridge import PeopleBridge
from bridge.router_assembly import _ROUTER_METHODS, _router_method
from services.run import normalize_blocks

def _ctx_property(field, setter_sync=True):
    def getter(self):
        ctx, _bridges = self._ensure_ctx()
        return getattr(ctx, field)

    def setter(self, value):
        ctx, _bridges = self._ensure_ctx()
        setattr(ctx, field, value)
        if setter_sync:
            ctx.sync_services()
    return property(getter, setter)


for _field in ("cdp", "memory", "criteria", "engine", "config", "presets",
               "labels", "dbs"):
    _ROUTER_METHODS["_" + _field] = _ctx_property(_field)
_ROUTER_METHODS["_history"] = _ctx_property("archive")
_ROUTER_METHODS["_archive"] = property(
    lambda self: getattr(self._ctx, "archive", None))


def _label_store(self):
    ctx, _bridges = self._ensure_ctx()
    return ctx.label_store()


def _db_manager(self):
    ctx, _bridges = self._ensure_ctx()
    manager = ctx.db_manager()
    if ctx.archive is not None:
        manager.attach(ctx.archive)
    return manager


_ROUTER_METHODS["label_store"] = property(_label_store)
_ROUTER_METHODS["db_manager"] = property(_db_manager)


@_router_method

# ── legacy instance methods used by tests ──────────────────────────
@_router_method
async def _refresh_users(self):
    await self._bridge(PeopleBridge)._refresh_users_async()


@_router_method
async def _do_delete_one(self, nick):
    await self._bridge(PeopleBridge)._do_delete_one(nick)


@_router_method
async def _do_delete_many(self, nicks):
    await self._bridge(PeopleBridge)._do_delete_many(nicks)


@_router_method
async def _do_set_messaged(self, nick, messaged):
    await self._bridge(PeopleBridge)._do_set_messaged(nick, messaged)


@_router_method
async def _do_reset(self):
    await self._bridge(PeopleBridge)._do_reset()


@_router_method
async def _do_clear(self):
    await self._bridge(PeopleBridge)._do_clear()


@_router_method
async def _people_rows(self):
    ctx, _b = self._ensure_ctx()
    return await ctx.people.rows()


@_router_method
def _push_people_entry(self, before, after):
    if before == after:
        return False
    ctx, _b = self._ensure_ctx()
    result = ctx.undo.push("people",
                          {"before": before, "after": after})
    return bool(result.is_ok)


@_router_method
def _labels_for_nicks(self, nicks):
    ctx, _b = self._ensure_ctx()
    return ctx.people.labels_for_nicks(nicks)


@_router_method
def _install_label_guard(self):
    self._bridge(LabelBridge).install_label_guard()


@_router_method
def _get_global_history(self):
    ctx, _b = self._ensure_ctx()
    return ctx.undo.history()


@_router_method
def _set_global_history(self, history, index):
    ctx, _b = self._ensure_ctx()
    ctx.undo.set_history(history, index)


def _undo_pendings(self):
    """Pending world-undo save tasks (compat: tests drain them)."""
    ctx, _b = self._ensure_ctx()
    return getattr(ctx.undo, "_undo_pendings", [])


_ROUTER_METHODS["_undo_pendings"] = property(_undo_pendings)


@_router_method
def _push_global(self, kind, value):
    ctx, _b = self._ensure_ctx()
    result = ctx.undo.push(kind, value)
    return result.value if result.is_ok else None


@_router_method
def _get_history(self):
    ctx, _b = self._ensure_ctx()
    return ctx.undo.stack_projection()


@_router_method
def _set_history(self, history, index, save=True):
    ctx, _b = self._ensure_ctx()
    ctx.undo.set_stack_projection(history, index)


@_router_method
def _push_history(self, blocks):
    ctx, _b = self._ensure_ctx()
    return ctx.undo.push_stack(blocks)


@_router_method
def _get_hist(self, kind):
    ctx, _b = self._ensure_ctx()
    return ctx.undo.kind_projection(kind)


@_router_method
def _set_hist(self, kind, hist, idx):
    ctx, _b = self._ensure_ctx()
    if kind == "stack":
        ctx.undo.set_stack_projection(hist, idx)
    else:
        entries = [ctx.undo._history_entry(kind, value)
                   for value in hist]
        ctx.undo.set_history(entries,
                             max(-1, min(idx, len(entries) - 1)))


@_router_method
def _push_hist(self, kind, value):
    ctx, _b = self._ensure_ctx()
    if kind == "stack":
        value = normalize_blocks(value)
    ctx.undo.push(kind, value)
    return ctx.undo.kind_projection(kind)
