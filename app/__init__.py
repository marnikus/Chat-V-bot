"""App package — lazy imports to avoid Qt tax for pure tests.

Design: docs/archive/2026-09-14-test-arch-redesign/TEST_ARCH_REDESIGN_2026-09-14.md
Old __init__.py imported bootstrap (which imports Qt) at package import time,
so `from app.lifecycle import ...` paid Qt cost even though lifecycle itself
is pure. Now we use PEP 562 __getattr__ for lazy loading.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

__all__ = ["ApplicationLifecycle", "MainWindow", "create_container", "create_window", "queue_path"]

_LAZY = {
    "ApplicationLifecycle": ("app.lifecycle", "ApplicationLifecycle"),
    "MainWindow": ("app.window", "MainWindow"),
    "create_container": ("app.bootstrap", "create_container"),
    "create_window": ("app.window", "create_window"),
    "queue_path": ("app.bootstrap", "queue_path"),
}

if TYPE_CHECKING:
    from app.bootstrap import create_container, queue_path
    from app.lifecycle import ApplicationLifecycle
    from app.window import MainWindow, create_window


def __getattr__(name: str):
    if name in _LAZY:
        mod_name, attr = _LAZY[name]
        mod = importlib.import_module(mod_name)
        val = getattr(mod, attr)
        globals()[name] = val
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(list(globals().keys()) + __all__)
