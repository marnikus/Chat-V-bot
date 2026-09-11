"""A world that cannot be inspected stops the delete instead of being skipped.

`_resolve_folder_policy` builds `other_folders`, the set that keeps every
other world's media out of the removal list. A world whose media folder
lookup raised used to be skipped, which silently dropped that world's
protection — the opposite of this pipeline's stated contract ("any
unverifiable world or unplannable target raises `_PhaseRefusal`",
services/db_deletion_scan.py). The same rule now holds inside the policy
ladder: a guard that cannot resolve a path retains the file, and `_validate`
refuses when it cannot tell whether the victim is the live database.

Deleting less is recoverable; deleting more is not, so every one of these
branches answers the doubt with "keep".
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import services.db_deletion as D  # noqa: E402
from services.db_deletion import classify_candidate  # noqa: E402
from services.db_deletion_flow import (  # noqa: E402
    _DeleteState, _PhaseRefusal, _validate)
from services.db_deletion_scan import _other_world_folders  # noqa: E402


class _Registry:
    """Minimal registry stand-in: answers media_dir, or raises for a world."""

    def __init__(self, fails=(), active=None):
        self.fails = set(fails)
        self.active = active

    def media_dir(self, path=""):
        if path in self.fails:
            raise RuntimeError("injected unreadable world")
        return os.path.join("/media", os.path.basename(path))

    def active_path(self):
        if self.active is None:
            raise RuntimeError("injected unreadable active world")
        return self.active


class _Inventory:
    def __init__(self, worlds):
        self.worlds = list(worlds)


class TestUnverifiableWorld(unittest.TestCase):
    def test_unreadable_other_world_refuses_the_deletion(self):
        st = _DeleteState(path="/w/victim.db", registry=_Registry(
            fails=["/w/other.db"]))
        with self.assertRaises(_PhaseRefusal) as caught:
            _other_world_folders(st, _Inventory(["/w/other.db"]))
        outcome = caught.exception.outcome
        self.assertEqual(outcome["phase"], "scan")
        self.assertIn("cannot resolve the media folder", outcome["error"])
        self.assertEqual(["/w/other.db"],
                         outcome["unverifiable_worlds"])

    def test_readable_other_worlds_are_all_collected(self):
        st = _DeleteState(path="/w/victim.db", registry=_Registry())
        folders = _other_world_folders(
            st, _Inventory(["/w/a.db", "/w/b.db"]))
        self.assertEqual(folders, {os.path.join("/media", "a.db"),
                                   os.path.join("/media", "b.db")})


class TestLadderFailsClosed(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="failclosed_")
        self.base = os.path.join(self.tmp, "base")
        self.victim = os.path.join(self.base, "victim")
        os.makedirs(self.victim, exist_ok=True)
        self.cand = os.path.join(self.victim, "a.jpg")
        with open(self.cand, "wb") as fh:
            fh.write(b"x")

    def classify(self, **kw):
        args = dict(candidate_abs=self.cand, base_abs=self.base,
                    victim_folder_abs=self.victim, folder_exclusive=True,
                    keep=frozenset(), other_world_folders=frozenset(),
                    is_discovered=False)
        args.update(kw)
        return classify_candidate(**args)

    def test_unreadable_other_folder_retains_instead_of_removing(self):
        real = D.canonical

        def flaky(path):
            if "other" in str(path):
                raise RuntimeError("boom")
            return real(path)

        with mock.patch.object(D, "canonical", side_effect=flaky):
            verdict = self.classify(
                other_world_folders=frozenset(["/base/other"]))
        self.assertEqual(verdict, "retain:other_world_folder",
                         "an unresolvable folder still protects its files")

    def test_unreadable_keep_entry_retains_instead_of_removing(self):
        class Unprintable:
            def __str__(self):
                raise RuntimeError("boom")

        verdict = self.classify(keep=frozenset([Unprintable()]))
        self.assertEqual(verdict, "retain:shared")

    def test_a_broken_resolver_retains_even_a_plain_removal(self):
        with mock.patch.object(D, "canonical",
                               side_effect=RuntimeError("boom")):
            verdict = self.classify()
        self.assertNotEqual(verdict, "remove")
        self.assertTrue(verdict.startswith("retain:"), verdict)

    def test_the_happy_path_still_removes(self):
        self.assertEqual(self.classify(), "remove")


class TestUnknownActiveState(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="active_")
        self.victim = os.path.join(self.tmp, "victim.db")
        with open(self.victim, "wb") as fh:
            fh.write(b"")

    def _registry(self):
        reg = _Registry(active=None)
        reg.resolve = lambda path: path
        reg.existing_worlds = lambda: [self.victim,
                                       os.path.join(self.tmp, "other.db")]
        return reg

    def test_unknown_active_state_refuses_before_touching_anything(self):
        st = _DeleteState(path=self.victim, registry=self._registry())
        with self.assertRaises(_PhaseRefusal) as caught:
            _validate(None, st)
        outcome = caught.exception.outcome
        self.assertEqual(outcome["phase"], "validate")
        self.assertIn("cannot tell whether that database is the active one",
                      outcome["error"])
        self.assertTrue(os.path.exists(self.victim))

    def test_a_readable_active_state_still_passes_validation(self):
        st = _DeleteState(path=self.victim, registry=_Registry(
            active=self.victim))
        st.registry.resolve = lambda path: path
        st.registry.existing_worlds = lambda: [
            self.victim, os.path.join(self.tmp, "other.db")]
        _validate(None, st)                      # doubt gone: no refusal
        self.assertTrue(st.was_active)


if __name__ == "__main__":
    unittest.main(verbosity=2)
