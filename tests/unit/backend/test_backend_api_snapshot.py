"""Golden-file proof that AREA D changed no public API (plan §8.3 Gate 6).

`tools/metrics/dump_public_api.py --write` snapshots, for every module of
`backend/` and `actions/`: the signature of each public function, each public
class (bases, public method signatures, public class attributes, dataclass
fields) and each public constant — plus, for the shipped blocks, the
`__init__` signature, `config_schema()` and the default `to_dict()`, which
together ARE the preset wire format (AGENT_RULES RULE 3).

The rule this enforces is asymmetric on purpose:

  * NEW public symbols are allowed (a refactor may expose more than it hid);
  * CHANGED or REMOVED ones are a cross-area break and fail here.

Refresh the snapshot only when a change is intentional and coordinated:
    python3 tools/metrics/dump_public_api.py --write

Design ref: docs/REFACTOR_2026-09-09_AREA_D_DESIGN.md §1 (frozen contracts).

Run with:  python3 tests/unit/backend/test_backend_api_snapshot.py
"""

import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools", "metrics"))

from dump_public_api import (  # noqa: E402
    BLOCKS, SNAPSHOT, build,
)


def _load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


class TestPublicApiSnapshot(unittest.TestCase):
    """backend/ + actions/ — nothing removed, nothing re-signatured."""

    @classmethod
    def setUpClass(cls):
        cls.expected = _load(SNAPSHOT)
        cls.actual = build()["public_api"]

    def test_snapshot_covers_both_packages(self):
        modules = set(self.expected["public_api"])
        self.assertIn("backend.chat_parser", modules)
        self.assertIn("backend.scroll_parser", modules)
        self.assertIn("actions.base", modules)
        # 50 at the AREA D snapshot; INTEGRATION-01/I1+I3 removed exactly 12
        # (the 11 test-only shims + backend.chat_agent_js, re-homed to core/)
        # — the removal set is pinned independently by
        # tests/integration/test_post_merge_contract.py::TestShimsAreRetired.
        self.assertGreaterEqual(len(modules), 38,
                                "the snapshot must cover every module of "
                                "backend/ and actions/")

    def test_no_module_disappeared_or_failed_to_import(self):
        for qualname in self.expected["public_api"]:
            now = self.actual.get(qualname)
            self.assertIsNotNone(now, f"{qualname} can no longer be imported")
            self.assertNotIn("import_error", now,
                             f"{qualname} fails to import: {now.get('import_error')}")

    def test_public_functions_keep_their_signature(self):
        drift = []
        for qualname, mod in self.expected["public_api"].items():
            now = self.actual.get(qualname, {})
            for name, want in mod["functions"].items():
                if name not in now["functions"]:
                    drift.append(f"{qualname}.{name} removed")
                elif now["functions"][name] != want:
                    drift.append(f"{qualname}.{name}: {want} → "
                                 f"{now['functions'][name]}")
        self.assertEqual(drift, [], "public function signatures drifted:\n"
                         + "\n".join(drift))

    def test_public_classes_keep_their_surface(self):
        drift = []
        for qualname, mod in self.expected["public_api"].items():
            now = self.actual.get(qualname, {}).get("classes", {})
            for name, want in mod["classes"].items():
                if name not in now:
                    drift.append(f"{qualname}.{name} removed")
                    continue
                have = now[name]
                for method, sig in want["methods"].items():
                    if method in have["methods"]:
                        if have["methods"][method] != sig:
                            drift.append(f"{qualname}.{name}.{method}: {sig} "
                                         f"→ {have['methods'][method]}")
                    elif have.get("inherited", {}).get(method) == sig:
                        continue    # moved into a shared base — same surface
                    else:
                        drift.append(f"{qualname}.{name}.{method} removed")
                for base in want.get("bases", []):
                    # `object` is the floor every class keeps; a base may move up
                    # the MRO or gain parents, but must stay an ancestor
                    if base not in have.get("ancestry", [])[1:]:
                        drift.append(f"{qualname}.{name} no longer inherits "
                                     f"{base}")
                for attr, value in want["attrs"].items():
                    if attr not in have["attrs"]:
                        drift.append(f"{qualname}.{name}.{attr} removed")
                    elif have["attrs"][attr] != value:
                        drift.append(f"{qualname}.{name}.{attr}: {value} → "
                                     f"{have['attrs'][attr]}")
                for field, spec in want.get("fields", {}).items():
                    if have.get("fields", {}).get(field) != spec:
                        drift.append(f"{qualname}.{name} field {field} changed")
        self.assertEqual(drift, [], "public class surfaces drifted:\n"
                         + "\n".join(drift))

    def test_public_constants_keep_their_value(self):
        drift = []
        for qualname, mod in self.expected["public_api"].items():
            now = self.actual.get(qualname, {}).get("values", {})
            for name, want in mod.get("values", {}).items():
                if now.get(name) != want:
                    drift.append(f"{qualname}.{name}: {want} → {now.get(name)}")
        self.assertEqual(drift, [], "public module constants changed:\n"
                         + "\n".join(drift))


class TestBlockWireSnapshot(unittest.TestCase):
    """The 16 shipped blocks: kwargs, schema and serialisation unchanged."""

    @classmethod
    def setUpClass(cls):
        cls.expected = _load(BLOCKS)
        cls.actual = build()["blocks"]

    def test_every_shipped_block_is_still_registered(self):
        for block_id in self.expected:
            self.assertIn(block_id, self.actual,
                          f"{block_id} is no longer registered — the block was "
                          f"renamed or its module stopped importing")

    def test_init_signature_is_the_preset_wire_format(self):
        drift = []
        for block_id, want in self.expected.items():
            have = self.actual.get(block_id)
            if have and have["init"] != want["init"]:
                drift.append(f"{block_id}.__init__:\n"
                             f"    was {want['init']}\n"
                             f"    now {have['init']}")
        self.assertEqual(drift, [], "block constructors changed — old presets "
                         "would stop loading:\n" + "\n".join(drift))

    def test_config_schema_is_unchanged_for_the_ui(self):
        """ui/js/stack-dnd.js renders these fields in this order."""
        drift = []
        for block_id, want in self.expected.items():
            have = self.actual.get(block_id)
            if not have:
                continue
            if have["schema_keys"] != want["schema_keys"]:
                drift.append(f"{block_id}: schema keys/order "
                             f"{want['schema_keys']} → {have['schema_keys']}")
            if have["schema"] != want["schema"]:
                drift.append(f"{block_id}: schema contents changed")
        self.assertEqual(drift, [], "\n".join(drift))

    def test_default_to_dict_is_unchanged(self):
        drift = []
        for block_id, want in self.expected.items():
            have = self.actual.get(block_id)
            if have and have["to_dict"] != want["to_dict"]:
                drift.append(f"{block_id}: {want['to_dict']} → {have['to_dict']}")
        self.assertEqual(drift, [], "block defaults changed (preset round-trip):\n"
                         + "\n".join(drift))


if __name__ == "__main__":
    unittest.main(verbosity=2)
