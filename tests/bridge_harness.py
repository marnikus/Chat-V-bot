"""Shared harness for the bridge/ test suite (Section D design).

Conventions follow the existing suite (test_people_undo.py):
  * real ConfigManager / UserMemory / sqlite on temp dirs;
  * `Bridge.__new__(Bridge)` + attribute injection where a module-scoped
    fixture is enough, the real constructor for wire-level tests;
  * no QApplication — Qt signals work for direct connect().

Every helper here exists so the tests assert observable *wire* behaviour
(returned JSON, emitted signals, store state) and never mere execution.
"""

import asyncio
import json
import os
import sys
import tempfile
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QObject  # noqa: E402

from backend.bridge import Bridge  # noqa: E402
from backend.config_manager import ConfigManager  # noqa: E402
from backend.user_memory import UserMemory, UserRecord  # noqa: E402


def run(coro):
    return asyncio.run(coro)


async def settle(ms=0.08):
    """Let scheduled coroutines run to completion."""
    await asyncio.sleep(ms)


class Recorder:
    """Record signal emissions: rec.calls == [(args, ...), ...]."""

    def __init__(self, *signals):
        self.calls = []
        for sig in signals:
            sig.connect(self)

    def __call__(self, *args):
        self.calls.append(args if len(args) != 1 else args[0])

    def clear(self):
        self.calls.clear()

    @property
    def payloads(self):
        out = []
        for c in self.calls:
            try:
                out.append(json.loads(c))
            except (TypeError, ValueError):
                out.append(c)
        return out


class FakeEngine:
    """ActionEngine stand-in: records calls, holds a stack."""

    def __init__(self, stack=None):
        self.stack = list(stack or [])
        self.calls = []
        self.running = False
        self.paused = False
        self.criteria = None
        self.composer_text = ""

    @property
    def is_running(self):
        return self.running

    def get_stack(self):
        return list(self.stack)

    def load_stack(self, blocks):
        self.calls.append(("load_stack", list(blocks)))
        self.stack = list(blocks)

    def run(self, *a, **k):
        self.calls.append(("run",))
        self.running = True

    async def execute(self, *a, **k):
        self.calls.append(("execute",))
        self.running = True

    def stop(self):
        self.calls.append(("stop",))
        self.running = False

    def pause(self):
        self.calls.append(("pause",))
        self.paused = True

    def resume(self):
        self.calls.append(("resume",))
        self.paused = False


def make_bare(**attrs):
    """A Router assembled the legacy-test way: __new__ + injection.
    Attributes are write-through onto the context — the historical names
    carry a leading underscore (`_config`, `_engine`, …); accept both
    spellings. Mirrors the real constructor's derivation: presets are
    auto-built from config when absent."""
    br = Bridge.__new__(Bridge)
    QObject.__init__(br)
    if attrs.get("presets") is None and attrs.get("config") is not None:
        from stores.preset_store import PresetStore
        attrs["presets"] = PresetStore(config=attrs["config"])
    for k, v in attrs.items():
        setattr(br, k if k.startswith("_") else "_" + k, v)
    return br


class TempWorld:
    """A temp directory with a config file. Usage: with TempWorld() as w:"""

    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        self.config_path = os.path.join(self.dir, "config.json")
        self.config = ConfigManager(self.config_path)

    def path(self, name):
        return os.path.join(self.dir, name)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.tmp.cleanup()


async def make_memory(world, name="users.db"):
    mem = UserMemory(world.path(name))
    await mem.init()
    return mem


def rec(nick, messaged=False, gender="female", message_count=0,
        last_messaged=None, notes=""):
    return UserRecord(nick=nick, gender=gender, guest=True,
                      messaged=messaged, message_count=message_count,
                      last_messaged=last_messaged, notes=notes)


async def seed(memory, *records):
    """The established convention (test_people_undo.py): upsert always
    starts a person unmessaged; flags change only via mark_messaged."""
    for r in records:
        await memory.upsert_user(r)
        if r.messaged:
            await memory.mark_messaged(r.nick)


def blocks(*ids):
    """A minimal CANONICAL block list (the form normalize_blocks produces)."""
    return [{"block_id": b, "params": {}, "enabled": True} for b in ids]


class BridgeCase(unittest.TestCase):
    """Base: a fresh Router wired to real temp config/memory per test."""

    def setUp(self):
        self.world = TempWorld()
        self.addCleanup(self.world.__exit__, None, None, None)
        self.engine = FakeEngine()
        self.bridge = make_bare(engine=self.engine, config=self.world.config)

    def stop_bridge(self):
        pass
