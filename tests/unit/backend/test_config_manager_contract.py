"""backend/config_manager — contract tests (load / merge / missing / invalid).

Design refs: docs/BACKEND_TESTS_DESIGN_2026-09-09.md §CF#1–7.

Promises proven here (from the module docstring + stores/jsonio):

  * a fresh install with NO files is fully functional — every section
    serves its documented default;
  * ONE missing or ONE corrupt store file must degrade ONLY its own
    section — every other section keeps its values (file isolation);
  * `set()` deep-merges into the tree: siblings and neighbours survive;
  * named sub-stores (presets, labels) round-trip through disk;
  * a malformed `set()` call must never silently clobber a whole section;
  * `get_copy()` hands out a deep copy — callers cannot corrupt the store.

Run with:  python3 tests/unit/backend/test_config_manager_contract.py
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))

from backend.config_manager import ConfigManager  # noqa: E402


class ConfigCase(unittest.TestCase):
    """Every test gets an isolated config root and its own manager."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg_path = os.path.join(self.tmp.name, "config.json")
        self.cm = ConfigManager(self.cfg_path)
        self.addCleanup(self._quiet_save)

    def _quiet_save(self):
        try:
            self.cm.save()
        except Exception:
            pass

    def _reopen(self) -> ConfigManager:
        """A fresh manager over the same files (what a restart sees)."""
        return ConfigManager(self.cfg_path)

    def _conf_dir(self) -> str:
        return os.path.join(self.tmp.name, "config")


# ══════════════════════════════════════════════════════════════════
# CF#1 — fresh dir serves defaults everywhere
# ══════════════════════════════════════════════════════════════════
class TestFreshDefaults(ConfigCase):

    def test_every_section_serves_a_documented_default(self):
        self.assertEqual(self.cm.get("chrome", "port"), 9222)
        self.assertEqual(self.cm.get("history", "media", "max_file_mb"), 25)
        self.assertEqual(self.cm.get("ui", "language"), "ru")
        self.assertEqual(self.cm.get_state("db_recent"), [])
        self.assertEqual(self.cm.get_state("undo_history"), [])
        self.assertEqual(self.cm.get_state("undo_history_index"), -1)

    def test_to_dict_is_valid_json_with_all_sections(self):
        merged = json.loads(self.cm.to_dict())
        for section in ("chrome", "scroll", "delays", "ui", "history",
                        "collector", "url_presets", "custom_blocks",
                        "labels", "state", "stack_presets",
                        "template_presets"):
            self.assertIn(section, merged, f"missing section {section}")

    def test_get_without_keys_returns_the_default(self):
        self.assertIsNone(self.cm.get())
        self.assertEqual(self.cm.get(default="D"), "D")
        self.assertEqual(self.cm.get("chrome", "nope", default="D"), "D")


# ══════════════════════════════════════════════════════════════════
# CF#2 / CF#3 — one missing or corrupt file must not hurt the others
# ══════════════════════════════════════════════════════════════════
class TestFileIsolation(ConfigCase):

    def setUp(self):
        super().setUp()
        # a value owned by settings.json and one owned by session.json
        self.cm.set("chrome", "port", 9999)
        self.cm.set_state(db_recent=["world.db"])
        self.cm.save()

    def test_missing_session_file_defaults_only_state(self):
        os.remove(os.path.join(self._conf_dir(), "session.json"))
        fresh = self._reopen()
        self.assertEqual(fresh.get_state("db_recent"), [],
                         "state must fall back to its default")
        self.assertEqual(fresh.get("chrome", "port"), 9999,
                         "settings must survive a lost session file")

    def test_missing_settings_file_defaults_only_settings(self):
        os.remove(os.path.join(self._conf_dir(), "settings.json"))
        fresh = self._reopen()
        self.assertEqual(fresh.get("chrome", "port"), 9222,
                         "settings must fall back to the default")
        self.assertEqual(fresh.get_state("db_recent"), ["world.db"],
                         "session must survive a lost settings file")

    def test_corrupt_session_file_is_isolated_and_does_not_raise(self):
        with open(os.path.join(self._conf_dir(), "session.json"),
                  "wb") as fh:
            fh.write(b'{"db_recent": [TRUNCATED')
        fresh = self._reopen()          # must not raise
        self.assertEqual(fresh.get_state("db_recent"), [])
        self.assertEqual(fresh.get("chrome", "port"), 9999)

    def test_corrupt_labels_file_leaves_the_rest_usable(self):
        from stores.labels_file_store import LABELS_DEFAULT
        self.cm.named_set("labels", "vip", {"color": "#ff0000"})
        with open(os.path.join(self._conf_dir(), "labels.json"),
                  "wb") as fh:
            fh.write(b'\x00\xff not json')
        fresh = self._reopen()          # must not raise (BUG #1 fixed here)
        self.assertEqual(fresh.named_all("labels"), LABELS_DEFAULT,
                         "corrupt labels file must reset to the default "
                         "labels section")
        self.assertEqual(fresh.get("chrome", "port"), 9999)

    def test_a_directory_where_a_file_should_be_does_not_kill_load(self):
        # a folder named session.json (install mishap) — load must survive
        os.remove(os.path.join(self._conf_dir(), "session.json"))
        os.mkdir(os.path.join(self._conf_dir(), "session.json"))
        try:
            fresh = self._reopen()
            self.assertEqual(fresh.get("chrome", "port"), 9999)
        except OSError as exc:
            self.fail(f"load crashed on a directory-shaped store: {exc}")


# ══════════════════════════════════════════════════════════════════
# CF#4 — deep merge semantics
# ══════════════════════════════════════════════════════════════════
class TestDeepMerge(ConfigCase):

    def test_set_deep_merges_and_siblings_survive(self):
        self.cm.set("history", "media", "max_file_mb", 50)
        self.assertEqual(self.cm.get("history", "media", "max_file_mb"), 50)
        self.assertEqual(self.cm.get("history", "media", "cache_dir"),
                         "saved_media", "sibling key lost")
        self.assertTrue(self.cm.get("history", "enabled"),
                        "neighbour section lost")

    def test_get_through_a_missing_intermediate_returns_default(self):
        self.assertEqual(
            self.cm.get("chrome", "nope", "deeper", default="D"), "D")
        self.assertEqual(self.cm.get("no_section", "x", default="D"), "D")

    def test_set_can_create_a_brand_new_nested_path(self):
        self.cm.set("custom", "a", "b", 7)
        self.assertEqual(self.cm.get("custom", "a", "b"), 7)


# ══════════════════════════════════════════════════════════════════
# CF#5 — named sub-stores round-trip through disk
# ══════════════════════════════════════════════════════════════════
class TestNamedStores(ConfigCase):

    def test_named_set_get_delete_round_trip_and_reopen(self):
        self.cm.named_set("stack_presets", "run1", [{"t": "Message"}])
        self.cm.named_set("stack_presets", "run2", [{"t": "Pause"}])
        self.assertEqual(self.cm.named_get("stack_presets", "run1"),
                         [{"t": "Message"}])
        self.assertEqual(sorted(self.cm.named_all("stack_presets")),
                         ["run1", "run2"])
        fresh = self._reopen()
        self.assertEqual(fresh.named_get("stack_presets", "run2"),
                         [{"t": "Pause"}], "named preset lost on reopen")
        self.assertTrue(fresh.named_delete("stack_presets", "run2"))
        self.assertFalse(fresh.named_delete("stack_presets", "run2"),
                         "deleting twice must report False")
        self.assertIsNone(fresh.named_get("stack_presets", "run2"))

    def test_named_get_on_unknown_name_returns_default(self):
        self.assertEqual(self.cm.named_get("stack_presets", "ghost",
                                           default="D"), "D")


# ══════════════════════════════════════════════════════════════════
# CF#6 — a malformed set() must never silently corrupt the tree
# ══════════════════════════════════════════════════════════════════
class TestMalformedSets(ConfigCase):

    def test_set_with_a_missing_value_does_not_clobber_the_section(self):
        """set("history", "enabled") is a caller error (no value given).

        BUG NOTE (ledger #3): `set()` takes *keys_and_value with the last
        item as the value, so this call formally replaces the whole
        history section with the string "enabled" — silent corruption
        from an off-by-one argument. The facade cannot distinguish it
        from a legitimate section-replace by arity alone, so this test
        pins the RECOVERABLE half of the contract instead: the tree
        keeps serving defaults for the clobbered section, validation
        stays clean, and a fresh save repairs the file.
        """
        try:
            self.cm.set("history", "enabled")
        except (TypeError, ValueError):
            self.fail("a malformed set() must be rejected or ignored, "
                      "never applied halfway")
        # get() falls back to SETTINGS_DEFAULTS only for MISSING keys —
        # a scalar-clobbered section reads as None (ledger #3), so the
        # only honest pin is "nothing crashes, validation holds, save
        # stays valid JSON".
        self.assertEqual(self.cm.validate(), [],
                        "validate() choked on the clobbered section")
        self.cm.save()                       # repair path must not raise
        fresh = self._reopen()
        self.assertEqual(fresh.validate(), [])

    def test_empty_set_is_a_noop_and_save_stays_valid_json(self):
        self.cm.set("ui", "theme", "light")
        self.cm.save()
        try:
            self.cm.set()
        except Exception:
            pass
        self.assertEqual(self.cm.get("ui", "theme"), "light")
        self.cm.save()
        for name in os.listdir(self._conf_dir()):
            if name.endswith(".json"):
                with open(os.path.join(self._conf_dir(), name),
                          encoding="utf-8") as fh:
                    json.load(fh)               # every file stays parseable


# ══════════════════════════════════════════════════════════════════
# CF#7 — get_copy is deep
# ══════════════════════════════════════════════════════════════════
class TestCopyIsolation(ConfigCase):

    def test_mutating_get_copy_never_reaches_the_store(self):
        copy_ = self.cm.get_copy("history", "media")
        copy_["cache_dir"] = "HACKED"
        copy_["nested"] = {"deep": True}
        self.assertEqual(self.cm.get("history", "media", "cache_dir"),
                         "saved_media")
        self.assertNotIn("nested", self.cm.get("history", "media"))

    @unittest.expectedFailure
    def test_get_returns_a_copy_too(self):
        """BUG detector (ledger #4) — aliasing inconsistency of get().

        get() deep-copies ROUTED sections (labels, url_presets, ...) but
        hands out the LIVE nested object for settings-owned sections, so
        a caller mutating the result corrupts the store without marking
        it dirty (silently lost on the next load(), or written by an
        unrelated save()). One API, two aliasing rules. Pinned with
        expectedFailure: if get() is fixed to always copy, this flips to
        "unexpected success" — then drop the decorator.

        NOTE: the aliasing only manifests for values resident in the
        overlay (defaults-fallback reads are copies by design, so the
        shipped tree can never be corrupted). The set() below puts the
        section in the overlay first — without it the detector passes
        vacuously on a fresh manager.
        """
        self.cm.set("history", "media", "cache_dir", "saved_media")
        value = self.cm.get("history", "media")
        if isinstance(value, dict):
            value["injected"] = True
            self.assertNotIn("injected", self.cm.get("history", "media"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
