"""services/undo_db — the DB-connection undo seams no test reached.

`tests/test_db_manager.py` (42 tests) pins create/load/delete/clean against a
real archive plus their undo integration, and `test_services_undo.py` pins the
timeline contract — but **no test ever constructed an `UndoService` with a
`dbs=`**, so `DbCommands._db_delete_op` and `._db_op_forward` never executed and
`services/undo_db.py` measured 45.68% covered once Round F step F3 split it out
of `undo_service.py`. The gap is older than the split; the split made it
measurable. This file covers the untested seams only, in the convention of
`test_services_db_gaps.py` and `test_services_collector_gaps.py`.

What is locked here:

* `_db_delete_op`, both directions, including the two warnings that make a
  permanent delete say so instead of pretending;
* `_db_op_forward`, the re-do half of create/load/clean, and its unknown-op
  `None`;
* `_apply_db_command`'s delete branch end to end — restart the world only on
  `ok`, announce on any result, and do neither when the op returned `None`;
* how a delete entry can exist at all, and what Ctrl+Z then does with it.

Two findings are locked as-is rather than fixed, because both are product
decisions and this is a test-only step. Each is named where it is asserted and
carried in ROUND_F2_F3_GOD_CLASS_DESIGN_2026-09-12.md §8.11.8:

* **D4 tension.** SYSTEM_OF_RECORD's D4 says a deleted world stays deleted and
  no Ctrl+Z brings it back, and `test_a_delete_is_not_an_undo_step` pins that
  nothing writes such an entry. A *legacy* entry — one persisted in a world's
  `undo_history` table before `db_bridge` grew its `if op != "delete"` guard —
  does the opposite and restores the file from its backup. Both are true today.
* **Success announced from the outcome, not the intent.** `_apply_db_command`
  still returns `True` and spawns the work — the timeline moves at once — but
  the "database restored" line now comes from `services.undo_db._announce`,
  built from the DbManager's own result, and `undo_apply._log_command` skips
  `dbconn` exactly as it already skipped `archive`. Announcing the intent is
  what let a locked database keep a person deleted while the log said "archive
  restored" (bug 2026-09-11, SYSTEM_OF_RECORD I-18); dbconn had the same shape,
  and these tests lock the corrected ordering.

Run with:  python3 tests/integration/services/test_services_undo_gaps.py
"""

import asyncio
import json
import logging
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)

import services.undo_apply as undo_apply                  # noqa: E402
import services.undo_db as undo_db                        # noqa: E402
from backend.config_manager import ConfigManager          # noqa: E402
from core.events import (DbChanged, EventBus, LogMessage,  # noqa: E402
                         UserDbChanged)
from services.undo_service import UndoService             # noqa: E402


async def wait_for(box, timeout=3.0):
    """Poll until `box` is non-empty — the db work runs in a spawned task."""
    step, waited = 0.01, 0.0
    while not box and waited < timeout:
        await asyncio.sleep(step)
        waited += step
    return box


class _Capture(logging.Handler):
    """The `chatbot` logger — where a crashed spawned task reports itself.

    `TimelineCommit._crash_log` announces a dead background step through
    `logging`, not the EventBus, so a bus-only recorder cannot distinguish "the
    op declined cleanly" from "the op raised inside its task". WARNING and above
    only: capturing DEBUG makes these suites visibly slower.
    """

    def __init__(self, box):
        super().__init__(level=logging.WARNING)
        self.box = box

    def emit(self, record):
        self.box.append(record.getMessage())


class FakeDbs:
    """Stands in for DbManager: records every call, returns a canned result."""

    def __init__(self, result=None):
        self.calls = []
        self.result = {"ok": True} if result is None else result

    async def delete(self, path):
        self.calls.append(("delete", path))
        return self.result

    async def load(self, path, create=False):
        self.calls.append(("load", path, create))
        return self.result

    async def clean(self):
        self.calls.append(("clean",))
        return self.result

    async def restore_backup(self, backup, target=""):
        self.calls.append(("restore_backup", backup, target))
        return self.result


class DbConnCase(unittest.IsolatedAsyncioTestCase):
    """An UndoService wired to a fake DbManager and a recording bus."""

    RESULT = None                     # per-class canned DbManager result

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name
        self.cfg = ConfigManager(os.path.join(self.dir, "config.json"))
        self.bus = EventBus()
        self.logs = []
        self.db_changed = []
        self.user_db_changed = []
        self.bus.subscribe(LogMessage,
                           lambda e: self.logs.append((e.level, e.message)))
        self.bus.subscribe(DbChanged, lambda e: self.db_changed.append(e))
        self.bus.subscribe(UserDbChanged,
                           lambda e: self.user_db_changed.append(e))
        self.dbs = FakeDbs(self.RESULT)
        self.undo = UndoService(config=self.cfg, dbs=self.dbs, bus=self.bus)
        self.pylogs = []
        logger = logging.getLogger("chatbot")
        handler = _Capture(self.pylogs)
        logger.addHandler(handler)
        self.addCleanup(logger.removeHandler, handler)
        self.restarts = []
        self._record_restarts()

    def tearDown(self):
        self._tmp.cleanup()

    # ── helpers ──────────────────────────────────────────────────
    def _record_restarts(self):
        """Patch `restart_world` WHERE undo_db looks it up.

        `services/undo_db.py` does `from services.undo_world import
        restart_world`, so the name it calls is its own module attribute; a
        patch on `services.undo_world` would be invisible to it. (The same
        trap in the other direction is why `bridge.db_bridge.restart_world` is
        patched in the bridge tests.)
        """
        original = undo_db.restart_world
        calls = self.restarts

        async def fake_restart(_memory, _archive, _labels, _undo, _bus, op):
            calls.append(op)

        undo_db.restart_world = fake_restart
        self.addCleanup(setattr, undo_db, "restart_world", original)

    def real(self, name):
        """Create a file that `os.path.exists` will find."""
        path = os.path.join(self.dir, name)
        with open(path, "wb") as fh:
            fh.write(b"sqlite-ish")
        return path

    def absent(self, name):
        return os.path.join(self.dir, name)

    def infos(self):
        return [m for lvl, m in self.logs if lvl == "info"]

    def warnings(self):
        return [m for lvl, m in self.logs if lvl == "warn"]

    def entry(self, **value):
        """A `dbconn` timeline entry shaped the way db_bridge writes them."""
        merged = {"op": "delete", "path": "", "before_path": "", "backup": ""}
        merged.update(value)
        return {"kind": "dbconn", "value": merged, "seq": 1}


# ═════════════════════════════════════════════════════════════════
# _db_delete_op — both directions of a delete entry
# ═════════════════════════════════════════════════════════════════
class TestDbDeleteOp(DbConnCase):
    async def test_forward_re_deletes_the_file(self):
        path = self.real("work.db")
        result = await self.undo._db_delete_op({"path": path}, True)
        self.assertEqual(self.dbs.calls, [("delete", path)])
        self.assertEqual(result, {"ok": True})

    async def test_forward_with_nothing_left_says_so_and_deletes_nothing(self):
        result = await self.undo._db_delete_op(
            {"path": self.absent("gone.db")}, True)
        self.assertIsNone(result, "None tells the caller: do not restart, "
                                  "do not emit — the op already said why")
        self.assertEqual(self.dbs.calls, [], "a missing file is not re-deleted")
        self.assertEqual(len(self.warnings()), 1)
        self.assertIn("Nothing to re-delete", self.warnings()[0])

    async def test_reverse_restores_the_world_from_its_backup(self):
        path = self.absent("work.db")          # deleted: the file is gone
        backup = self.real("work.db.bak")
        result = await self.undo._db_delete_op(
            {"path": path, "backup": backup}, False)
        self.assertEqual(self.dbs.calls, [("restore_backup", backup, path)])
        self.assertEqual(result, {"ok": True})

    async def test_reverse_with_no_backup_says_the_delete_is_permanent(self):
        result = await self.undo._db_delete_op(
            {"path": self.absent("work.db"),
             "backup": self.absent("gone.bak")}, False)
        self.assertIsNone(result)
        self.assertEqual(self.dbs.calls, [], "there is nothing to restore from")
        self.assertEqual(len(self.warnings()), 1)
        self.assertIn("Database deletions are permanent", self.warnings()[0])

    async def test_an_entry_with_no_backup_key_at_all_is_permanent_too(self):
        """`str(value.get("backup") or "")` — a missing key is a missing backup.

        Legacy entries are exactly the ones whose shape cannot be assumed, so
        the coercion is part of the contract rather than an implementation
        detail.
        """
        result = await self.undo._db_delete_op({"path": "work.db"}, False)
        self.assertIsNone(result)
        self.assertEqual(self.dbs.calls, [])
        self.assertIn("permanent", self.warnings()[0])


# ═════════════════════════════════════════════════════════════════
# _db_op_forward — the re-do half of create / load / clean
# ═════════════════════════════════════════════════════════════════
class TestDbOpForward(DbConnCase):
    async def test_create_loads_the_new_world_with_create_true(self):
        result = await self.undo._db_op_forward("create", "/w/new.db")
        self.assertEqual(self.dbs.calls, [("load", "/w/new.db", True)])
        self.assertEqual(result, {"ok": True})

    async def test_load_reopens_without_creating(self):
        await self.undo._db_op_forward("load", "/w/old.db")
        self.assertEqual(self.dbs.calls, [("load", "/w/old.db", False)])

    async def test_clean_empties_the_live_world_and_ignores_the_path(self):
        await self.undo._db_op_forward("clean", "/w/whatever.db")
        self.assertEqual(self.dbs.calls, [("clean",)],
                         "clean acts on the LIVE world, not on the entry's path")

    async def test_an_unknown_op_is_none_and_calls_nothing(self):
        self.assertIsNone(await self.undo._db_op_forward("bogus", "/w.db"))
        self.assertEqual(self.dbs.calls, [])


# ═════════════════════════════════════════════════════════════════
# _apply_db_command — the delete branch, end to end
# ═════════════════════════════════════════════════════════════════
class TestApplyDbCommandDeleteBranch(DbConnCase):
    async def test_an_ok_delete_restarts_the_world_and_announces_it(self):
        path = self.real("work.db")
        self.assertTrue(self.undo._apply_db_command(
            {"op": "delete", "path": path}, forward=True),
            "the spawn is the answer; the outcome arrives on the bus")
        await wait_for(self.db_changed)
        self.assertEqual(self.dbs.calls, [("delete", path)])
        self.assertEqual(self.restarts, ["delete"],
                         "a different world is live, so every surface rebuilds")
        self.assertEqual(self.db_changed[0].action, "delete")
        payload = json.loads(self.db_changed[0].payload)
        self.assertTrue(payload["switched"],
                        "ok + delete ⇒ JS windows must drop cached world data")
        self.assertEqual(json.loads(self.user_db_changed[0].payload),
                         {"action": "db_delete", "ok": True})

    async def test_a_failed_delete_announces_without_restarting(self):
        self.dbs.result = {"ok": False, "error": "the file is in use"}
        self.undo._apply_db_command(
            {"op": "delete", "path": self.real("work.db")}, forward=True)
        await wait_for(self.db_changed)
        self.assertEqual(self.restarts, [],
                         "nothing moved, so nothing may be rebuilt")
        self.assertFalse(json.loads(self.db_changed[0].payload).get("switched"))
        self.assertEqual(json.loads(self.user_db_changed[0].payload)["ok"],
                         False)
        self.assertTrue(any("⚠ the file is in use" in m
                            for m in self.warnings()),
                        "the DbManager's own error reaches the Log Console: "
                        f"{self.warnings()}")

    async def test_a_delete_that_cannot_run_is_silent_on_the_bus(self):
        self.undo._apply_db_command(
            {"op": "delete", "path": self.absent("gone.db")}, forward=True)
        await wait_for(self.warnings())
        await asyncio.sleep(0.05)          # let any stray emit land
        self.assertEqual(self.dbs.calls, [])
        self.assertEqual(self.restarts, [])
        self.assertEqual(self.db_changed, [],
                         "None means the op already said why: no restart, no "
                         "emit, and above all no switched=True")
        self.assertIn("Nothing to re-delete", self.warnings()[0])
        self.assertEqual([m for m in self.pylogs if "db command failed" in m],
                         [], "declining cleanly is not the same as raising "
                             "inside the spawned task")

    async def test_an_unknown_op_neither_restarts_nor_announces(self):
        self.undo._apply_db_command({"op": "bogus", "path": "x"}, forward=False)
        await asyncio.sleep(0.05)
        self.assertEqual(self.dbs.calls, [])
        self.assertEqual(self.restarts, [])
        self.assertEqual(self.db_changed, [])
        self.assertEqual([m for m in self.pylogs if "db command failed" in m],
                         [], "an unknown op is a no-op, not a crash")


# ═════════════════════════════════════════════════════════════════
# _db_switch_op — the forward half, which nothing re-did
# ═════════════════════════════════════════════════════════════════
class TestDbSwitchOp(DbConnCase):
    """`_db_switch_op` both ways: create/load/clean, and an unknown op.

    `test_db_manager.py` undoes a load and a clean but never re-does one, so
    the `if forward:` branch delegating to `_db_op_forward` was the module's
    last uncovered line. Direction is the whole contract here: forward goes to
    `path`, backward goes to `before_path` (or to the clean's `backup`), and
    mixing the two up reopens the wrong world.
    """

    ENTRY = {"op": "load", "path": "/w/new.db", "before_path": "/w/old.db",
             "backup": ""}

    async def test_redo_of_a_load_reopens_the_world_it_moved_to(self):
        result = await self.undo._db_switch_op(dict(self.ENTRY), True)
        self.assertEqual(self.dbs.calls, [("load", "/w/new.db", False)],
                         "redo goes FORWARD to path, not back to before_path")
        self.assertEqual(result, {"ok": True})

    async def test_undo_of_a_load_goes_back_to_the_previous_world(self):
        await self.undo._db_switch_op(dict(self.ENTRY), False)
        self.assertEqual(self.dbs.calls, [("load", "/w/old.db", False)],
                         "undo reopens the world that was left, without "
                         "creating anything")

    async def test_redo_of_a_create_creates_the_world(self):
        await self.undo._db_switch_op(
            {"op": "create", "path": "/w/new.db", "before_path": ""}, True)
        self.assertEqual(self.dbs.calls, [("load", "/w/new.db", True)])

    async def test_undo_of_a_clean_restores_the_backup_it_made(self):
        await self.undo._db_switch_op(
            {"op": "clean", "path": "/w/live.db", "backup": "/w/live.bak"},
            False)
        self.assertEqual(self.dbs.calls,
                         [("restore_backup", "/w/live.bak", "/w/live.db")])

    async def test_an_unknown_switch_op_is_none_in_both_directions(self):
        self.assertIsNone(await self.undo._db_switch_op({"op": "bogus"}, True))
        self.assertIsNone(await self.undo._db_switch_op({"op": "bogus"}, False))
        self.assertEqual(self.dbs.calls, [])
        self.assertEqual([m for m in self.pylogs if "db command failed" in m],
                         [])


# ═════════════════════════════════════════════════════════════════
# how a delete entry can exist at all — and what Ctrl+Z then does
# ═════════════════════════════════════════════════════════════════
class TestHowADeleteEntryCanExist(DbConnCase):
    def test_nothing_in_the_product_records_a_delete_entry(self):
        """The guard that makes delete entries legacy-only.

        Pinned behaviourally by
        `test_db_manager.py::test_a_delete_is_not_an_undo_step` (a permanent
        delete is not an undo step); pinned here at the source so the reason
        `_db_delete_op` is reachable only from persisted data sits next to the
        tests that exercise it.
        """
        with open(os.path.join(ROOT, "bridge", "db_bridge.py"),
                  encoding="utf-8") as fh:
            src = fh.read()
        guard = src.index('if op != "delete":')
        push = src.index('push("dbconn"')
        self.assertLess(guard, push,
                        "the only dbconn push must stay behind the delete guard")

    async def test_a_legacy_delete_entry_still_restores_the_world(self):
        """Ctrl+Z on an entry a *previous* version persisted.

        `sync_world_state` merges a world's `undo_history` table straight into
        the live timeline, so an entry written before the guard exists is
        indistinguishable from a fresh one — and undoing it restores the file
        from the backup the old entry carried.

        D4 tension, locked as-is and deliberately NOT resolved here: D4 says a
        deleted world stays deleted, and nothing today writes this entry, but a
        world file that still holds one gets its delete reversed. Which of the
        two should win is a product decision; §8.11.8 records it.
        """
        path = self.absent("work.db")
        backup = self.real("work.db.bak")
        self.undo.set_history([self.entry(op="delete", path=path,
                                          backup=backup)], 0)
        result = self.undo.undo()
        self.assertTrue(result.is_ok)
        self.assertEqual(result.unwrap()["kind"], "dbconn")
        await wait_for(self.dbs.calls)
        self.assertEqual(self.dbs.calls, [("restore_backup", backup, path)])
        self.assertEqual(self.restarts, ["delete"])
        self.assertTrue(json.loads(self.db_changed[0].payload)["switched"])

    async def test_redo_of_a_legacy_delete_deletes_the_file_again(self):
        path = self.real("work.db")
        self.undo.set_history([self.entry(op="delete", path=path,
                                          backup=self.real("work.db.bak"))], -1)
        result = self.undo.redo()
        self.assertTrue(result.is_ok)
        await wait_for(self.dbs.calls)
        self.assertEqual(self.dbs.calls, [("delete", path)])
        self.assertEqual(self.restarts, ["delete"])

# ═════════════════════════════════════════════════════════════════
# the outcome announcement — SYSTEM_OF_RECORD I-21
# ═════════════════════════════════════════════════════════════════
class TestTheOutcomeAnnouncement(DbConnCase):
    """`dbconn` reports what the DbManager returned, never what was intended.

    These are the tests that changed when the intent-announcement was fixed
    (§8.13): the line used to be written by `undo_apply._log_command` the moment
    the task was spawned, which is the archive bug of 2026-09-11 (I-18) wearing
    a different entry kind.
    """

    async def test_success_is_announced_only_after_the_op_succeeded(self):
        """The archive fix, now applied to dbconn too.

        `_apply_db_command` still answers from the INTENT (`return True` after
        spawning) — the timeline moves at once — but the "↩ Undo — database
        restored" line now comes from `services.undo_db._announce` inside the
        task, built from the DbManager's own result, the way `archive` reports
        itself from the rows it read back. `_log_command` skips both kinds,
        because announcing the intent is what let a locked database keep a
        person deleted while the log said "archive restored" (bug 2026-09-11,
        SYSTEM_OF_RECORD I-18).
        """
        backup = self.real("work.db.bak")
        self.undo.set_history([self.entry(op="delete",
                                          path=self.absent("work.db"),
                                          backup=backup)], 0)
        self.assertEqual(self.infos(), [], "nothing is logged before undo()")
        result = self.undo.undo()
        self.assertTrue(result.is_ok, "the timeline moved; the op has not run")
        self.assertEqual(self.infos(), [],
                         "and nothing is announced before there is a result")
        await wait_for(self.db_changed)
        self.assertTrue(any("↩ Undo — database restored" in m
                            for m in self.infos()),
                        f"the verified outcome is what gets announced: "
                        f"{self.infos()}")
        self.assertEqual(self.dbs.calls,
                         [("restore_backup", backup, self.absent("work.db"))])

    async def test_a_delete_with_no_backup_never_claims_a_restore(self):
        """The worst thing the old ordering could say, now unsayable.

        A legacy delete whose backup is gone warns that deletions are permanent
        and touches nothing — and no line tells the user a database was
        restored, which is exactly what the intent-announcement used to do.
        """
        self.undo.set_history([self.entry(op="delete",
                                          path=self.absent("work.db"),
                                          backup="")], 0)
        result = self.undo.undo()
        self.assertTrue(result.is_ok, "the timeline still moves")
        await wait_for(self.warnings())
        self.assertIn("permanent", self.warnings()[0])
        self.assertEqual([m for m in self.infos() if "restored" in m], [],
                         "a permanent delete must not announce a restore")
        self.assertEqual(self.dbs.calls, [], "nothing was restored")
        self.assertEqual(self.db_changed, [],
                         "and nothing was announced on the db channel either")

    async def test_a_failed_op_reports_the_error_once_and_no_success(self):
        """`emit_db_change` already turns `result["error"]` into a warning, and
        every `{"ok": False}` the DbManager returns carries one (12 of 12 in
        `services/db_lifecycle.py`) — so `_announce` stays quiet instead of
        saying the same thing twice."""
        self.dbs.result = {"ok": False, "error": "the file is in use"}
        self.undo._apply_db_command({"op": "delete",
                                     "path": self.real("work.db")}, True)
        await wait_for(self.db_changed)
        self.assertEqual([m for m in self.infos()
                          if "restored" in m or "re-deleted" in m], [],
                         "no success line for a refusal")
        self.assertTrue(any("the file is in use" in m for m in self.warnings()),
                        f"the error is reported exactly once: {self.warnings()}")

    async def test_redo_of_a_delete_announces_the_re_delete_too(self):
        """The forward direction gets the same treatment: the line is built
        from the result, and reads "↪ Redo" because that is what happened."""
        target = self.real("work.db")
        self.dbs.result = {"ok": True, "path": target}
        self.undo._apply_db_command({"op": "delete", "path": target}, True)
        await wait_for(self.db_changed)
        self.assertTrue(any(m.startswith("↪ Redo — database restored")
                            for m in self.infos()),
                        f"the redo says redo: {self.infos()}")

    async def test_a_switch_op_announces_from_its_result_too(self):
        """The create/load/clean branch of `_apply_db_command` gets the same
        treatment: the line comes after the DbManager answered, and the world
        really did move."""
        old = self.real("old.db")
        self.undo._apply_db_command({"op": "load", "path": self.absent("new.db"),
                                     "before_path": old}, False)
        await wait_for(self.db_changed)
        self.assertTrue(any("↩ Undo — database restored" in m
                            for m in self.infos()),
                        f"the switch branch announces as well: {self.infos()}")
        self.assertEqual(self.dbs.calls, [("load", old, False)],
                         "it went back to the world that was left")
        self.assertEqual(self.restarts, ["load"], "and the world restarted")


# ═════════════════════════════════════════════════════════════════
# _log_command — which kinds are left to announce themselves
# ═════════════════════════════════════════════════════════════════
class TestLogCommandSkipsTheSelfReportingKinds(DbConnCase):
    """The suppression half of I-21 — and the half of I-18 nothing had pinned.

    `_log_command` announces every command kind EXCEPT the two that report
    themselves from their own outcome. Dropping either name silently restores
    the 2026-09-11 bug for that kind, and the negative check for this step
    found that removing `archive` from the tuple failed no test at all.
    """

    def test_archive_and_dbconn_say_nothing_here(self):
        """Neither self-reporting kind may be announced from the intent.

        Removing `archive` from the tuple is what the 2026-09-11 bug was, and
        until this step no test in the repo failed when it was removed.
        """
        for kind in ("archive", "dbconn"):
            self.logs.clear()
            undo_apply._log_command(self.undo, {"kind": kind}, False)
            self.assertEqual(self.logs, [],
                             f"{kind} reports itself, from its outcome")

    def test_every_other_command_kind_is_announced_from_its_label(self):
        """Skipping two kinds must not have silenced the announcement itself.

        `labels` is applied synchronously — `_apply_labels_command` restores the
        snapshot, emits and returns — so for it the intent *is* the outcome.
        `people` is not: its branch spawns `people_service.apply`, which logs
        its own verified line ("↩ People list restored — N person(s)") or an
        error, so the intent line written here is a second, earlier claim. That
        is the dbconn shape again, recorded as open in §8.13.3 rather than fixed
        in this step; these assertions pin today's wording, which is exactly
        what such a fix would have to change on purpose.
        """
        undo_apply._log_command(self.undo, {"kind": "labels"}, False)
        undo_apply._log_command(self.undo, {"kind": "people"}, True)
        self.assertEqual(self.infos(), ["↩ Undo — labels restored",
                                        "↪ Redo — people list restored"],
                         "the label table still drives the wording, and the "
                         "arrow still follows the direction")


if __name__ == "__main__":
    unittest.main()
