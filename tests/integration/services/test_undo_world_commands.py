"""services/undo_service — the world-change half of the ONE global timeline.

`tests/integration/services/test_services_undo.py` pins push / undo / redo /
the cap / the projections, and `test_undo_support_contract.py` pins the
migration, the world store and the timeline commit. What neither reaches is
the **dbconn command** and everything a world change drags along — exactly the
code god-class round step 7 moves out of `services/undo_service.py`
(`docs/archive/2026-09-13-god-classes/STEP7_UNDO_SERVICE_DESIGN_2026-09-13.md`):

  * `emit_db_change` — the `db_changed` wire payload, including WHEN a world
    counts as *switched* (a failed, unchanged or offline result is not one);
  * `restart_world` — after a create/load/delete every world-bound surface is
    rebuilt: the people queue follows the file, the undo timeline is re-synced,
    the windows are told to reload and the my-nick readout follows;
  * `_apply_db_command` / `_db_delete_op` / `_db_switch_op` — re-applying and
    reversing each DB Connection action, and the two loud refusals (a backup
    that does not exist, a file that is already gone) which must NOT be
    reported as successes (the bug of 2026-09-11 in its dbconn shape);
  * `_apply_entry` — walking onto a grid or a stack snapshot entry;
  * the timeline edges the moved code depends on: seq preservation on
    migration, the redo-branch truncation on a re-push, `rewind_after_failure`
    finding an equal-but-not-identical entry, and the world table winning over
    the config half in `sync_world_state`.

The DB manager, the people queue, the label store and the archive are fakes at
their service seam (coroutine-returning surfaces); the `UndoService`, the
`ConfigManager`, the `EventBus` and the timeline commit are REAL (RULE 8).

Run with:  python3 -m pytest tests/integration/services/test_undo_world_commands.py
"""

import asyncio
import json
import os
import sys
import tempfile
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

from backend.config_manager import ConfigManager  # noqa: E402
from core.events import (DbChanged, EventBus, GridLayoutChanged,  # noqa: E402
                         LabelsChanged, LogMessage, MyNickChanged,
                         PeopleChanged, UndoHistoryChanged, UserDbChanged)
from services.layout_service import LayoutService  # noqa: E402
from services.undo_service import (UndoService,  # noqa: E402
                                   emit_db_change, restart_world)

#: a real canonical layout — `config.set_state(grid_layout=…)` validates
#: the payload, so an arbitrary string would be refused by the store
GRID = LayoutService.default_payload()


class FakeDbManager:
    """The DbManager seam the dbconn commands drive."""

    def __init__(self, results=None):
        self.calls = []
        self.results = dict(results or {})

    async def delete(self, path):
        self.calls.append(("delete", path))
        return self.results.get("delete", {"ok": True})

    async def restore_backup(self, backup, path):
        self.calls.append(("restore_backup", backup, path))
        return self.results.get("restore_backup", {"ok": True})

    async def load(self, path, create=False):
        self.calls.append(("load", path, create))
        return self.results.get("load", {"ok": True})

    async def clean(self):
        self.calls.append(("clean",))
        return self.results.get("clean", {"ok": True})


class FakeMemory:
    def __init__(self, db_path, fail=False):
        self.db_path = db_path
        self.switched = []
        self.fail = fail

    async def switch_db(self, path):
        if self.fail:
            raise RuntimeError("the queue is mid-collection")
        self.switched.append(path)


class FakeArchive:
    def __init__(self, path="/fake/world.db", my_nick="Me", open_=True,
                 world=None):
        self.db = types.SimpleNamespace(is_open=open_, path=path)
        self.my_nick = my_nick
        self._world = list(world or [])
        self.saved = []

    async def save_world_undo(self, entries):
        self.saved.append(list(entries))

    async def load_world_undo(self):
        return list(self._world)


class FakeLabels:
    def __init__(self, state=None):
        self._state = state if state is not None else {"labels": []}
        self.restored = []

    def state(self):
        return self._state

    def restore(self, snapshot):
        self.restored.append(snapshot)
        self._state = snapshot


class FakePeople:
    def __init__(self):
        self.applied = []

    async def apply(self, rows):
        self.applied.append(rows)


class FakeTimeline:
    """The `undo` argument of `restart_world`."""

    def __init__(self, fail=False):
        self.syncs = 0
        self.fail = fail

    async def sync_world_state(self):
        self.syncs += 1
        if self.fail:
            raise RuntimeError("the world table is locked")


class Recorder:
    """Every bus event, in order, tagged with its type name."""

    TYPES = (DbChanged, UserDbChanged, LogMessage, MyNickChanged,
             PeopleChanged, LabelsChanged, GridLayoutChanged,
             UndoHistoryChanged)

    def __init__(self, bus):
        self.seen = []
        for event_type in self.TYPES:
            bus.subscribe(event_type,
                          lambda e, t=event_type: self.seen.append(
                              (t.__name__, e)))

    def of(self, name):
        return [e for t, e in self.seen if t == name]

    def db_payloads(self):
        return [json.loads(e.payload) for e in self.of("DbChanged")]

    def userdb_payloads(self):
        return [json.loads(e.payload) for e in self.of("UserDbChanged")]

    def logs(self, needle=None, level=None):
        return [e.message for e in self.of("LogMessage")
                if (needle is None or needle in e.message)
                and (level is None or e.level == level)]


class UndoWorldCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name
        self.cfg = ConfigManager(os.path.join(self.dir, "config.json"))
        self.bus = EventBus()
        self.rec = Recorder(self.bus)
        self.addCleanup(self._tmp.cleanup)

    def service(self, **kwargs):
        kwargs.setdefault("config", self.cfg)
        kwargs.setdefault("bus", self.bus)
        return UndoService(**kwargs)

    async def settle(self, times=12, step=0.01):
        for _ in range(times):
            await asyncio.sleep(step)


class TestEmitDbChange(UndoWorldCase):
    def test_a_newly_live_world_is_announced_as_switched(self):
        for action in ("create", "load", "delete"):
            emit_db_change(self.bus, action, {"ok": True, "path": "/w.db"})
            payload = self.rec.db_payloads()[-1]
            self.assertEqual(payload["action"], action)
            self.assertTrue(payload["switched"], payload)
            self.assertEqual(self.rec.userdb_payloads()[-1],
                             {"action": "db_" + action, "ok": True})

    def test_a_refusal_an_unchanged_and_an_offline_result_are_no_switch(self):
        emit_db_change(self.bus, "load", {"ok": False, "path": "/w.db"})
        emit_db_change(self.bus, "load", {"ok": True, "unchanged": True})
        emit_db_change(self.bus, "load", {"ok": True, "offline": True})
        emit_db_change(self.bus, "clean", {"ok": True})
        for payload in self.rec.db_payloads():
            self.assertNotIn("switched", payload, payload)
        self.assertEqual([p["ok"] for p in self.rec.db_payloads()],
                         [False, True, True, True])

    def test_an_error_in_the_result_is_also_a_visible_warning(self):
        emit_db_change(self.bus, "delete", {"ok": False, "error": "locked"})
        self.assertEqual(self.rec.logs("locked", level="warn"),
                         ["⚠ locked"])

    def test_a_missing_result_is_still_a_payload(self):
        emit_db_change(self.bus, "clean", None)
        self.assertEqual(self.rec.db_payloads(), [{"action": "clean"}])


class TestRestartWorld(UndoWorldCase):
    async def test_without_an_archive_there_is_nothing_to_rebuild(self):
        memory = FakeMemory("/other.db")
        await restart_world(memory, None, FakeLabels(), FakeTimeline(),
                            self.bus, "load")
        self.assertEqual(memory.switched, [])
        self.assertEqual(self.rec.seen, [])

    async def test_every_world_bound_surface_follows_the_file(self):
        world = os.path.join(self.dir, "world.db")
        archive = FakeArchive(path=world, my_nick="HiHoney")
        memory, labels, undo = FakeMemory("/old.db"), FakeLabels(), FakeTimeline()
        await restart_world(memory, archive, labels, undo, self.bus, "load")
        self.assertEqual(memory.switched, [world])
        self.assertEqual(undo.syncs, 1)
        self.assertEqual([e.reason for e in self.rec.of("PeopleChanged")],
                         ["db_switch"])
        self.assertEqual(self.rec.userdb_payloads(),
                         [{"action": "db_switch", "ok": True}])
        self.assertEqual(len(self.rec.of("LabelsChanged")), 1)
        self.assertEqual([e.nick for e in self.rec.of("MyNickChanged")],
                         ["HiHoney"])
        self.assertTrue(self.rec.logs("my nick follows the world"))

    async def test_a_queue_that_refuses_to_follow_is_reported_not_fatal(self):
        archive = FakeArchive(path=os.path.join(self.dir, "w.db"))
        memory, undo = FakeMemory("/old.db", fail=True), FakeTimeline()
        await restart_world(memory, archive, FakeLabels(), undo, self.bus,
                            "create")
        self.assertEqual(undo.syncs, 1, "the rest of the rebuild still ran")
        self.assertEqual(len(self.rec.of("MyNickChanged")), 1)

    async def test_a_timeline_that_refuses_to_sync_is_reported_not_fatal(self):
        archive = FakeArchive(path=os.path.join(self.dir, "w.db"))
        memory, undo = FakeMemory(archive.db.path), FakeTimeline(fail=True)
        await restart_world(memory, archive, FakeLabels(), undo, self.bus,
                            "delete")
        self.assertEqual(memory.switched, [], "already on that file")
        self.assertEqual(len(self.rec.of("PeopleChanged")), 1,
                         "the windows are still told to reload")

    async def test_a_broken_label_store_does_not_cost_the_other_announcements(
            self):
        class BrokenLabels:
            def state(self):
                raise RuntimeError("label file is gone")

        archive = FakeArchive(path=os.path.join(self.dir, "w.db"))
        await restart_world(FakeMemory(archive.db.path), archive,
                            BrokenLabels(), FakeTimeline(), self.bus, "load")
        self.assertEqual(len(self.rec.of("MyNickChanged")), 1)
        self.assertEqual(self.rec.of("LabelsChanged"), [])


class TestDbConnCommands(UndoWorldCase):
    def entry(self, **value):
        return {"kind": "dbconn", "value": value}

    def world(self):
        path = os.path.join(self.dir, "world.db")
        open(path, "w").close()
        return path

    def backup(self):
        path = os.path.join(self.dir, "backup.db")
        open(path, "w").close()
        return path

    async def run_command(self, entry, forward, **kwargs):
        kwargs.setdefault("archive", FakeArchive(path=self.world()))
        kwargs.setdefault("memory", FakeMemory(kwargs["archive"].db.path))
        kwargs.setdefault("labels", FakeLabels())
        service = self.service(dbs=kwargs.pop("dbs", FakeDbManager()), **kwargs)
        accepted = service.apply_command(entry, forward=forward)
        await self.settle()
        return accepted, service

    async def test_undo_of_a_delete_restores_the_backup_and_reopens_the_world(
            self):
        path, backup = self.world(), self.backup()
        dbs = FakeDbManager()
        memory = FakeMemory("/somewhere/else.db")
        accepted, service = await self.run_command(
            self.entry(op="delete", path=path, backup=backup), forward=False,
            dbs=dbs, memory=memory)
        self.assertTrue(accepted)
        self.assertEqual(dbs.calls, [("restore_backup", backup, path)])
        self.assertEqual(memory.switched, [service._archive.db.path])
        self.assertEqual([p["action"] for p in self.rec.db_payloads()],
                         ["delete"])
        self.assertTrue(self.rec.db_payloads()[0]["switched"])

    async def test_a_missing_backup_is_a_loud_refusal_not_a_silent_success(
            self):
        path = self.world()
        dbs = FakeDbManager()
        accepted, _service = await self.run_command(
            self.entry(op="delete", path=path,
                       backup=os.path.join(self.dir, "gone.db")),
            forward=False, dbs=dbs)
        self.assertTrue(accepted, "the entry stays retryable (RULE 12)")
        self.assertEqual(dbs.calls, [], "nothing may be touched")
        self.assertEqual(self.rec.db_payloads(), [], "and nothing announced")
        self.assertTrue(self.rec.logs("deletions are permanent", level="warn"),
                        self.rec.of("LogMessage"))

    async def test_redeleting_a_file_that_is_already_gone_says_so(self):
        dbs = FakeDbManager()
        await self.run_command(
            self.entry(op="delete", path=os.path.join(self.dir, "gone.db"),
                       backup=self.backup()),
            forward=True, dbs=dbs)
        self.assertEqual(dbs.calls, [])
        self.assertEqual(self.rec.db_payloads(), [])
        self.assertTrue(self.rec.logs("Nothing to re-delete", level="warn"))

    async def test_a_create_is_reapplied_by_loading_it_again(self):
        path = self.world()
        dbs = FakeDbManager()
        await self.run_command(self.entry(op="create", path=path,
                                          before_path="/old.db"),
                               forward=True, dbs=dbs)
        self.assertEqual(dbs.calls, [("load", path, True)])
        self.assertEqual([p["action"] for p in self.rec.db_payloads()],
                         ["create"])

    async def test_undo_of_a_create_loads_the_world_that_was_live_before(self):
        dbs = FakeDbManager()
        await self.run_command(self.entry(op="load", path=self.world(),
                                          before_path="/previous.db"),
                               forward=False, dbs=dbs)
        self.assertEqual(dbs.calls, [("load", "/previous.db", False)])
        self.assertEqual([p["action"] for p in self.rec.db_payloads()],
                         ["load"])

    async def test_clean_is_reapplied_and_reversed_through_its_backup(self):
        path, backup = self.world(), self.backup()
        dbs = FakeDbManager()
        await self.run_command(self.entry(op="clean", path=path, backup=backup),
                               forward=True, dbs=dbs)
        self.assertEqual(dbs.calls, [("clean",)])
        dbs.calls.clear()
        await self.run_command(self.entry(op="clean", path=path, backup=backup),
                               forward=False, dbs=dbs)
        self.assertEqual(dbs.calls, [("restore_backup", backup, path)])

    async def test_an_unchanged_result_announces_without_restarting_the_world(
            self):
        dbs = FakeDbManager(results={"load": {"ok": True, "unchanged": True}})
        memory = FakeMemory("/somewhere/else.db")
        await self.run_command(self.entry(op="load", path=self.world()),
                               forward=True, dbs=dbs, memory=memory)
        self.assertEqual(memory.switched, [], "the same world is still live")
        self.assertNotIn("switched", self.rec.db_payloads()[0])

    async def test_an_unknown_dbconn_op_does_nothing_at_all(self):
        dbs = FakeDbManager()
        accepted, _service = await self.run_command(
            self.entry(op="nonsense", path=self.world()), forward=True, dbs=dbs)
        self.assertTrue(accepted)
        self.assertEqual(dbs.calls, [])
        self.assertEqual(self.rec.db_payloads(), [])

    async def test_a_non_dict_value_is_refused_outright(self):
        service = self.service(dbs=FakeDbManager())
        self.assertFalse(service.apply_command({"kind": "dbconn",
                                                "value": "delete"},
                                               forward=True))

    def test_without_a_running_loop_the_command_is_dropped_not_half_applied(
            self):
        """No loop → `spawn` closes the coroutine and nothing is announced.

        Pre-existing behaviour, pinned because step 7 moves it: the dbconn
        command returns True (the entry is a command, the timeline moved) but
        no manager call happens and no `db_changed` is emitted.
        """
        dbs = FakeDbManager()
        service = self.service(dbs=dbs, archive=FakeArchive(path=self.world()))
        self.assertTrue(service.apply_command(
            self.entry(op="delete", path="/x.db", backup="/y.db"),
            forward=True))
        self.assertEqual(dbs.calls, [])
        self.assertEqual(self.rec.db_payloads(), [])


class TestEntryApplication(UndoWorldCase):
    async def test_walking_onto_a_grid_entry_restores_the_layout(self):
        engine = types.SimpleNamespace(
            loads=[], load_stack=lambda blocks: engine.loads.append(blocks))
        service = self.service(engine=engine)
        service.push("grid", GRID)
        # push records the layout but does not WRITE it: only landing on the
        # entry does, so a live grid is never clobbered by a snapshot
        self.assertIsNone(self.cfg.get_state("grid_layout"))
        service.push("stack", [{"block_id": "PAUSE"}])
        service.undo()                       # pointer back onto the grid
        self.assertEqual(self.cfg.get_state("grid_layout"), GRID)
        result = service.redo()              # walks onto the stack snapshot
        self.assertTrue(result.is_ok, result)
        self.assertEqual(engine.loads, [[{"block_id": "PAUSE",
                                           "enabled": True}]])
        service.undo()                       # walks back onto the grid entry
        self.assertEqual(self.cfg.get_state("grid_layout"), GRID)
        # one event per landing on a grid entry, payload verbatim
        self.assertEqual([e.payload for e in self.rec.of("GridLayoutChanged")],
                         [GRID, GRID])
        self.assertTrue(self.rec.logs("↩ Undo — restored grid"))

    async def test_walking_onto_a_people_entry_restores_the_rows(self):
        people = FakePeople()
        service = self.service(people=people)
        rows = [{"nick": "Ann"}]
        self.assertTrue(service.apply_command(
            {"kind": "people", "value": {"before": [], "after": rows}},
            forward=True))
        await self.settle()
        self.assertEqual(people.applied, [rows])

    async def test_a_labels_command_restores_the_snapshot_and_announces(self):
        labels = FakeLabels()
        service = self.service(labels=labels)
        snapshot = {"labels": [{"id": "vip"}]}
        self.assertTrue(service.apply_command(
            {"kind": "labels", "value": {"before": {}, "after": snapshot}},
            forward=True))
        self.assertEqual(labels.restored, [snapshot])
        self.assertEqual(json.loads(self.rec.of("LabelsChanged")[0].payload),
                         snapshot)
        self.assertEqual([e.reason for e in self.rec.of("PeopleChanged")],
                         ["labels"], "labels can hide people from the queue")

    async def test_a_labels_command_without_a_snapshot_or_store_is_refused(
            self):
        service = self.service(labels=None)
        self.assertFalse(service.apply_command(
            {"kind": "labels", "value": {"before": {}, "after": {}}},
            forward=True))
        self.assertFalse(service.apply_command(
            {"kind": "labels", "value": {"before": [], "after": []}},
            forward=True))

    async def test_redo_of_a_command_that_refuses_is_a_typed_error(self):
        people = FakePeople()
        service = self.service(people=people)
        service.push("stack", [{"block_id": "PAUSE"}])
        # a people entry with no `after` half: the undo direction can be
        # applied (it restores `before`), the redo direction cannot
        service.push("people", {"before": [{"nick": "Ann"}], "after": None})
        undone = service.undo()
        self.assertTrue(undone.is_ok, undone)
        await self.settle()
        self.assertEqual(people.applied, [[{"nick": "Ann"}]])
        self.assertEqual(service.history()[1], 0)

        result = service.redo()
        self.assertTrue(result.is_err, result)
        self.assertEqual(result.code, "nothing_to_redo")
        self.assertIn("cannot re-apply", result.detail)
        self.assertEqual(service.history()[1], 0,
                         "a refused redo leaves the pointer where Ctrl+Z "
                         "finds the entry again")

    async def test_a_refused_undo_also_leaves_the_pointer_on_the_entry(self):
        service = self.service(people=None)
        service.push("people", {"before": [{"nick": "Ann"}], "after": []})
        result = service.undo()
        self.assertTrue(result.is_err, result)
        self.assertEqual(result.code, "nothing_to_undo")
        self.assertIn("cannot reverse", result.detail)
        self.assertEqual(service.history()[1], 0)


class TestTimelineEdges(UndoWorldCase):
    def test_a_stored_entry_keeps_the_seq_it_was_migrated_with(self):
        self.cfg.set_state(undo_history=[
            {"kind": "stack", "value": [{"block_id": "PAUSE"}], "seq": 7},
            {"kind": "grid", "value": GRID, "seq": 9},
            {"kind": "nonsense", "value": 1, "seq": 11},
            {"kind": "stack", "value": [{"block_id": "CLICK_SEND"}], "seq": 13},
        ], undo_history_index=1)
        service = self.service()
        history, index = service.migrate_global_history()
        # the unknown kind is the only row dropped; the survivors keep the
        # seq they were stored with — seq is the identity the world merge keys off
        self.assertEqual([e.get("seq") for e in history], [7, 9, 13])
        self.assertEqual(index, 1)

    def test_a_repush_of_the_value_at_the_pointer_is_a_no_op(self):
        service = self.service()
        pause = [{"block_id": "PAUSE", "enabled": True}]
        service.push_stack([{"block_id": "PAUSE"}])
        service.push_stack([{"block_id": "CLICK_MAIN_TAB"}])
        service.undo()
        events = len(self.rec.of("UndoHistoryChanged"))

        # `push` truncates the redo branch in its OWN list and answers with it,
        # but the same-value path commits nothing — so the store keeps the tail.
        result = service.push("stack", pause)
        self.assertTrue(result.is_ok, result)
        answer, index = result.value
        self.assertEqual(index, 0, "the pointer did not move")
        self.assertEqual([e["value"][0]["block_id"] for e in answer],
                         ["PAUSE"], "the ANSWER is the truncated branch")

        # ... and because nothing was written, the stored timeline still
        # carries the redo branch and the bus stayed quiet. Pinned as the
        # behaviour step 7 relocates (see its design doc, "observed, not
        # changed": push's docstring promises the tail cannot survive).
        self.assertEqual(len(self.rec.of("UndoHistoryChanged")), events)
        stored, stored_index = service.history()
        self.assertEqual([e["value"][0]["block_id"] for e in stored],
                         ["PAUSE", "CLICK_MAIN_TAB"])
        self.assertEqual(stored_index, 0)

    def test_push_stack_answers_from_the_store_not_from_the_push(self):
        service = self.service()
        service.push_stack([{"block_id": "PAUSE"}])
        service.push_stack([{"block_id": "CLICK_MAIN_TAB"}])
        service.undo()
        # the compat wrapper drops push's answer and re-reads the timeline, so
        # after a no-op push it still shows the redo branch `push` truncated
        stacks, index = service.push_stack([{"block_id": "PAUSE"}])
        self.assertEqual(index, 0)
        self.assertEqual([value[0]["block_id"] for value in stacks],
                         ["PAUSE", "CLICK_MAIN_TAB"])

    def test_a_repush_of_a_different_value_does_truncate_the_redo_branch(self):
        service = self.service()
        service.push_stack([{"block_id": "PAUSE"}])
        service.push_stack([{"block_id": "CLICK_MAIN_TAB"}])
        service.undo()
        service.push_stack([{"block_id": "CLICK_SEND"}])
        stored, index = service.history()
        self.assertEqual([e["value"][0]["block_id"] for e in stored],
                         ["PAUSE", "CLICK_SEND"])
        self.assertEqual(index, 1)

    def test_a_failed_command_rewinds_onto_an_equal_entry(self):
        service = self.service()
        service.push("grid", GRID)
        service.push("stack", [{"block_id": "PAUSE"}])
        history, index = service.history()
        self.assertEqual(index, 1)
        # an equal-but-not-identical copy of the FIRST entry, as a caller that
        # rebuilt the entry from the wire would hand over
        copy_of_first = json.loads(json.dumps(history[0]))
        self.assertIsNot(copy_of_first, history[0])
        service.rewind_after_failure(copy_of_first, forward=True)
        self.assertEqual(service.history()[1], 0)
        service.rewind_after_failure(None, forward=True)      # no crash
        service.rewind_after_failure({"kind": "stack", "value": []},
                                     forward=False)           # not found
        self.assertEqual(service.history()[1], 0)

    def test_value_equality_falls_back_to_equality_when_json_cannot_help(self):
        class Opaque:
            def __init__(self, tag):
                self.tag = tag

            def __eq__(self, other):
                return isinstance(other, Opaque) and other.tag == self.tag

        service = self.service()
        first = service.push("grid", Opaque("a"))
        self.assertTrue(first.is_ok)
        again = service.push("grid", Opaque("a"))
        self.assertTrue(again.is_ok)
        self.assertEqual(len(again.value[0]), 1, "the dedupe still fired")

    async def test_the_world_table_wins_over_the_config_half(self):
        world_entry = {"kind": "people",
                       "value": {"before": [], "after": [{"nick": "W"}]},
                       "seq": 4}
        archive = FakeArchive(world=[world_entry])
        self.cfg.set_state(undo_history=[
            {"kind": "stack", "value": [{"block_id": "PAUSE"}], "seq": 1},
            {"kind": "people", "value": {"before": [], "after": []}, "seq": 2},
            "not an entry",
        ], undo_history_index=1)
        service = self.service(archive=archive)
        result = await service.sync_world_state()
        self.assertTrue(result.is_ok)
        history, index = service.history()
        self.assertEqual([(e["kind"], e.get("seq")) for e in history],
                         [("stack", 1), ("people", 4)],
                         "the stale config copy of a world kind is dropped")
        self.assertEqual(index, 1)

    async def test_a_world_save_is_scheduled_and_settled(self):
        archive = FakeArchive()
        service = self.service(archive=archive)
        service.push("people", {"before": [], "after": [{"nick": "A"}]})
        await self.settle()
        self.assertEqual(len(archive.saved), 1)
        self.assertEqual(archive.saved[0][0]["kind"], "people")

    def test_attach_binds_every_dependency_it_is_given(self):
        service = self.service()
        archive, people, labels = FakeArchive(), FakePeople(), FakeLabels()
        dbs, memory, engine = FakeDbManager(), FakeMemory("/x"), object()
        bus = EventBus()
        service.attach(archive=archive, people=people, labels=labels, dbs=dbs,
                       memory=memory, engine=engine, bus=bus)
        self.assertIs(service._archive, archive)
        self.assertIs(service._people, people)
        self.assertIs(service._labels, labels)
        self.assertIs(service._dbs, dbs)
        self.assertIs(service._memory, memory)
        self.assertIs(service._engine, engine)
        self.assertIs(service._bus, bus)
        service.attach()                     # nothing given → nothing rebound
        self.assertIs(service._archive, archive)

    def test_clean_history_drops_rows_that_are_not_block_lists(self):
        cleaned = UndoService._clean_history(
            [[{"block_id": "PAUSE"}], "nonsense", None,
             [{"block_id": "CLICK_SEND", "nick": "Ann"}]])
        self.assertEqual(cleaned, [[{"block_id": "PAUSE", "enabled": True}],
                                   [{"block_id": "CLICK_SEND", "nick": "Ann",
                                     "enabled": True}]])
        self.assertEqual(UndoService._clean_history("not a list"), [])
        self.assertEqual(UndoService._clean_history(None), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
