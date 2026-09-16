"""Round F step F8 — `stores/` counts as 15 §18.3 modules, not 37 loose files.

`docs/current/AGENT_RULES.md` §18.3 caps a directory at ~15 cohesive files and
offers two remedies past it: promote a family to a sub-package, or treat a
prefix family as one module — "a family is a module in everything but the
directory separator; treat it as one when counting."

The sub-package remedy is closed to `stores/` by a contract, not by effort:
`test_stores_public_api.py` fails on any change to the frozen surface recorded
in `api_baseline.json`, whose keys are dotted module paths, and plan §7.3
rule 1 forbids moves of any symbol another area imports. Merging files is
closed too — it would undo the AREA B2 splits and lands outside §18.2's
150-300 line band. So F8 takes the counting remedy.

This test does not re-implement the grouping rules; `tools/metrics/
stores_modules.py` owns them so the report and the gate cannot drift apart.
What is asserted here is the verdict, the structural invariants the tool does
not own (chiefly that AREA B's three frozen modules are still loose at the top
level of `stores/`, i.e. F8 moved nothing), and that the evidence checks are
capable of failing — a gate that cannot fail is decoration.

Design ref: docs/archive/2026-09-12-round-f-size-tail/ROUND_F_DESIGN_2026-09-12.md §11.
Run with:  python3 tests/unit/stores/test_stores_module_families.py
      or:  python3 tools/metrics/stores_modules.py
"""

import importlib.util
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)

_spec = importlib.util.spec_from_file_location(
    "stores_modules", os.path.join(ROOT, "tools", "metrics",
                                   "stores_modules.py"))
stores_modules = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(stores_modules)

#: AREA B's frozen modules — `test_stores_public_api.py::FROZEN` without the
#: package prefix. They must stay exactly where they are.
FROZEN_MODULES = ("history_models", "jsonio", "migration")


def measurement():
    return stores_modules.measure()


class TestTheCountFits(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.got = measurement()

    def test_the_effective_module_count_is_within_the_ratchet(self):
        self.assertLessEqual(self.got["effective_modules"],
                             stores_modules.RATCHET)
        self.assertEqual(self.got["problems"], [],
                         "the grouping lost its evidence — every group has to "
                         "justify itself from the import graph")

    def test_the_counting_actually_collapses_something(self):
        """Without this the ratchet could pass by counting files one by one."""
        self.assertGreater(self.got["raw_files"],
                           self.got["effective_modules"])

    def test_no_module_belongs_to_two_groups_and_none_is_left_out(self):
        claimed = sorted(m for group in self.got["groups"]
                         for m in group["members"])
        self.assertEqual(claimed, stores_modules.modules(),
                         "every module in stores/ belongs to exactly one "
                         "group, so a new loose file forces a decision "
                         "instead of silently inflating the count")
        self.assertEqual(len(claimed), len(set(claimed)))

    def test_no_group_is_bigger_than_one_module_may_be(self):
        for group in self.got["groups"]:
            self.assertLessEqual(group["files"],
                                 stores_modules.file_band(group),
                                 f"{group['module']} is a directory in all "
                                 "but name; §18.3 wants it split further")
            self.assertGreaterEqual(group["files"], 1)


class TestNothingWasMoved(unittest.TestCase):
    """F8 is a measurement, not a refactor: no file changed directory."""

    def test_the_three_frozen_modules_are_still_loose_at_the_top_level(self):
        on_disk = set(os.listdir(os.path.join(ROOT, "stores")))
        for name in FROZEN_MODULES:
            self.assertIn(name + ".py", on_disk,
                          f"stores/{name}.py moved — that breaks AREA B's "
                          "frozen surface and test_stores_public_api.py")

    def test_stores_has_no_sub_packages(self):
        """A sub-package would change every dotted path in api_baseline.json."""
        packages = [entry for entry in os.listdir(os.path.join(ROOT, "stores"))
                    if os.path.isdir(os.path.join(ROOT, "stores", entry))
                    and os.path.exists(os.path.join(ROOT, "stores", entry,
                                                    "__init__.py"))]
        self.assertEqual(packages, [],
                         "stores/ gained a sub-package; §18.3's sub-package "
                         "remedy is closed to stores/ by AREA B's frozen "
                         "surface — use the family counting instead")

    def test_the_grouping_names_only_real_modules(self):
        on_disk = set(stores_modules.modules())
        for group in measurement()["groups"]:
            for member in group["members"]:
                self.assertIn(member, on_disk)


class TestTheEvidenceChecksCanFail(unittest.TestCase):
    """Negative controls, run against the real import graph."""

    def setUp(self):
        self.mods = stores_modules.modules()
        self.deps = {m: stores_modules.imports_of(m) for m in self.mods}

    def test_a_collaborator_with_more_than_one_consumer_is_rejected(self):
        # json_store is imported by eight domain stores, so it can never pass
        # as a collaborator that belongs to exactly one aggregate.
        members, problems = stores_modules.check(
            {"name": "probe", "kind": "pair", "aggregate": "block_store",
             "collaborator": "json_store"}, self.mods, self.deps)
        self.assertTrue(problems)
        self.assertIn("json_store", problems[0])
        self.assertEqual(members, ["block_store", "json_store"])

    def test_a_layer_whose_root_does_not_import_a_part_is_rejected(self):
        _, problems = stores_modules.check(
            {"name": "probe", "kind": "layer", "root": "json_store",
             "parts": ["world_lock"]}, self.mods, self.deps)
        self.assertTrue(problems)
        self.assertIn("does not import", problems[0])

    def test_a_prefix_that_matches_nothing_is_rejected(self):
        members, problems = stores_modules.check(
            {"name": "probe", "kind": "prefix", "prefix": "nonexistent_"},
            self.mods, self.deps)
        self.assertEqual(members, [])
        self.assertTrue(problems)

    def test_a_group_naming_a_module_that_does_not_exist_is_rejected(self):
        _, problems = stores_modules.check(
            {"name": "probe", "kind": "single", "module": "not_a_store"},
            self.mods, self.deps)
        self.assertTrue(problems)
        self.assertIn("do not exist", problems[0])

    def test_the_real_pairs_do_have_exactly_one_consumer(self):
        for group in stores_modules.GROUPS:
            if group["kind"] != "pair":
                continue
            importers = [m for m in self.mods
                         if group["collaborator"] in self.deps[m]]
            self.assertEqual(importers, [group["aggregate"]],
                             f"{group['collaborator']} is only defensible as "
                             f"part of {group['aggregate']}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
