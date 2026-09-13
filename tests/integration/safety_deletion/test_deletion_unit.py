"""Unit coverage for services.db_deletion (inventory/policy/helpers)."""

import os
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))

from services.db_deletion import (  # noqa: E402
    DeletionOutcome, build_deletion_inventory, canonical,
    classify_candidate, collect_discovered_files, is_same_file, is_within,
    plan_deletion, prune_empty_dirs, unlink_one)


def write(path, data=b"x"):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)
    return path


class FakeRegistry:
    def __init__(self, tmp, active, existing, known):
        self._tmp = tmp
        self._active = active
        self._existing = existing
        self._known = known
        self._host = types.SimpleNamespace(root=tmp)
        self._fail_existing = False
        self._fail_active = False
        self._fail_known = False

    def existing_worlds(self):
        if self._fail_existing:
            raise OSError("scan boom")
        return list(self._existing)

    def active_path(self):
        if self._fail_active:
            raise RuntimeError("active boom")
        return self._active

    def known_paths(self):
        if self._fail_known:
            raise RuntimeError("known boom")
        return list(self._known)

    def media_dir(self, path=""):
        from services.db_service import db_stem
        base = os.path.join(self._tmp, "saved_media")
        stem = db_stem(path or self._active)
        return os.path.join(base, stem)


class TestCanonicalWithin(unittest.TestCase):
    def test_canonical_basic(self):
        self.assertTrue(canonical("/tmp/a"))
        self.assertEqual(canonical(""), os.path.realpath(os.path.abspath("")))

    def test_canonical_fallback_on_error(self):
        with mock.patch("os.path.realpath", side_effect=OSError("boom")):
            # falls back to abspath
            self.assertEqual(canonical("/tmp/a"), os.path.abspath("/tmp/a"))
        with mock.patch("os.path.realpath", side_effect=OSError("boom")), \
             mock.patch("os.path.abspath", side_effect=OSError("boom")):
            self.assertEqual(canonical("/tmp/a"), "/tmp/a")

    def test_is_within(self):
        tmp = tempfile.mkdtemp()
        child = os.path.join(tmp, "a", "b.jpg")
        self.assertTrue(is_within(child, tmp))
        self.assertFalse(is_within(tmp, tmp))
        self.assertFalse(is_within("/tmp/other", tmp))
        # different drives (ValueError) → False
        with mock.patch("os.path.commonpath", side_effect=ValueError("x")):
            self.assertFalse(is_within(child, tmp))
        with mock.patch("services.db_deletion_paths.canonical",
                        side_effect=RuntimeError("boom")):
            self.assertFalse(is_within(child, tmp))

    def test_is_same_file(self):
        self.assertTrue(is_same_file("/tmp/a", "/tmp/a"))
        self.assertFalse(is_same_file("/tmp/a", "/tmp/b"))
        with mock.patch("services.db_deletion_paths.canonical",
                        side_effect=RuntimeError("boom")):
            self.assertTrue(is_same_file("/tmp/a", "/tmp/a"))


class TestInventory(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="inv_")
        self.a = os.path.join(self.tmp, "a.db")
        self.b = os.path.join(self.tmp, "b.db")
        open(self.a, "wb").close()
        open(self.b, "wb").close()

    def test_basic_inventory(self):
        reg = FakeRegistry(self.tmp, self.a, [self.a, self.b], [self.a])
        inv = build_deletion_inventory(registry=reg, victim_abs=self.b)
        self.assertTrue(inv.complete)
        self.assertTrue(inv.victim_in_scope)
        self.assertIn(os.path.abspath(self.a),
                      [os.path.abspath(p) for p in inv.worlds])
        self.assertNotIn(os.path.abspath(self.b),
                         [os.path.abspath(p) for p in inv.worlds])

    def test_victim_dir_scan(self):
        sub = os.path.join(self.tmp, "sub")
        os.makedirs(sub, exist_ok=True)
        v = os.path.join(sub, "v.db")
        open(v, "wb").close()
        reg = FakeRegistry(self.tmp, self.a, [self.a], [])
        inv = build_deletion_inventory(registry=reg, victim_abs=v)
        self.assertTrue(inv.complete)
        self.assertTrue(inv.victim_in_scope)

    def test_victim_dir_scan_failure(self):
        sub = os.path.join(self.tmp, "sub2")
        os.makedirs(sub, exist_ok=True)
        v = os.path.join(sub, "v.db")
        open(v, "wb").close()
        reg = FakeRegistry(self.tmp, self.a, [self.a], [])
        with mock.patch("os.listdir", side_effect=OSError("boom")):
            inv = build_deletion_inventory(registry=reg, victim_abs=v)
        self.assertFalse(inv.complete)
        self.assertTrue(any("victim" in d.lower() for d in inv.diagnostics))

    def test_existing_scan_failure(self):
        reg = FakeRegistry(self.tmp, self.a, [self.a], [])
        reg._fail_existing = True
        inv = build_deletion_inventory(registry=reg, victim_abs=self.b)
        self.assertFalse(inv.complete)

    def test_active_failure(self):
        reg = FakeRegistry(self.tmp, self.a, [self.a], [])
        reg._fail_active = True
        inv = build_deletion_inventory(registry=reg, victim_abs=self.b)
        self.assertFalse(inv.complete)

    def test_known_failure(self):
        reg = FakeRegistry(self.tmp, self.a, [self.a], [self.a])
        reg._fail_known = True
        inv = build_deletion_inventory(registry=reg, victim_abs=self.b)
        self.assertFalse(inv.complete)

    def test_known_filters(self):
        outside = "/tmp/outside.db"
        nodb = os.path.join(self.tmp, "x.txt")
        open(nodb, "wb").close()
        missing = os.path.join(self.tmp, "missing.db")
        reg = FakeRegistry(self.tmp, self.a, [self.a],
                           [self.a, outside, nodb, missing, "", 123])
        inv = build_deletion_inventory(registry=reg, victim_abs=self.b)
        self.assertTrue(inv.complete)
        # only in-root existing .db kept (a)
        self.assertIn(os.path.abspath(self.a),
                      [os.path.abspath(p) for p in inv.worlds + inv.all_worlds])

    def test_victim_not_in_scope(self):
        # victim outside root, not discoverable
        reg = FakeRegistry(self.tmp, self.a, [self.a], [])
        inv = build_deletion_inventory(registry=reg,
                                       victim_abs="/tmp/elsewhere.db")
        # victim file doesn't exist, not in union → not in scope
        self.assertFalse(inv.victim_in_scope)

    def test_dedup(self):
        reg = FakeRegistry(self.tmp, self.a, [self.a, self.a, self.b],
                           [self.a, self.a])
        inv = build_deletion_inventory(registry=reg, victim_abs=self.b)
        abspaths = [os.path.abspath(p) for p in inv.all_worlds]
        self.assertEqual(len(abspaths), len(set(abspaths)))


class TestDiscovered(unittest.TestCase):
    def test_missing_folder_empty(self):
        tmp = tempfile.mkdtemp()
        base = os.path.join(tmp, "base")
        os.makedirs(base, exist_ok=True)
        self.assertEqual(collect_discovered_files(
            os.path.join(base, "nope"), base), set())

    def test_outside_base_empty(self):
        tmp = tempfile.mkdtemp()
        base = os.path.join(tmp, "base")
        os.makedirs(base, exist_ok=True)
        outside = os.path.join(tmp, "outside")
        os.makedirs(outside, exist_ok=True)
        write(os.path.join(outside, "a.jpg"))
        self.assertEqual(collect_discovered_files(outside, base), set())

    def test_collects_regular_skips_symlink(self):
        tmp = tempfile.mkdtemp()
        base = os.path.join(tmp, "base")
        folder = os.path.join(base, "victim")
        os.makedirs(os.path.join(folder, "sub"), exist_ok=True)
        a = write(os.path.join(folder, "a.jpg"))
        b = write(os.path.join(folder, "sub", "b.jpg"))
        # symlink file skipped
        link = os.path.join(folder, "link.jpg")
        try:
            os.symlink(a, link)
            has_link = True
        except OSError:
            has_link = False
        # symlink dir pruned
        outside = os.path.join(tmp, "out")
        os.makedirs(outside, exist_ok=True)
        write(os.path.join(outside, "evil.jpg"))
        dlink = os.path.join(folder, "dlink")
        try:
            os.symlink(outside, dlink)
        except OSError:
            pass
        found = collect_discovered_files(folder, base)
        self.assertIn(os.path.abspath(a), found)
        self.assertIn(os.path.abspath(b), found)
        if has_link:
            self.assertNotIn(os.path.abspath(link), found)


class TestClassify(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cls_")
        self.base = os.path.join(self.tmp, "base")
        self.vf = os.path.join(self.base, "victim")
        self.of = os.path.join(self.base, "other")
        os.makedirs(self.vf, exist_ok=True)
        os.makedirs(self.of, exist_ok=True)

    def test_symlink_retained(self):
        a = write(os.path.join(self.vf, "a.jpg"))
        link = os.path.join(self.vf, "l.jpg")
        try:
            os.symlink(a, link)
        except OSError:
            self.skipTest("no symlink")
        v = classify_candidate(candidate_abs=link, base_abs=self.base,
                               victim_folder_abs=self.vf,
                               folder_exclusive=True, keep=frozenset(),
                               other_world_folders=frozenset(),
                               is_discovered=False)
        self.assertEqual(v, "retain:symlink")

    def test_outside_root(self):
        outside = write(os.path.join(self.tmp, "out.jpg"))
        v = classify_candidate(candidate_abs=outside, base_abs=self.base,
                               victim_folder_abs=self.vf,
                               folder_exclusive=True, keep=frozenset(),
                               other_world_folders=frozenset(),
                               is_discovered=False)
        self.assertEqual(v, "retain:outside_root")

    def test_root_itself(self):
        v = classify_candidate(candidate_abs=self.base, base_abs=self.base,
                               victim_folder_abs=self.vf,
                               folder_exclusive=True, keep=frozenset(),
                               other_world_folders=frozenset(),
                               is_discovered=False)
        self.assertEqual(v, "retain:root")

    def test_other_world_folder(self):
        keep = write(os.path.join(self.of, "k.jpg"))
        v = classify_candidate(candidate_abs=keep, base_abs=self.base,
                               victim_folder_abs=self.vf,
                               folder_exclusive=True, keep=frozenset(),
                               other_world_folders=frozenset([self.of]),
                               is_discovered=False)
        self.assertEqual(v, "retain:other_world_folder")
        # exact folder match
        v2 = classify_candidate(candidate_abs=self.of, base_abs=self.base,
                                victim_folder_abs=self.vf,
                                folder_exclusive=True, keep=frozenset(),
                                other_world_folders=frozenset([self.of]),
                                is_discovered=False)
        self.assertEqual(v2, "retain:other_world_folder")

    def test_shared(self):
        a = write(os.path.join(self.vf, "a.jpg"))
        v = classify_candidate(candidate_abs=a, base_abs=self.base,
                               victim_folder_abs=self.vf,
                               folder_exclusive=True,
                               keep=frozenset([os.path.abspath(a)]),
                               other_world_folders=frozenset(),
                               is_discovered=False)
        self.assertEqual(v, "retain:shared")

    def test_ambiguous_discovered(self):
        a = write(os.path.join(self.vf, "a.jpg"))
        v = classify_candidate(candidate_abs=a, base_abs=self.base,
                               victim_folder_abs=self.vf,
                               folder_exclusive=False, keep=frozenset(),
                               other_world_folders=frozenset(),
                               is_discovered=True)
        self.assertEqual(v, "retain:ambiguous_folder")

    def test_missing_and_not_file(self):
        missing = os.path.join(self.vf, "gone.jpg")
        v = classify_candidate(candidate_abs=missing, base_abs=self.base,
                               victim_folder_abs=self.vf,
                               folder_exclusive=True, keep=frozenset(),
                               other_world_folders=frozenset(),
                               is_discovered=False)
        self.assertEqual(v, "retain:missing")
        # dir itself
        v2 = classify_candidate(candidate_abs=self.vf, base_abs=self.base,
                                victim_folder_abs=self.vf,
                                folder_exclusive=True, keep=frozenset(),
                                other_world_folders=frozenset(),
                                is_discovered=False)
        self.assertEqual(v2, "retain:not_file")

    def test_remove(self):
        a = write(os.path.join(self.vf, "a.jpg"))
        v = classify_candidate(candidate_abs=a, base_abs=self.base,
                               victim_folder_abs=self.vf,
                               folder_exclusive=True, keep=frozenset(),
                               other_world_folders=frozenset(),
                               is_discovered=False)
        self.assertEqual(v, "remove")


class TestPlan(unittest.TestCase):
    def test_plan_combines(self):
        tmp = tempfile.mkdtemp()
        base = os.path.join(tmp, "base")
        vf = os.path.join(base, "v")
        os.makedirs(vf, exist_ok=True)
        a = write(os.path.join(vf, "a.jpg"))
        b = write(os.path.join(vf, "b.jpg"))
        shared = write(os.path.join(base, "s.jpg"))
        inv = types.SimpleNamespace(worlds=[], complete=True)
        plan = plan_deletion(victim_abs="/tmp/v.db",
                             victim_folder_abs=vf, media_base_abs=base,
                             footprint_files={a, shared},
                             discovered_files={b},
                             keep={shared}, folder_exclusive=True,
                             other_world_folders=set(), inventory=inv)
        self.assertIn(os.path.abspath(a), plan.candidates)
        self.assertIn(os.path.abspath(b), plan.candidates)
        self.assertIn(os.path.abspath(shared), plan.retained)
        self.assertTrue(plan.folder_exclusive)


class TestUnlinkPrune(unittest.TestCase):
    def test_unlink_missing_ok(self):
        ok, err = unlink_one("/tmp/definitely-missing-xyz-123.jpg")
        self.assertTrue(ok)

    def test_unlink_file_ok(self):
        tmp = tempfile.mkdtemp()
        p = write(os.path.join(tmp, "a.jpg"))
        ok, _ = unlink_one(p)
        self.assertTrue(ok)
        self.assertFalse(os.path.exists(p))

    def test_unlink_symlink_refused(self):
        tmp = tempfile.mkdtemp()
        a = write(os.path.join(tmp, "a.jpg"))
        link = os.path.join(tmp, "l.jpg")
        try:
            os.symlink(a, link)
        except OSError:
            self.skipTest("no symlink")
        ok, _ = unlink_one(link)
        self.assertFalse(ok)
        self.assertTrue(os.path.islink(link))

    def test_unlink_dir_refused(self):
        tmp = tempfile.mkdtemp()
        d = os.path.join(tmp, "d")
        os.makedirs(d, exist_ok=True)
        ok, _ = unlink_one(d)
        self.assertFalse(ok)

    def test_unlink_failure(self):
        with mock.patch("os.unlink", side_effect=OSError("boom")):
            ok, err = unlink_one("/tmp/x.jpg")
        # /tmp/x.jpg missing? lexists False → True before unlink? Use existing
        tmp = tempfile.mkdtemp()
        p = write(os.path.join(tmp, "a.jpg"))
        with mock.patch("os.unlink", side_effect=OSError("boom")):
            ok, err = unlink_one(p)
        self.assertFalse(ok)
        self.assertIn("boom", err)

    def test_prune_empty(self):
        tmp = tempfile.mkdtemp()
        base = os.path.join(tmp, "base")
        d = os.path.join(base, "a", "b")
        os.makedirs(d, exist_ok=True)
        removed = prune_empty_dirs(start_dirs={d}, base_abs=base,
                                   other_world_folders=frozenset())
        self.assertIn(os.path.abspath(d), [os.path.abspath(p) for p in removed])
        self.assertFalse(os.path.exists(d))
        # base itself never removed
        self.assertTrue(os.path.isdir(base))

    def test_prune_skips_nonempty_and_other(self):
        tmp = tempfile.mkdtemp()
        base = os.path.join(tmp, "base")
        other = os.path.join(base, "other")
        os.makedirs(other, exist_ok=True)
        keep = write(os.path.join(other, "k.jpg"))
        # non-empty
        d = os.path.join(base, "d")
        os.makedirs(d, exist_ok=True)
        write(os.path.join(d, "f.jpg"))
        removed = prune_empty_dirs(start_dirs={d, other}, base_abs=base,
                                   other_world_folders=frozenset([other]))
        self.assertEqual(removed, [])
        self.assertTrue(os.path.exists(keep))

    def test_prune_skips_symlink_and_outside(self):
        tmp = tempfile.mkdtemp()
        base = os.path.join(tmp, "base")
        os.makedirs(base, exist_ok=True)
        outside = os.path.join(tmp, "out")
        os.makedirs(outside, exist_ok=True)
        removed = prune_empty_dirs(start_dirs={outside}, base_abs=base,
                                   other_world_folders=frozenset())
        self.assertEqual(removed, [])


class TestOutcome(unittest.TestCase):
    def test_as_dict(self):
        o = DeletionOutcome(ok=True, phase="finalize", path="/tmp/v.db",
                            before_path="/tmp/v.db", was_active=True,
                            active_path="/tmp/a.db", removed_paths=["/tmp/v.db"],
                            retained_paths=[], failed_paths=[],
                            media_files_removed=1)
        d = o.as_dict()
        self.assertTrue(d["ok"])
        self.assertEqual(d["op"], "delete")
        self.assertEqual(d["phase"], "finalize")
        o2 = DeletionOutcome(ok=False, phase="scan", error="boom",
                             path="/tmp/v.db", extra={"last_database": True,
                                                      "unverifiable_worlds": ["x"]})
        d2 = o2.as_dict()
        self.assertIn("last_database", d2)
        self.assertIn("error", d2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
