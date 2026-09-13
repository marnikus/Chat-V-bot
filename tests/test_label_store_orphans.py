"""stores/label_store — orphan, import/export, hostile edges.

Design refs: docs/archive/2026-09-09-test-suite/STORES_TEST_DESIGN_2026-09-09.md §10 (LBL-01–20).

test_person_labels.py (41) pins config-mode CRUD + filter + undo, and
test_label_store_dbmode.py (8) pins world-mode persistence. This file pins
the orphan and seam contracts around them: labels are flat, unknown ids
can never dangle, delete/forget clean up fully, hostile names/colours
degrade safely, filters with unknown ids fail closed without raising, and
snapshot/restore + flush/load round-trips are exact — including against a
world whose rows went bad.

Config-mode tests run the store against a REAL AtomicJsonStore file (the
config seam the store actually talks through); world-mode tests use a real
HistoryDB with an explicit flush, like the dbmode suite.

Run with:  python3 tests/test_label_store_orphans.py
"""

import copy
import inspect
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stores.atomic import AtomicJsonStore  # noqa: E402
from stores.history_db import HistoryDB  # noqa: E402
from stores.label_store import (  # noqa: E402
    DEFAULT_COLOR,
    LabelStore,
    normalize_color,
    normalize_id,
    normalize_name,
)


def config_store(tmpdir, name="config.json"):
    return LabelStore(AtomicJsonStore(os.path.join(tmpdir, name)))


def world_store(db):
    return LabelStore(config=None, db=db,
                      scheduler=lambda coro: coro.close())


class ConfigCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.store = config_store(self.dir)


class TestFlatAndOrphans(ConfigCase):
    def test_labels_are_flat(self):  # LBL-01
        self.assertNotIn("parent", inspect.signature(
            LabelStore.create).parameters)
        made = self.store.create("Rude", "#ff0000")
        self.assertNotIn("parent", made)
        self.assertNotIn("parent", self.store.defs()[0])

    def test_assign_unknown_id_refuses_cleanly(self):  # LBL-02
        self.store.create("Rude")
        self.assertFalse(self.store.assign("Ann", "lbl_ghost"))
        self.assertEqual(self.store.assignments(), {})

    def test_assign_blank_nick_refuses_cleanly(self):  # LBL-03
        label = self.store.create("Rude")
        self.assertFalse(self.store.assign("", label["id"]))
        self.assertFalse(self.store.assign("   ", label["id"]))
        self.assertEqual(self.store.assignments(), {})

    def test_unassign_unknown_is_a_noop(self):  # LBL-04
        self.assertFalse(self.store.unassign("ghost", "lbl_ghost"))
        label = self.store.create("Rude")
        self.store.assign("Ann", label["id"])
        self.assertFalse(self.store.unassign("Ann", "lbl_ghost"))
        self.assertFalse(self.store.unassign("ghost", label["id"]))
        self.assertEqual(self.store.ids_for("Ann"), [label["id"]])

    def test_set_for_dedupes_and_drops_unknown(self):  # LBL-05
        label = self.store.create("Rude")
        self.assertTrue(self.store.set_for(
            "Ann", [label["id"], label["id"], "lbl_ghost"]))
        self.assertEqual(self.store.ids_for("Ann"), [label["id"]])

    def test_delete_cleans_every_trace(self):  # LBL-06
        label = self.store.create("Rude")
        self.store.assign("Ann", label["id"])
        self.store.assign("Bob", label["id"])
        self.store.set_filter(exclude=[label["id"]])
        self.assertTrue(self.store.delete(label["id"]))
        self.assertEqual(self.store.assignments(), {})
        self.assertEqual(self.store.filter(),
                         {"include": [], "exclude": []})

    def test_forget_drops_the_nick_only(self):  # LBL-07
        label = self.store.create("Rude")
        self.store.assign("Ann", label["id"])
        self.store.assign("Bob", label["id"])
        self.assertTrue(self.store.forget("Ann"))
        self.assertFalse(self.store.forget("Ann"))
        self.assertFalse(self.store.forget("ghost"))
        self.assertEqual(self.store.assignments(), {"Bob": [label["id"]]})
        self.assertEqual(len(self.store.defs()), 1)  # defs untouched


class TestHostileInputs(ConfigCase):
    def test_blank_name_refused_long_name_capped(self):  # LBL-08
        self.assertIsNone(self.store.create("  "))
        self.assertIsNone(self.store.create(""))
        made = self.store.create("x" * 300)
        self.assertEqual(len(made["name"]), 40)
        self.assertEqual(len(self.store.defs()), 1)

    def test_emoji_name_is_stored_capped(self):  # LBL-08b (pin)
        made = self.store.create("🎉 party 🎉")
        self.assertIsNotNone(made)
        self.assertIn("party", made["name"])

    def test_update_collision_keeps_original(self):  # LBL-09
        first = self.store.create("Rude")
        second = self.store.create("Nice")
        back = self.store.update(second["id"], name="rude")
        self.assertEqual(back["name"], "Nice")
        self.assertEqual(self.store.by_id(first["id"])["name"], "Rude")

    def test_update_unknown_creates_no_phantom(self):  # LBL-10
        self.assertIsNone(self.store.update("lbl_ghost", name="X"))
        self.assertEqual(self.store.defs(), [])

    def test_unknown_lookups_are_none(self):  # LBL-11
        self.assertIsNone(self.store.by_id("lbl_ghost"))
        self.assertIsNone(self.store.by_name("ghost"))
        self.assertIsNone(self.store.by_name(""))
        self.assertIsNone(self.store.by_name(None))

    def test_empty_lookups(self):  # LBL-12
        self.assertEqual(self.store.ids_for("ghost"), [])
        self.assertEqual(self.store.labels_for("ghost"), [])
        self.assertEqual(self.store.labels_map(), {})
        label = self.store.create("Rude", "#ff0000")
        self.store.assign("Ann", label["id"])
        mapped = self.store.labels_map()
        self.assertEqual(set(mapped), set(self.store.assignments()))
        self.assertEqual(mapped["Ann"][0]["color"], "#ff0000")

    def test_normalize_helpers_never_raise(self):  # LBL-08c
        self.assertEqual(normalize_color(None), DEFAULT_COLOR)
        self.assertEqual(normalize_color("red"), DEFAULT_COLOR)
        self.assertEqual(normalize_color("#ABC"), "#aabbcc")
        self.assertEqual(normalize_color("#aabbcc"), "#aabbcc")
        self.assertEqual(normalize_color("x", fallback="#123456"), "#123456")
        self.assertEqual(normalize_name(None), "")
        self.assertEqual(normalize_id(None), "")


class TestFilterEdges(ConfigCase):
    def test_unknown_filter_ids_are_dropped(self):  # LBL-13 (SPEC pin)
        # Unknown ids never persist in a filter (dropped at set time AND
        # on read): the guard fails closed without ever raising.
        back = self.store.set_filter(include=["lbl_ghost"],
                                     exclude=["lbl_ghost"])
        self.assertEqual(back, {"include": [], "exclude": []})
        self.assertTrue(self.store.allows("Ann"))

    def test_filter_lifecycle(self):  # LBL-14
        label = self.store.create("VIP")
        self.assertFalse(self.store.filter_active)
        self.store.set_filter(include=[label["id"]])
        self.assertTrue(self.store.filter_active)
        self.store.clear_filter()
        self.assertFalse(self.store.filter_active)
        self.assertTrue(self.store.allows("Ann"))

    def test_unlabelled_nick_under_include_filter(self):  # LBL-15
        label = self.store.create("VIP")
        self.store.set_filter(include=[label["id"]])
        self.assertFalse(self.store.allows("Ann"))
        reason = self.store.reject_reason("Ann")
        self.assertTrue(reason)
        self.assertIn("VIP", reason)
        self.assertEqual(self.store.reject_reason("nobody-special"), reason)

    def test_allows_unknown_nick_without_filter(self):  # LBL-15b
        self.assertTrue(self.store.allows("ghost"))
        self.assertEqual(self.store.reject_reason("ghost"), "")


class TestSnapshotRestore(ConfigCase):
    def test_snapshot_mutate_restore_is_exact(self):  # LBL-16
        vip = self.store.create("VIP", "#00ff00")
        rude = self.store.create("Rude", "#ff0000")
        self.store.assign("Ann", vip["id"])
        self.store.set_filter(exclude=[rude["id"]])
        snap = self.store.snapshot()
        # mutate everything …
        self.store.delete(vip["id"])
        self.store.delete(rude["id"])
        self.store.clear_filter()
        self.assertEqual(self.store.defs(), [])
        # … restore brings it all back, filter included
        self.store.restore(copy.deepcopy(snap))
        self.assertEqual(self.store.snapshot(), snap)

    def test_restore_non_dict_is_a_noop(self):  # LBL-17a
        label = self.store.create("VIP")
        self.store.assign("Ann", label["id"])
        before = self.store.snapshot()
        for bad in (None, [], "str", 5):
            self.store.restore(bad)
        self.assertEqual(self.store.snapshot(), before)

    def test_restore_ill_typed_values_degrade_without_bricking(self):  # LBL-17b
        self.store.create("VIP")
        self.store.restore({"defs": "xx", "assign": ["not-a-dict"],
                            "filter": "xx"})
        # degraded, but the store keeps serving reads afterwards
        self.assertEqual(self.store.defs(), [])
        self.assertTrue(self.store.allows("Ann"))
        self.assertEqual(self.store.reject_reason("Ann"), "")
        # … and accepts new writes normally
        self.assertIsNotNone(self.store.create("Fresh"))

    def test_state_is_a_deep_copy(self):  # LBL-20
        label = self.store.create("VIP")
        self.store.assign("Ann", label["id"])
        state = self.store.state()
        state["defs"].clear()
        state["assign"]["Ann"].append("lbl_hack")
        self.assertEqual(len(self.store.defs()), 1)
        self.assertEqual(self.store.ids_for("Ann"), [label["id"]])


class WorldCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.dir = tempfile.mkdtemp()
        self.db = HistoryDB(os.path.join(self.dir, "w.db"))
        await self.db.init()
        self.store = world_store(self.db)
        await self.store.load_from_db(self.db)

    async def asyncTearDown(self):
        await self.db.close()


class TestWorldSync(WorldCase):
    async def test_flush_then_load_round_trip(self):  # LBL-18
        label = self.store.create("VIP", "#00ff00")
        self.store.assign("Ann", label["id"])
        self.store.set_filter(include=[label["id"]])
        await self.store.flush_to_db()
        fresh = world_store(self.db)
        await fresh.load_from_db(self.db)
        self.assertEqual(fresh.defs(), self.store.defs())
        self.assertEqual(fresh.assignments(), self.store.assignments())
        self.assertEqual(fresh.filter(), self.store.filter())

    async def test_unflushed_changes_are_invisible(self):  # LBL-18b
        self.store.create("Ghost")
        fresh = world_store(self.db)
        await fresh.load_from_db(self.db)
        self.assertEqual(fresh.defs(), [])
        await self.store.flush_to_db()
        await fresh.load_from_db(self.db)
        self.assertEqual([d["name"] for d in fresh.defs()], ["Ghost"])

    async def test_load_from_corrupt_world_is_best_effort(self):  # LBL-19
        await self.db.execute(
            "INSERT INTO labels(id, name, color) VALUES(?,?,?)",
            ("lbl_bad", "", "not-a-color"))
        await self.db.execute(
            "INSERT INTO labels(id, name, color) VALUES(?,?,?)",
            ("lbl_ok", "Fine", "#00ff00"))
        await self.db.execute(
            "INSERT INTO label_assigns(nick, label_id) VALUES(?,?)",
            ("Ann", "lbl_ghost"))
        await self.db.execute(
            "INSERT INTO label_assigns(nick, label_id) VALUES(?,?)",
            ("Ann", "lbl_ok"))
        await self.db.execute(
            "INSERT INTO app_settings(key, value) VALUES(?,?)",
            ("label_filter", "{broken"))
        await self.db.execute(
            "INSERT INTO schema_meta(key, value) VALUES(?,?)",
            ("labels_next_id", "xx"))
        await self.db.commit()
        await self.store.load_from_db(self.db)  # must not raise
        self.assertEqual([d["name"] for d in self.store.defs()], ["Fine"])
        self.assertEqual(self.store.ids_for("Ann"), ["lbl_ok"])
        self.assertFalse(self.store.filter_active)
        # the store stays usable: new labels get fresh ids
        made = self.store.create("New")
        self.assertTrue(made["id"].startswith("lbl_"))


if __name__ == "__main__":
    unittest.main()
