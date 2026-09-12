"""Defensive-branch coverage for services.db_deletion."""

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

# `canonical` is patched on the module that OWNS it, not on the `db_deletion`
# shim: since the 2026-09-12 family split every caller looks it up through
# `db_deletion_paths`, so patching there governs all of them. Patching the shim
# would silently no-op and leave these defensive tests passing vacuously.
import services.db_deletion_inventory as INV  # noqa: E402
import services.db_deletion_paths as PATHS  # noqa: E402
from services.db_deletion import (  # noqa: E402
    DeletionOutcome, build_deletion_inventory, canonical,
    classify_candidate, collect_discovered_files, plan_deletion,
    prune_empty_dirs, unlink_one)


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

    def existing_worlds(self):
        return list(self._existing)

    def active_path(self):
        return self._active

    def known_paths(self):
        return list(self._known)


class BareRegistry:
    """No _host/root (covers root-empty branch)."""

    def __init__(self, active, existing, known):
        self._active = active
        self._existing = existing
        self._known = known

    def existing_worlds(self):
        return list(self._existing)

    def active_path(self):
        return self._active

    def known_paths(self):
        return list(self._known)


class TestDedupDefensive(unittest.TestCase):
    def test_canonical_raises(self):
        with mock.patch.object(PATHS, "canonical",
                               side_effect=RuntimeError("boom")):
            # falls back to abspath
            out = INV._dedup(["/tmp/a.db", "/tmp/a.db", "/tmp/b.db"])
        self.assertEqual(len(out), 2)


class TestInventoryDefensive(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="invd_")
        self.a = os.path.join(self.tmp, "a.db")
        open(self.a, "wb").close()

    def test_isfile_raises_in_victim_scan(self):
        sub = os.path.join(self.tmp, "sub")
        os.makedirs(sub, exist_ok=True)
        v = os.path.join(sub, "v.db")
        open(v, "wb").close()
        reg = FakeRegistry(self.tmp, self.a, [self.a], [])
        real_isfile = os.path.isfile

        def boom(p):
            raise OSError("stat boom")

        with mock.patch("os.path.isfile", side_effect=boom):
            # victim dir scan hits OSError per-file → skipped, still complete
            # (active exists check also mocked, but exists uses stat not isfile)
            inv = build_deletion_inventory(registry=reg, victim_abs=v)
        # isfile mocked also affects victim-scope? victim exists via exists(),
        # so in_scope still True; per-file OSError is swallowed.
        self.assertTrue(inv.complete)

    def test_victim_dirname_raises(self):
        reg = FakeRegistry(self.tmp, self.a, [self.a], [])
        with mock.patch("os.path.dirname", side_effect=RuntimeError("boom")):
            inv = build_deletion_inventory(registry=reg, victim_abs=self.a)
        self.assertFalse(inv.complete)
        self.assertTrue(any("victim directory handling" in d
                            for d in inv.diagnostics))

    def test_known_ap_abspath_raises(self):
        # known path differs from victim/active so the mock is surgical.
        b = os.path.join(self.tmp, "b.db")
        open(b, "wb").close()
        reg = FakeRegistry(self.tmp, self.a, [self.a], [b])
        real_abspath = os.path.abspath

        def boom(p):
            if os.path.basename(str(p)) == "b.db":
                raise RuntimeError("ap boom")
            return real_abspath(p)

        with mock.patch("os.path.abspath", side_effect=boom):
            inv = build_deletion_inventory(registry=reg, victim_abs=self.a)
        # bad known entry skipped, inventory still complete
        self.assertTrue(inv.complete)

    def test_commonpath_valueerror(self):
        reg = FakeRegistry(self.tmp, self.a, [self.a], [self.a])
        with mock.patch("os.path.commonpath",
                        side_effect=ValueError("mix")):
            inv = build_deletion_inventory(registry=reg, victim_abs=self.a)
        self.assertTrue(inv.complete)

    def test_exists_raises_in_known(self):
        b = os.path.join(self.tmp, "b.db")
        open(b, "wb").close()
        reg = FakeRegistry(self.tmp, self.a, [self.a], [b])
        real_exists = os.path.exists

        def boom(p):
            if os.path.basename(str(p)) == "b.db":
                raise OSError("exists boom")
            return real_exists(p)

        with mock.patch("os.path.exists", side_effect=boom):
            inv = build_deletion_inventory(registry=reg, victim_abs=self.a)
        self.assertTrue(inv.complete)

    def test_victim_exists_raises(self):
        # victim differs from active so the mock only hits the scope check.
        b = os.path.join(self.tmp, "b.db")
        open(b, "wb").close()
        reg = FakeRegistry(self.tmp, self.a, [self.a], [])
        real_exists = os.path.exists

        def boom(p):
            if os.path.basename(str(p)) == "b.db":
                raise OSError("victim boom")
            return real_exists(p)

        with mock.patch("os.path.exists", side_effect=boom):
            inv = build_deletion_inventory(registry=reg, victim_abs=b)
        # swallowed (pass) → out of scope but complete
        self.assertTrue(inv.complete)
        self.assertFalse(inv.victim_in_scope)

    def test_bare_registry_no_root(self):
        reg = BareRegistry(self.a, [self.a], [self.a])
        inv = build_deletion_inventory(registry=reg, victim_abs=self.a)
        self.assertTrue(inv.complete)

    def test_host_root_property_raises(self):
        reg = FakeRegistry(self.tmp, self.a, [self.a], [self.a])

        class BadHost:
            @property
            def root(self):
                raise RuntimeError("root boom")

        reg._host = BadHost()
        inv = build_deletion_inventory(registry=reg, victim_abs=self.a)
        self.assertTrue(inv.complete)

    def test_active_none_skipped(self):
        # active falsy → `if active and exists` False branch (114->121).
        reg = FakeRegistry(self.tmp, None, [self.a], [])
        inv = build_deletion_inventory(registry=reg, victim_abs=self.a)
        self.assertTrue(inv.complete)

    def test_victim_dir_db_directory_skipped(self):
        # a directory named *.db → isfile False branch (136->131).
        sub = os.path.join(self.tmp, "subd")
        os.makedirs(os.path.join(sub, "weird.db"), exist_ok=True)
        v = os.path.join(sub, "v.db")
        open(v, "wb").close()
        reg = FakeRegistry(self.tmp, self.a, [self.a], [])
        inv = build_deletion_inventory(registry=reg, victim_abs=v)
        self.assertTrue(inv.complete)

    def test_victim_canonical_empty(self):
        # victim_c falsy → in_scope False (covers `if victim_c else False`).
        reg = FakeRegistry(self.tmp, self.a, [self.a], [])
        with mock.patch.object(PATHS, "canonical", return_value=""):
            inv = build_deletion_inventory(registry=reg, victim_abs=self.a)
        self.assertFalse(inv.victim_in_scope)


class TestDiscoveredDefensive(unittest.TestCase):
    def test_dir_islink_raises(self):
        tmp = tempfile.mkdtemp()
        base = os.path.join(tmp, "base")
        folder = os.path.join(base, "v")
        os.makedirs(os.path.join(folder, "sub"), exist_ok=True)
        write(os.path.join(folder, "sub", "a.jpg"))
        real_islink = os.path.islink

        def boom(p):
            if p.endswith("sub"):
                raise OSError("link boom")
            return real_islink(p)

        with mock.patch("os.path.islink", side_effect=boom):
            found = collect_discovered_files(folder, base)
        # sub pruned → nothing found, no crash
        self.assertEqual(found, set())

    def test_file_checks_raise(self):
        tmp = tempfile.mkdtemp()
        base = os.path.join(tmp, "base")
        folder = os.path.join(base, "v")
        os.makedirs(folder, exist_ok=True)
        write(os.path.join(folder, "a.jpg"))
        with mock.patch("os.path.islink", side_effect=OSError("boom")):
            found = collect_discovered_files(folder, base)
        self.assertEqual(found, set())

    def test_not_regular_file_skipped(self):
        tmp = tempfile.mkdtemp()
        base = os.path.join(tmp, "base")
        folder = os.path.join(base, "v")
        os.makedirs(folder, exist_ok=True)
        write(os.path.join(folder, "a.jpg"))
        with mock.patch("os.path.islink", return_value=False), \
             mock.patch("os.path.isfile", return_value=False):
            found = collect_discovered_files(folder, base)
        self.assertEqual(found, set())


class TestClassifyDefensive(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cld_")
        self.base = os.path.join(self.tmp, "base")
        self.vf = os.path.join(self.base, "v")
        os.makedirs(self.vf, exist_ok=True)

    def test_islink_raises_retains(self):
        a = write(os.path.join(self.vf, "a.jpg"))
        with mock.patch("os.path.islink", side_effect=OSError("boom")):
            v = classify_candidate(
                candidate_abs=a, base_abs=self.base,
                victim_folder_abs=self.vf, folder_exclusive=True,
                keep=frozenset(), other_world_folders=frozenset(),
                is_discovered=False)
        self.assertEqual(v, "retain:symlink")

    def test_canonical_raises_outside(self):
        outside = write(os.path.join(self.tmp, "o.jpg"))
        with mock.patch.object(PATHS, "canonical",
                               side_effect=RuntimeError("boom")):
            v = classify_candidate(
                candidate_abs=outside, base_abs=self.base,
                victim_folder_abs=self.vf, folder_exclusive=True,
                keep=frozenset(), other_world_folders=frozenset(),
                is_discovered=False)
        # is_within False (canonical boom) → root check also booms → outside
        self.assertEqual(v, "retain:outside_root")

    def test_canonical_raises_root_check(self):
        a = write(os.path.join(self.vf, "a.jpg"))
        calls = {"n": 0}
        real = canonical

        def flaky(p):
            calls["n"] += 1
            # succeed for is_within (first calls), fail later for root check
            if calls["n"] > 4:
                raise RuntimeError("boom")
            return real(p)

        with mock.patch.object(PATHS, "canonical", side_effect=flaky):
            v = classify_candidate(
                candidate_abs=a, base_abs=self.base,
                victim_folder_abs=self.vf, folder_exclusive=True,
                keep=frozenset(), other_world_folders=frozenset(),
                is_discovered=False)
        # root check swallowed → falls through to remove (regular file)
        self.assertEqual(v, "remove")

    def test_other_canonical_raises(self):
        a = write(os.path.join(self.vf, "a.jpg"))
        real = canonical

        def flaky(p):
            if p == "/tmp/bad-other":
                raise RuntimeError("boom")
            return real(p)

        with mock.patch.object(PATHS, "canonical", side_effect=flaky):
            v = classify_candidate(
                candidate_abs=a, base_abs=self.base,
                victim_folder_abs=self.vf, folder_exclusive=True,
                keep=frozenset(),
                other_world_folders=frozenset(["/tmp/bad-other"]),
                is_discovered=False)
        self.assertEqual(v, "remove")

    def test_commonpath_valueerror_other(self):
        a = write(os.path.join(self.vf, "a.jpg"))
        real_common = os.path.commonpath
        calls = {"n": 0}

        def flaky(paths):
            calls["n"] += 1
            # 1st call is is_within (must succeed); later calls are the
            # other-world check (fail → swallowed → not other-world).
            if calls["n"] == 1:
                return real_common(paths)
            raise ValueError("mix")

        with mock.patch("os.path.commonpath", side_effect=flaky):
            v = classify_candidate(
                candidate_abs=a, base_abs=self.base,
                victim_folder_abs=self.vf, folder_exclusive=True,
                keep=frozenset(),
                other_world_folders=frozenset([self.base]),
                is_discovered=False)
        # ValueError swallowed → not other-world → remove
        self.assertEqual(v, "remove")

    def test_keep_entry_raises(self):
        a = write(os.path.join(self.vf, "a.jpg"))

        class Bad:
            def __str__(self):
                raise RuntimeError("boom")

        v = classify_candidate(
            candidate_abs=a, base_abs=self.base,
            victim_folder_abs=self.vf, folder_exclusive=True,
            keep=frozenset([Bad()]), other_world_folders=frozenset(),
            is_discovered=False)
        self.assertEqual(v, "remove")

    def test_keep_block_raises(self):
        a = write(os.path.join(self.vf, "a.jpg"))
        real = canonical
        calls = {"n": 0}

        def flaky(p):
            calls["n"] += 1
            # fail only deep into keep comparison
            if calls["n"] > 8:
                raise RuntimeError("boom")
            return real(p)

        with mock.patch.object(PATHS, "canonical", side_effect=flaky):
            v = classify_candidate(
                candidate_abs=a, base_abs=self.base,
                victim_folder_abs=self.vf, folder_exclusive=True,
                keep=frozenset([a]), other_world_folders=frozenset(),
                is_discovered=False)
        self.assertIn(v, ("remove", "retain:shared"))

    def test_isfile_raises(self):
        a = write(os.path.join(self.vf, "a.jpg"))
        with mock.patch("os.path.isfile", side_effect=OSError("boom")):
            v = classify_candidate(
                candidate_abs=a, base_abs=self.base,
                victim_folder_abs=self.vf, folder_exclusive=True,
                keep=frozenset(), other_world_folders=frozenset(),
                is_discovered=False)
        self.assertEqual(v, "retain:not_file")


class TestPlanDefensive(unittest.TestCase):
    def test_discovered_retained_and_dupes(self):
        import types as _t
        tmp = tempfile.mkdtemp()
        base = os.path.join(tmp, "base")
        vf = os.path.join(base, "v")
        os.makedirs(vf, exist_ok=True)
        a = write(os.path.join(vf, "a.jpg"))
        shared = write(os.path.join(vf, "s.jpg"))
        inv = _t.SimpleNamespace(worlds=[], complete=True)
        plan = plan_deletion(
            victim_abs="/tmp/v.db", victim_folder_abs=vf,
            media_base_abs=base, footprint_files={a},
            discovered_files={a, shared}, keep={shared},
            folder_exclusive=True, other_world_folders=set(),
            inventory=inv)
        # a dup skipped; shared discovered → retained
        self.assertIn(os.path.abspath(shared), plan.retained)
        self.assertIn(os.path.abspath(a), plan.candidates)


class TestUnlinkDefensive(unittest.TestCase):
    def test_guard_raises(self):
        with mock.patch("os.path.islink", side_effect=OSError("boom")):
            ok, err = unlink_one("/tmp/x.jpg")
        self.assertFalse(ok)
        self.assertIn("boom", err)

    def test_race_not_found(self):
        tmp = tempfile.mkdtemp()
        p = write(os.path.join(tmp, "a.jpg"))
        with mock.patch("os.unlink",
                        side_effect=FileNotFoundError("gone")):
            ok, _ = unlink_one(p)
        self.assertTrue(ok)


class TestPruneDefensive(unittest.TestCase):
    def test_base_canonical_raises(self):
        tmp = tempfile.mkdtemp()
        base = os.path.join(tmp, "base")
        d = os.path.join(base, "a")
        os.makedirs(d, exist_ok=True)
        real = canonical
        calls = {"n": 0}

        def flaky(p):
            # fail only the first call (base_c lookup); later calls
            # (is_within etc.) must succeed.
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("boom")
            return real(p)

        with mock.patch.object(PATHS, "canonical", side_effect=flaky):
            removed = prune_empty_dirs(
                start_dirs={d}, base_abs=base,
                other_world_folders=frozenset())
        # base_c fallback → still prunes empty dir
        self.assertIn(d, removed)

    def test_other_canonical_raises(self):
        tmp = tempfile.mkdtemp()
        base = os.path.join(tmp, "base")
        d = os.path.join(base, "a")
        os.makedirs(d, exist_ok=True)
        real = canonical

        def flaky(p):
            if "bad" in str(p):
                raise RuntimeError("boom")
            return real(p)

        with mock.patch.object(PATHS, "canonical", side_effect=flaky):
            removed = prune_empty_dirs(
                start_dirs={d}, base_abs=base,
                other_world_folders=frozenset(["/tmp/bad-other"]))
        self.assertIn(d, removed)

    def test_folder_canonical_raises(self):
        tmp = tempfile.mkdtemp()
        base = os.path.join(tmp, "base")
        d = os.path.join(base, "a")
        os.makedirs(d, exist_ok=True)
        with mock.patch.object(PATHS, "canonical",
                               side_effect=RuntimeError("boom")):
            removed = prune_empty_dirs(
                start_dirs={d}, base_abs=base,
                other_world_folders=frozenset())
        self.assertEqual(removed, [])

    def test_symlink_dir_breaks(self):
        tmp = tempfile.mkdtemp()
        base = os.path.join(tmp, "base")
        real = os.path.join(base, "real")
        os.makedirs(real, exist_ok=True)
        link = os.path.join(base, "link")
        try:
            os.symlink(real, link)
        except OSError:
            self.skipTest("no symlink")
        removed = prune_empty_dirs(
            start_dirs={link}, base_abs=base,
            other_world_folders=frozenset())
        self.assertEqual(removed, [])

    def test_listdir_raises(self):
        tmp = tempfile.mkdtemp()
        base = os.path.join(tmp, "base")
        d = os.path.join(base, "a")
        os.makedirs(d, exist_ok=True)
        with mock.patch("os.listdir", side_effect=OSError("boom")):
            removed = prune_empty_dirs(
                start_dirs={d}, base_abs=base,
                other_world_folders=frozenset())
        self.assertEqual(removed, [])

    def test_rmdir_raises(self):
        tmp = tempfile.mkdtemp()
        base = os.path.join(tmp, "base")
        d = os.path.join(base, "a")
        os.makedirs(d, exist_ok=True)
        with mock.patch("os.rmdir", side_effect=OSError("busy")):
            removed = prune_empty_dirs(
                start_dirs={d}, base_abs=base,
                other_world_folders=frozenset())
        self.assertEqual(removed, [])


    def test_shared_parent_seen(self):
        # two starts sharing a parent → while re-entry via seen (437->435).
        tmp = tempfile.mkdtemp()
        base = os.path.join(tmp, "base")
        d1 = os.path.join(base, "a", "x")
        d2 = os.path.join(base, "a", "y")
        os.makedirs(d1, exist_ok=True)
        os.makedirs(d2, exist_ok=True)
        removed = prune_empty_dirs(
            start_dirs={d1, d2}, base_abs=base,
            other_world_folders=frozenset())
        self.assertIn(d1, removed)
        self.assertIn(d2, removed)


class TestOutcomeDefensive(unittest.TestCase):
    def test_extra_duplicate_key_ignored(self):
        o = DeletionOutcome(ok=True, phase="media", path="/tmp/v.db",
                            extra={"ok": False, "custom": 1})
        d = o.as_dict()
        self.assertTrue(d["ok"])
        self.assertEqual(d["custom"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
