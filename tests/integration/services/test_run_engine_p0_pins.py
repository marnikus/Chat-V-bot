"""P0 pins for the run engine (AREA A — startup & harness).

These tests pin the two missing-import defects from the four-area plan
(§5 P0-1 / P0-2) independently of the AREA-C-owned
``test_services_run.py`` / ``test_click_user_memory.py`` files, which AREA A
must not edit:

  * P0-1  ``RunCoordinator.load_stack`` must resolve block classes through
          ``actions.registry.get_action_class`` — before the fix the module
          never imported the name and every stack load raised ``NameError``;
  * P0-2  ``services.run.progress`` must expose the real ``UserRecord`` at
          runtime (it was imported under ``if TYPE_CHECKING:``), so the
          single-target cycle — ``Use Person from Memory`` — can construct
          ``UserRecord(nick=target)``.

Each test runs against a shipped-only registry view (the registry is
process-global and other test modules deliberately shadow shipped blocks at
import time) and restores the previous table in tearDown.

Run:  python -m pytest tests/integration/services/test_run_engine_p0_pins.py
"""

import asyncio
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))))

from actions.base_action import ActionResult, BaseAction  # noqa: E402
from actions.registry import ActionRegistry  # noqa: E402
from actions.take_person import TakePerson  # noqa: E402
from services.run import RunCoordinator  # noqa: E402
from stores.user_memory import UserRecord  # noqa: E402


def _shipped_block_classes():
    """block_id -> shipped class from the already-imported actions modules.

    No reload: cached modules (and the class objects other test modules
    bound at collection time) stay identity-stable; the shipped classes are
    simply re-registered on top of any test-double shadows.
    """
    import importlib
    import pkgutil

    import actions as actions_pkg
    found = {}
    for modinfo in pkgutil.iter_modules(actions_pkg.__path__):
        if modinfo.name in ActionRegistry._SKIP_MODULES:
            continue
        module = importlib.import_module(f"actions.{modinfo.name}")
        for obj in vars(module).values():
            if (isinstance(obj, type)
                    and issubclass(obj, BaseAction)
                    and obj.__module__.startswith("actions.")
                    and getattr(obj, "block_id", "")):
                found[obj.block_id] = obj
    return found


class RegistryCase(unittest.TestCase):
    """Shipped-only registry for one test; the previous table is restored."""

    def setUp(self):
        self._saved = dict(ActionRegistry._classes)
        ActionRegistry._classes.clear()
        for block_id, klass in _shipped_block_classes().items():
            ActionRegistry.register_class(klass, block_id=block_id)

    def tearDown(self):
        ActionRegistry._classes.clear()
        ActionRegistry._classes.update(self._saved)


def make_coordinator(memory=None):
    return RunCoordinator(cdp=None, memory=memory, criteria=None)


# ── P0-1: load_stack ─────────────────────────────────────────────

class TestLoadStackPins(RegistryCase):
    def test_plan_gate_pause_block_loads_without_raising(self):
        """Plan §6.1 exit criterion 3 / Gate 2 — the gate snippet with the
        registry's uppercase id loads and round-trips."""
        engine = make_coordinator()
        engine.load_stack([{"block_id": "PAUSE", "id": "A",
                            "duration_ms": 50}])
        stack = engine.get_stack()
        self.assertEqual(len(stack), 1)
        self.assertEqual(stack[0]["block_id"], "PAUSE")
        self.assertTrue(stack[0]["enabled"])

    def test_unknown_and_non_dict_entries_are_skipped(self):
        engine = make_coordinator()
        engine.load_stack([
            {"block_id": "NOT_A_REAL_BLOCK", "id": "x"},
            "garbage",
            None,
            42,
        ])
        self.assertEqual(engine.get_stack(), [])

    def test_unknown_id_does_not_raise_even_in_lowercase(self):
        """The plan's gate snippet spells the id lowercase ("pause"); the
        registry is uppercase-keyed, so it resolves to nothing and is
        skipped — crucially this must not raise NameError."""
        engine = make_coordinator()
        engine.load_stack([{"block_id": "pause", "id": "A"}])  # must not raise
        self.assertEqual(engine.get_stack(), [])

    def test_disabled_flag_and_retired_keys_round_trip(self):
        engine = make_coordinator()
        engine.load_stack([
            {"block_id": "PAUSE", "id": "on", "duration_ms": 1},
            {"block_id": "PAUSE", "id": "off", "enabled": False,
             "duration_ms": 2, "use_panel_filters": True, "_hidden": 1},
        ])
        stack = engine.get_stack()
        self.assertEqual([s["enabled"] for s in stack], [True, False])
        self.assertNotIn("use_panel_filters", stack[1])
        self.assertNotIn("_hidden", stack[1])

    def test_representative_shipped_blocks_instantiate(self):
        engine = make_coordinator()
        engine.load_stack([
            {"block_id": "PAUSE", "id": "p"},
            {"block_id": "REPEAT_LOOP", "id": "r", "repeat_count": 2},
            {"block_id": "CLICK_SEND", "id": "s"},
        ])
        ids = [b.block_id for b in engine._stack]
        self.assertEqual(ids, ["PAUSE", "REPEAT_LOOP", "CLICK_SEND"])
        # they are the SHIPPED classes, not test doubles
        self.assertEqual(
            [type(b).__module__ for b in engine._stack],
            ["actions.pause", "actions.repeat_loop", "actions.click_send"])

    def test_loading_again_replaces_the_previous_stack(self):
        engine = make_coordinator()
        engine.load_stack([{"block_id": "PAUSE", "id": "a"}])
        engine.load_stack([{"block_id": "PAUSE", "id": "b"},
                           {"block_id": "PAUSE", "id": "c"}])
        self.assertEqual([s["id"] for s in engine.get_stack()], ["b", "c"])


# ── P0-2: UserRecord at runtime in services.run.progress ─────────

class TestProgressUserRecordPin(unittest.TestCase):
    def test_userrecord_importable_from_progress_at_runtime(self):
        import services.run.progress as progress

        self.assertTrue(hasattr(progress, "UserRecord"),
                        "UserRecord must be bound at runtime, not only under "
                        "TYPE_CHECKING")
        self.assertIs(progress.UserRecord, UserRecord)

    def test_single_target_cycle_constructs_real_userrecord(self):
        """The runtime construction site must receive the real dataclass:
        building one through the progress module must behave like the
        stores dataclass (fields + identity)."""
        from services.run.progress import UserRecord as ProgressRecord

        rec = ProgressRecord(nick="Zoe")
        self.assertEqual(rec.nick, "Zoe")
        self.assertFalse(rec.messaged)
        self.assertIsInstance(rec, UserRecord)


class _MemoryDb:
    """Minimal async in-memory UserMemory stand-in for engine runs."""

    def __init__(self, *records):
        self._users = list(records)
        self.marked = []

    async def get_queue(self):
        return [u for u in self._users if not getattr(u, "messaged", False)]

    async def get_all(self):
        return list(self._users)

    async def mark_messaged(self, nick):
        self.marked.append(nick)
        for u in self._users:
            if u.nick == nick:
                u.messaged = True


def _make_stub_click():
    class StubClick(BaseAction):
        """Stands in for CLICK_USER with Use-Person-from-Memory on."""

        block_id = "CLICK_USER"
        name = "Click User"
        icon = "👤"

        def __init__(self, **kw):
            super().__init__(pre_delay_ms=0)
            self.use_person_from_memory = True
            self.calls = []

        async def execute(self, user_nick, cdp, engine=None):
            nick = getattr(engine, "selected_nick", "") or user_nick
            if not nick:
                return ActionResult.FAIL   # never click blindly
            self.calls.append(nick)
            return ActionResult.OK

    return StubClick()


def _make_consumer():
    class Consumer(BaseAction):
        block_id = "TYPE_MESSAGE"
        name = "Type Message"
        icon = "⌨️"

        def __init__(self, **kw):
            super().__init__(pre_delay_ms=0)
            self.message = "hi {{nick}}"
            self.seen = []

        async def execute(self, user_nick, cdp, engine=None):
            self.seen.append(user_nick)
            return ActionResult.OK

    return Consumer()


class TestSingleTargetCyclePin(RegistryCase):
    """End-to-end pin for the P0-2 crash path."""

    def setUp(self):
        super().setUp()
        self.old = os.getcwd()
        self.tmp = tempfile.TemporaryDirectory()
        os.chdir(self.tmp.name)

    def tearDown(self):
        os.chdir(self.old)
        self.tmp.cleanup()
        super().tearDown()

    def test_runs_once_on_picked_person_and_marks_them(self):
        """Queue lists Anna + Bella; Pick Person chooses one; the memory
        click works exactly that person and marks them — the queue's other
        person is never touched. Before P0-2 this raised NameError."""
        async def go():
            memory = _MemoryDb(UserRecord(nick="Anna"),
                               UserRecord(nick="Bella"))
            engine = make_coordinator(memory)
            click = _make_stub_click()
            take = TakePerson(pick_mode="order_first")
            consumer = _make_consumer()
            engine._stack = [take, click, consumer]
            await engine.execute(None)
            return click, consumer, memory

        click, consumer, memory = asyncio.run(go())
        self.assertEqual(len(click.calls), 1,
                         "the queue must be ignored — exactly one target")
        chosen = click.calls[0]
        self.assertIn(chosen, {"Anna", "Bella"})
        self.assertEqual(consumer.seen, [chosen])
        self.assertEqual(memory.marked, [chosen])
        other = "Bella" if chosen == "Anna" else "Anna"
        self.assertNotIn(other, click.calls)

    def test_no_saved_nick_ends_safely_without_p0_crash(self):
        async def go():
            memory = _MemoryDb(UserRecord(nick="Anna"),
                               UserRecord(nick="Bella"))
            engine = make_coordinator(memory)
            click = _make_stub_click()
            logs = []
            engine.log_msg.connect(logs.append)
            engine.debug_msg.connect(lambda m, level=None: logs.append(m))
            engine._stack = [click]
            await engine.execute(None)
            return click.calls, memory.marked, logs

        calls, marked, logs = asyncio.run(go())
        self.assertEqual(calls, [])
        self.assertEqual(marked, [])
        self.assertTrue(any("memory" in m.lower() for m in logs))


if __name__ == "__main__":
    unittest.main(verbosity=2)
