"""stores/label_store — world-bound (db) mode and normalisation edges.

Design refs: docs/archive/2026-09-09-test-suite/BACKEND_TESTS_DESIGN_2026-09-09.md §LB#1–5.

test_person_labels.py covers config-mode CRUD + the filter logic. This
file pins the mode the bridge uses since ONE DB = ONE WORLD:

  * labels live in the world's tables: create/assign → flush_to_db → a
    fresh store reading the same db sees the same state;
  * two worlds hold independent label sets;
  * normalize_color returns a stylesheet-safe `#rrggbb` for garbage;
  * normalize_name caps length and collapses whitespace;
  * snapshot/restore is deep (undo must not alias live state).

Run with:  python3 tests/unit/backend/test_label_store_dbmode.py
"""

import asyncio
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))

from backend.history_db import HistoryDB  # noqa: E402
from stores.label_store import (  # noqa: E402
    DEFAULT_COLOR,
    MAX_NAME,
    LabelStore,
    normalize_color,
    normalize_name,
    normalize_nick,
)


def make_store(db):
    # the scheduler would run the write-through on the Qt loop; these tests
    # flush explicitly, so the scheduled coroutine is simply closed.
    return LabelStore(config=None, db=db,
                      scheduler=lambda coro: coro.close())


class DbCase(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.dir = tempfile.mkdtemp()
        self.db1 = HistoryDB(os.path.join(self.dir, "w1.db"))
        await self.db1.init()
        self.db2 = HistoryDB(os.path.join(self.dir, "w2.db"))
        await self.db2.init()
        self.store = make_store(self.db1)
        await self.store.load_from_db(self.db1)

    async def asyncTearDown(self):
        await self.db1.close()
        await self.db2.close()


class TestWorldPersistence(DbCase):

    async def test_state_round_trips_through_the_world_file(self):
        label = self.store.create("VIP", "#ff0000")     # returns the def dict
        self.store.assign("Анна", label["id"])
        await self.store.flush_to_db()

        fresh = make_store(self.db1)
        await fresh.load_from_db(self.db1)
        defs = fresh.defs()
        self.assertEqual([d["name"] for d in defs], ["VIP"])
        self.assertEqual(fresh.labels_for("Анна")[0]["name"], "VIP")
        self.assertEqual(fresh.by_id(label["id"])["color"], "#ff0000")
        # create() hands back a usable dict, not an id
        self.assertEqual(label["name"], "VIP")

    async def test_two_worlds_hold_independent_sets(self):
        id1 = self.store.create("OnlyWorld1", "#00ff00")["id"]
        self.store.assign("Ann", id1)
        await self.store.flush_to_db()

        store2 = make_store(self.db2)
        await store2.load_from_db(self.db2)
        id2 = store2.create("OnlyWorld2", "#0000ff")["id"]
        store2.assign("Bea", id2)
        await store2.flush_to_db()

        reread1 = make_store(self.db1)
        await reread1.load_from_db(self.db1)
        reread2 = make_store(self.db2)
        await reread2.load_from_db(self.db2)

        self.assertEqual([d["name"] for d in reread1.defs()], ["OnlyWorld1"])
        self.assertEqual([d["name"] for d in reread2.defs()], ["OnlyWorld2"])
        self.assertEqual(reread1.labels_for("Bea"), [])
        self.assertEqual(reread2.labels_for("Ann"), [])

    async def test_delete_then_flush_leaves_no_ghost_assignments(self):
        label_id = self.store.create("Temp", DEFAULT_COLOR)["id"]
        self.store.assign("Ann", label_id)
        await self.store.flush_to_db()
        self.assertTrue(self.store.delete(label_id))
        await self.store.flush_to_db()
        fresh = make_store(self.db1)
        await fresh.load_from_db(self.db1)
        self.assertEqual(fresh.defs(), [])
        self.assertEqual(fresh.labels_for("Ann"), [],
                         "the assignment survived the label's deletion")


class TestNormalisation(unittest.TestCase):

    def test_normalize_color_returns_safe_hex(self):
        good = normalize_color("#FF0000")
        self.assertEqual(good, "#ff0000")
        for garbage in ("red", "#fff", "#GGGGGG", "#12345", "", None,
                        "#123456789", "javascript:alert(1)", "#12 56"):
            value = normalize_color(garbage)
            self.assertRegex(value, r"^#[0-9a-f]{6}$",
                             f"{garbage!r} → {value!r} is not #rrggbb")

    def test_normalize_color_fallback_is_honoured(self):
        self.assertEqual(normalize_color("garbage", "#aabbcc"), "#aabbcc")

    def test_normalize_name_caps_and_collapses(self):
        self.assertEqual(normalize_name("  VIP   people "), "VIP people")
        capped = normalize_name("x" * 100)
        self.assertTrue(capped)
        self.assertLessEqual(len(capped), MAX_NAME)
        self.assertEqual(normalize_name("   "), "")
        self.assertEqual(normalize_name(None), "")

    def test_normalize_nick_never_returns_whitespace(self):
        self.assertEqual(normalize_nick("  Ann \n"), "Ann")
        self.assertEqual(normalize_nick(None), "")


class TestSnapshotRestore(DbCase):

    async def test_snapshot_restore_round_trip_is_deep(self):
        label_id = self.store.create("Keep", DEFAULT_COLOR)["id"]
        self.store.assign("Ann", label_id)
        pristine = self.store.snapshot()

        # mutate the live state, then undo back to the snapshot
        extra_id = self.store.create("Extra", DEFAULT_COLOR)["id"]
        self.store.assign("Ann", extra_id)
        self.assertEqual(len(self.store.defs()), 2)
        self.store.restore(pristine)
        self.assertEqual([d["name"] for d in self.store.defs()], ["Keep"])
        self.assertEqual([l["name"] for l in self.store.labels_for("Ann")],
                         ["Keep"])

        # the snapshot is a DEEP copy: mutating it must not touch the store
        scratch = self.store.snapshot()
        scratch["defs"].clear()
        scratch["assign"].clear()
        self.assertEqual([d["name"] for d in self.store.defs()], ["Keep"])
        # restore() of a garbage value is a no-op, not a wipe
        self.store.restore(None)
        self.store.restore("garbage")
        self.assertEqual([d["name"] for d in self.store.defs()], ["Keep"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
