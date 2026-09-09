"""ActionRegistry — registration + lookup, nothing else.

Two ways to register (both end in the same table):

* implicit — subclass BaseAction with a ``block_id`` (``__init_subclass__``
  does the registration; this is what every shipped block uses);
* explicit — ``@ActionRegistry.register("ID")`` for aliases and adapters.

``scan()`` walks the actions/ package with pkgutil and imports every
module: dropping a new ``my_action.py`` file into actions/ registers it —
no central import list to edit (the Open/Closed fix).
"""

from __future__ import annotations

import logging
import pkgutil
from typing import Iterator, Optional, Type

log = logging.getLogger("chatbot")


class ActionRegistry:
    _classes: dict[str, Type] = {}
    #: modules that contain no action blocks (infrastructure)
    _SKIP_MODULES = frozenset({"base", "base_action", "registry",
                               "context", "__init__"})

    # ── registration ─────────────────────────────────────────────
    @classmethod
    def register(cls, block_id: str):
        """Class decorator: @ActionRegistry.register("PAUSE")."""

        def decorator(klass: Type) -> Type:
            klass.block_id = block_id
            cls.register_class(klass, block_id=block_id)
            return klass

        return decorator

    @classmethod
    def register_class(cls, klass: Type,
                       block_id: Optional[str] = None) -> None:
        block_id = block_id or getattr(klass, "block_id", "")
        if not block_id:
            return
        existing = cls._classes.get(block_id)
        if existing is not None and existing is not klass:
            in_package = (existing.__module__.startswith("actions.")
                          and klass.__module__.startswith("actions."))
            if in_package:
                # Two REAL blocks fighting over one id is a programming
                # error: fail loudly at import time.
                raise ValueError(
                    f"duplicate action id {block_id!r}: "
                    f"{existing.__module__}.{existing.__name__} vs "
                    f"{klass.__module__}.{klass.__name__}")
            # A test/adaptor shadowing a shipped block (the historical
            # last-wins semantics) is allowed — but never silently.
            log.warning("action id %r re-registered by %s.%s (was %s.%s)",
                        block_id, klass.__module__, klass.__name__,
                        existing.__module__, existing.__name__)
        cls._classes[block_id] = klass

    # ── lookup ───────────────────────────────────────────────────
    @classmethod
    def get(cls, block_id: str) -> Optional[Type]:
        return cls._classes.get(block_id)

    @classmethod
    def all_ids(cls) -> list[str]:
        return sorted(cls._classes)

    @classmethod
    def all_classes(cls) -> dict[str, Type]:
        return dict(cls._classes)

    @classmethod
    def clear(cls) -> None:
        """Tests only."""
        cls._classes.clear()

    # ── package scan ─────────────────────────────────────────────
    @classmethod
    def scan(cls, package=None) -> list[str]:
        """Import every module of the actions package; each import
        registers its blocks. Returns the ids found (idempotent)."""
        import actions as actions_pkg
        package = package or actions_pkg
        before = set(cls._classes)
        for module_info in pkgutil.iter_modules(package.__path__):
            if module_info.name in cls._SKIP_MODULES:
                continue
            __import__(f"{package.__name__}.{module_info.name}")
        new = sorted(set(cls._classes) - before)
        if new:
            log.info("action registry scanned: %d block(s) registered",
                     len(cls._classes))
        return new


def get_action_class(block_id: str) -> Optional[Type]:
    """Compatibility helper (engine + tests import this from base_action)."""
    return ActionRegistry.get(block_id)


def all_action_ids() -> list[str]:
    """Compatibility helper."""
    return ActionRegistry.all_ids()
