"""Outcome / Refusal — a `Result` whose truthiness means "something changed".

Design ref: docs/REFACTOR_2026-09-09_AREA_B_DESIGN.md §1.2.

`core/result.py` is frozen for every area, and it deliberately has no
__bool__: `Ok(None)` and `Err("…")` are both truthy there. Two callers of the
bookmark store ask a question that a plain `Ok` cannot answer:

    bridge/cdp_bridge.py:87   if self.ctx.config.bookmarks.add(url):   # toast
    stores/bookmark_store.py  add/remove → "did the list change?"

`BookmarkStoreProto` in `core/interfaces.py` documents the return as `bool`,
so the *truthiness* is the contract and the `Result` is the extra detail.
`Outcome`/`Refusal` are the two narrow subclasses that make both readings true
at once — a store can keep its `-> Result[...]` annotation while `if …:`
means what the proto says.

Nothing outside `stores/` imports this module; it exists so the config stores
have one vocabulary for "accepted / refused / no-op".
"""

from __future__ import annotations

from core.result import Err, Ok

__all__ = ["Outcome", "Refusal", "changed", "unchanged", "refused"]

class Outcome(Ok[bool]):
    """An accepted write. `True` = the payload changed, `False` = no-op.

    `Ok[bool]`, so `is_ok`, `.value`, `.unwrap()` and `.unwrap_or()` all keep
    working for code that reads the Result; `bool()` is the same answer for
    code that only asks "did anything happen?".
    """

    __slots__ = ()

    def __bool__(self) -> bool:
        return bool(self.value)

class Refusal(Err):
    """A write the store would not perform, with the reason to show or log."""

    __slots__ = ()

    def __bool__(self) -> bool:
        return False

def changed(value: bool = True) -> Outcome:
    """`Outcome(True)` — the payload moved."""
    return Outcome(bool(value))

def unchanged() -> Outcome:
    """`Outcome(False)` — a legal call that had nothing to do."""
    return Outcome(False)

def refused(code: str, detail: str = "") -> Refusal:
    """`Refusal` — a duplicate, an empty name, a write that could not land."""
    return Refusal(str(code), str(detail or ""))
