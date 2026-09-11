"""bridge/file_bridge — FileBridge slots over real stores.

Design: docs/STACK_PRESET_EXPORT_IMPORT_DESIGN_2026-09-10.md §4.2, §7.

The REAL ``FileBridge`` QObject runs against REAL ``PresetStore`` /
``BlockStore`` files (temp paths) with fake engine/undo and monkeypatched
file dialogs: exports write files that round-trip through
``services.preset_io.parse_export``; imports validate before touching
anything; replace/merge behave per spec; forged previews are rejected.

Run:  python -m pytest tests/unit/bridge/test_file_bridge.py
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from bridge.context import BridgeContext            # noqa: E402
import bridge.file_bridge as fb_mod                 # noqa: E402
from bridge.file_bridge import FileBridge           # noqa: E402
from core.events import EventBus                    # noqa: E402
from services.preset_io import (build_block_export,  # noqa: E402
                                build_stack_export,
                                parse_export, write_export)
from stores.block_store import BlockStore           # noqa: E402
from stores.preset_store import PresetStore         # noqa: E402


class FakeEngine:
    def __init__(self):
        self.stack = []

    def load_stack(self, blocks):
        self.stack = list(blocks)

    def get_stack(self):
        return [dict(b) for b in self.stack]


class FakeUndo:
    def __init__(self):
        self.pushed = []

    def push_stack(self, blocks):
        self.pushed.append(list(blocks))
        return (self.pushed, len(self.pushed) - 1)

    def attach(self, **_refs):      # ctx._crosswire calls this on build
        return None


class FileBridgeCase(unittest.TestCase):
    block_a = {"block_id": "PAUSE", "pre_delay_ms": 250, "enabled": True}
    block_b = {"block_id": "CUSTOM_FIND", "custom_name": "open menu",
               "selector": "#menu", "enabled": True}

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.engine = FakeEngine()
        self.undo = FakeUndo()
        self.blocks = BlockStore(path=os.path.join(self.dir, "blocks.json"))
        self.presets = PresetStore(path=os.path.join(self.dir,
                                                     "presets.json"))

        class FakeConfig:
            pass

        self.config = FakeConfig()
        self.config.blocks = self.blocks
        self.config._state = {}
        self.config.get_state = \
            lambda k, d=None: self.config._state.get(k, d)
        def _set_state(save=True, **kw):
            self.config._state.update(kw)
        self.config.set_state = _set_state
        self.config.save = lambda: None

        self.ctx = BridgeContext(engine=self.engine, config=self.config,
                                 presets=self.presets, bus=EventBus())
        self.ctx._undo_svc = self.undo
        self.bridge = FileBridge(self.ctx)
        # monkeypatch the native dialogs
        self.save_target = os.path.join(self.dir, "export.json")
        self.open_target = ""
        self._orig = (fb_mod.pick_save_path, fb_mod.pick_open_path)
        fb_mod.pick_save_path = lambda cap, name: self.save_target
        fb_mod.pick_open_path = lambda cap: self.open_target

    def tearDown(self):
        fb_mod.pick_save_path, fb_mod.pick_open_path = self._orig
        PresetStore._by_path.pop(os.path.abspath(self.presets.path), None)

    # ── helpers ──────────────────────────────────────────────────
    def seed_library(self):
        self.blocks.save_custom_block("open menu", dict(self.block_b))

    def seed_preset(self, name="My Campaign"):
        self.presets.save_stack(name, [dict(self.block_a)])
        self.presets.save(force=True)

    def write_file(self, payload, name="file.json"):
        path = os.path.join(self.dir, name)
        write_export(path, payload)
        return path

    def stack_file(self):
        return self.write_file(
            build_stack_export("Imported",
                               [dict(self.block_a), dict(self.block_b)],
                               self.blocks.all()), "stack.json")

    def block_file(self):
        return self.write_file(
            build_block_export("open menu", dict(self.block_b)),
            "block.json")

    def result(self, raw):
        return json.loads(raw)

    # ── export ───────────────────────────────────────────────────
    def test_export_stack_writes_round_trippable_file(self):
        self.seed_library()
        out = self.result(self.bridge.export_stack(
            json.dumps([dict(self.block_a), dict(self.block_b)])))
        self.assertTrue(out["ok"])
        self.assertEqual(out["path"], self.save_target)
        text = open(self.save_target, encoding="utf-8").read()
        preview = parse_export(text).unwrap()
        self.assertEqual(preview.kind, "stack")
        self.assertEqual([b["block_id"] for b in preview.stack],
                         ["PAUSE", "CUSTOM_FIND"])
        self.assertEqual(preview.custom_blocks[0]["name"], "open menu")
        # all parameters survive
        self.assertEqual(preview.stack[1]["selector"], "#menu")

    def test_export_stack_preset_uses_preset_blocks(self):
        self.seed_preset()
        self.seed_library()
        out = self.result(self.bridge.export_stack_preset("My Campaign"))
        self.assertTrue(out["ok"])
        preview = parse_export(
            open(self.save_target, encoding="utf-8").read()).unwrap()
        self.assertEqual(preview.name, "My Campaign")
        self.assertEqual([b["block_id"] for b in preview.stack], ["PAUSE"])

    def test_export_stack_preset_missing(self):
        out = self.result(self.bridge.export_stack_preset("ghost"))
        self.assertFalse(out["ok"])
        self.assertIn("not found", out["error"])
        self.assertFalse(os.path.exists(self.save_target))

    def test_export_custom_block(self):
        self.seed_library()
        out = self.result(self.bridge.export_custom_block("open menu"))
        self.assertTrue(out["ok"])
        preview = parse_export(
            open(self.save_target, encoding="utf-8").read()).unwrap()
        self.assertEqual(preview.kind, "block")
        self.assertEqual(preview.name, "open menu")
        self.assertEqual(preview.block, self.block_b)

    def test_export_custom_block_missing(self):
        out = self.result(self.bridge.export_custom_block("ghost"))
        self.assertFalse(out["ok"])
        self.assertIn("not found", out["error"])

    def test_export_empty_stack_refused(self):
        out = self.result(self.bridge.export_stack("[]"))
        self.assertFalse(out["ok"])
        self.assertFalse(os.path.exists(self.save_target))

    def test_export_cancelled_writes_nothing(self):
        self.save_target = ""
        out = self.result(self.bridge.export_stack(
            json.dumps([dict(self.block_a)])))
        self.assertFalse(out["ok"])
        self.assertTrue(out["canceled"])

    # ── import: preview only, nothing applied ───────────────────
    def test_import_stack_returns_preview(self):
        self.open_target = self.stack_file()
        out = self.result(self.bridge.import_file("stack"))
        self.assertTrue(out["ok"])
        self.assertEqual(out["kind"], "stack")
        self.assertEqual(out["name"], "Imported")
        self.assertEqual(len(out["stack"]), 2)
        self.assertIn("text", out)
        self.assertEqual(self.engine.stack, [], "preview must not apply")

    def test_import_unknown_block_type_warns_in_preview(self):
        bad = {"block_id": "GHOST_BLOCK", "enabled": True}
        path = self.write_file(
            build_stack_export("bad", [dict(self.block_a), bad], []),
            "bad.json")
        self.open_target = path
        out = self.result(self.bridge.import_file("stack"))
        self.assertTrue(out["ok"])
        self.assertTrue(any("GHOST_BLOCK" in w for w in out["warnings"]))

    def test_import_invalid_json_is_rejected(self):
        path = os.path.join(self.dir, "bad.json")
        open(path, "w", encoding="utf-8").write("{nope")
        self.open_target = path
        out = self.result(self.bridge.import_file("stack"))
        self.assertFalse(out["ok"])
        self.assertIn("not valid JSON", out["error"])

    def test_import_kind_mismatch_is_rejected(self):
        self.open_target = self.block_file()
        out = self.result(self.bridge.import_file("stack"))
        self.assertFalse(out["ok"])
        self.assertIn("not a stack preset", out["error"])

    def test_import_missing_file_is_rejected(self):
        self.open_target = os.path.join(self.dir, "missing.json")
        out = self.result(self.bridge.import_file("stack"))
        self.assertFalse(out["ok"])
        self.assertIn("could not read", out["error"])

    def test_import_cancelled(self):
        self.open_target = ""
        out = self.result(self.bridge.import_file("stack"))
        self.assertFalse(out["ok"])
        self.assertTrue(out["canceled"])

    def test_import_bad_kind_argument(self):
        out = self.result(self.bridge.import_file("virus"))
        self.assertFalse(out["ok"])

    # ── failure branches: disk errors, bad payloads, no config ────
    def test_export_disk_failure_is_reported_not_raised(self):
        ro_dir = os.path.join(self.dir, "ro")
        os.makedirs(ro_dir)
        os.chmod(ro_dir, 0o555)
        try:
            self.save_target = os.path.join(ro_dir, "x.json")
            out = self.result(self.bridge.export_stack(
                json.dumps([dict(self.block_a)])))
            self.assertFalse(out["ok"])
            self.assertTrue(out["error"].startswith("export failed"))
        finally:
            os.chmod(ro_dir, 0o755)

    def test_revalidate_rejects_non_json_preview(self):
        out = self.result(self.bridge.apply_imported(
            "not json at all", "replace", "[]"))
        self.assertFalse(out["ok"])
        self.assertIn("not JSON", out["error"])

    def test_merge_tolerates_unreadable_current_stack(self):
        self.open_target = self.stack_file()
        preview = json.loads(self.bridge.import_file("stack"))
        # a broken current-stack payload degrades to "empty current",
        # it does not abort the import
        out = self.result(self.bridge.apply_imported(
            json.dumps(preview), "merge", "not json"))
        self.assertTrue(out["ok"])
        self.assertEqual(out["stack"], list(preview["stack"]))

    def test_merge_library_reports_store_failure_in_the_log(self):
        from core.events import LogMessage
        logs = []
        self.ctx.bus.subscribe(LogMessage,
                               lambda e: logs.append(e.message))
        self.seed_library()     # the file carries one block to merge
        ro_dir = os.path.join(self.dir, "ro")
        os.makedirs(ro_dir)
        ro_store = BlockStore(path=os.path.join(ro_dir, "blocks.json"))
        ro_store.save_custom_block("seed", dict(self.block_a))
        self.config.blocks = ro_store
        os.chmod(ro_dir, 0o555)
        try:
            self.open_target = self.stack_file()
            preview = json.loads(self.bridge.import_file("stack"))
            out = self.result(self.bridge.apply_imported(
                json.dumps(preview), "replace", "[]"))
            self.assertTrue(out["ok"], "the stack import still succeeds")
            self.assertEqual(out["blocks_added"], 0)
            self.assertEqual(out["blocks_replaced"], 0)
            self.assertTrue(any("not saved" in m for m in logs))
        finally:
            os.chmod(ro_dir, 0o755)

    def test_apply_block_without_a_library_is_a_clear_error(self):
        self.open_target = self.block_file()
        preview = json.loads(self.bridge.import_file("block"))
        self.ctx.config = None     # a context without the config store
        out = self.result(self.bridge.apply_imported(
            json.dumps(preview), "add", "[]"))
        self.assertFalse(out["ok"])
        self.assertIn("no block library", out["error"])

    def test_export_custom_block_with_non_dict_block_refused(self):
        self.blocks.set_all([{"name": "broken", "block": "junk",
                              "updated_at": ""}])
        out = self.result(self.bridge.export_custom_block("broken"))
        self.assertFalse(out["ok"])
        self.assertIn("block object", out["error"])

    def test_apply_block_with_a_failing_store_is_a_clear_error(self):
        ro_dir = os.path.join(self.dir, "ro")
        os.makedirs(ro_dir)
        ro_store = BlockStore(path=os.path.join(ro_dir, "blocks.json"))
        self.config.blocks = ro_store
        self.open_target = self.block_file()
        preview = json.loads(self.bridge.import_file("block"))
        os.chmod(ro_dir, 0o555)
        try:
            out = self.result(self.bridge.apply_imported(
                json.dumps(preview), "add", "[]"))
            self.assertFalse(out["ok"])
            self.assertIn("rejected the import", out["error"])
        finally:
            os.chmod(ro_dir, 0o755)

    def test_apply_degrades_gracefully_without_engine_and_config(self):
        # a bare context (no engine, no config) must still import —
        # the stack is returned, the missing services are just skipped
        bare = BridgeContext(bus=EventBus())
        bare._undo_svc = self.undo
        bridge = FileBridge(bare)
        self.open_target = self.stack_file()
        preview = json.loads(self.bridge.import_file("stack"))
        out = self.result(bridge.apply_imported(
            json.dumps(preview), "replace", "[]"))
        self.assertTrue(out["ok"])
        self.assertEqual(len(out["stack"]), 2)

    # ── import: apply ───────────────────────────────────────────
    def _preview(self, path):
        return json.loads(self.bridge.import_file("stack"))

    def test_apply_replace_swaps_stack_and_merges_library(self):
        self.seed_library()
        self.open_target = self.stack_file()
        preview = self._preview(self.open_target)
        current = [dict(self.block_a)]
        out = self.result(self.bridge.apply_imported(
            json.dumps(preview), "replace", json.dumps(current)))
        self.assertTrue(out["ok"])
        self.assertEqual([b["block_id"] for b in out["stack"]],
                         ["PAUSE", "CUSTOM_FIND"])
        self.assertEqual([b["block_id"] for b in self.engine.stack],
                         ["PAUSE", "CUSTOM_FIND"])
        # undo sees the pre-import stack (RULE 12)
        self.assertEqual(self.undo.pushed, [current])
        # library: the file's "open menu" overwrote the same-named one
        self.assertEqual(out["blocks_added"], 0)
        self.assertEqual(out["blocks_replaced"], 1)
        self.assertEqual(len(self.blocks.all()), 1)
        self.assertEqual(self.config._state["last_stack_preset"], "")

    def test_apply_merge_appends_to_current_stack(self):
        self.open_target = self.stack_file()
        preview = self._preview(self.open_target)
        current = [dict(self.block_a)]
        out = self.result(self.bridge.apply_imported(
            json.dumps(preview), "merge", json.dumps(current)))
        self.assertTrue(out["ok"])
        self.assertEqual([b["block_id"] for b in out["stack"]],
                         ["PAUSE", "PAUSE", "CUSTOM_FIND"])
        self.assertEqual([b["block_id"] for b in self.engine.stack],
                         ["PAUSE", "PAUSE", "CUSTOM_FIND"])
        self.assertEqual(self.undo.pushed, [current])

    def test_apply_merge_adds_new_blocks_to_library(self):
        path = self.write_file(
            build_stack_export("lib", [dict(self.block_a)],
                               [{"name": "fresh", "block": dict(self.block_b),
                                 "updated_at": "t"}]), "lib.json")
        self.open_target = path
        preview = json.loads(self.bridge.import_file("stack"))
        out = self.result(self.bridge.apply_imported(
            json.dumps(preview), "merge", "[]"))
        self.assertTrue(out["ok"])
        self.assertEqual(out["blocks_added"], 1)
        self.assertEqual(out["blocks_replaced"], 0)
        self.assertEqual([b["name"] for b in self.blocks.all()], ["fresh"])

    def test_apply_rejects_bad_mode(self):
        self.open_target = self.stack_file()
        preview = self._preview(self.open_target)
        out = self.result(self.bridge.apply_imported(
            json.dumps(preview), "explode", "[]"))
        self.assertFalse(out["ok"])
        self.assertEqual(self.engine.stack, [])

    def test_apply_rejects_forged_preview(self):
        self.open_target = self.stack_file()
        preview = self._preview(self.open_target)
        preview["text"] = json.dumps(
            {"format": "chat-v-bot/stack-preset", "format_version": 99,
             "name": "x", "stack": []})
        out = self.result(self.bridge.apply_imported(
            json.dumps(preview), "replace", "[]"))
        self.assertFalse(out["ok"])
        self.assertIn("re-validation failed", out["error"])

    def test_apply_rejects_preview_without_text(self):
        self.open_target = self.stack_file()
        preview = self._preview(self.open_target)
        del preview["text"]
        out = self.result(self.bridge.apply_imported(
            json.dumps(preview), "replace", "[]"))
        self.assertFalse(out["ok"])
        self.assertIn("missing the file text", out["error"])

    def test_apply_unknown_type_kept_in_stack_for_the_engine(self):
        # RULE 4: the bridge does NOT silently drop the unknown block —
        # the user was warned in the preview; the engine decides at run.
        bad = {"block_id": "GHOST_BLOCK", "enabled": True}
        path = self.write_file(
            build_stack_export("bad", [dict(self.block_a), bad], []),
            "bad.json")
        self.open_target = path
        preview = json.loads(self.bridge.import_file("stack"))
        out = self.result(self.bridge.apply_imported(
            json.dumps(preview), "replace", "[]"))
        self.assertTrue(out["ok"])
        self.assertEqual([b["block_id"] for b in self.engine.stack],
                         ["PAUSE", "GHOST_BLOCK"])

    # ── import: single block ─────────────────────────────────────
    def test_import_block_preview(self):
        self.open_target = self.block_file()
        out = self.result(self.bridge.import_file("block"))
        self.assertTrue(out["ok"])
        self.assertEqual(out["kind"], "block")
        self.assertEqual(out["block"], self.block_b)

    def test_apply_block_add_grows_library(self):
        self.open_target = self.block_file()
        preview = json.loads(self.bridge.import_file("block"))
        out = self.result(self.bridge.apply_imported(
            json.dumps(preview), "add", "[]"))
        self.assertTrue(out["ok"])
        self.assertEqual(out["name"], "open menu")
        self.assertEqual([b["name"] for b in self.blocks.all()],
                         ["open menu"])

    def test_apply_block_wrong_mode_refused(self):
        self.open_target = self.block_file()
        preview = json.loads(self.bridge.import_file("block"))
        out = self.result(self.bridge.apply_imported(
            json.dumps(preview), "replace", "[]"))
        self.assertFalse(out["ok"])
        self.assertEqual(self.blocks.all(), [])

    def test_apply_stack_mode_to_block_file_refused(self):
        self.open_target = self.block_file()
        preview = json.loads(self.bridge.import_file("block"))
        out = self.result(self.bridge.apply_imported(
            json.dumps(preview), "merge", "[]"))
        self.assertFalse(out["ok"])

    # ── import also registers the file as a saved preset (BUG) ───
    def test_apply_replace_registers_the_preset_in_the_select_list(self):
        from core.events import PresetsChanged
        events = []
        self.ctx.bus.subscribe(PresetsChanged, lambda e: events.append(e))
        self.open_target = self.stack_file()
        preview = json.loads(self.bridge.import_file("stack"))
        out = self.result(self.bridge.apply_imported(
            json.dumps(preview), "replace", "[]"))
        self.assertTrue(out["ok"])
        self.assertEqual(out["preset_saved"], "Imported")
        # the Select Preset list now offers it, with the file's stack
        self.assertEqual(self.presets.load_stack("Imported"),
                         [dict(self.block_a), dict(self.block_b)])
        self.assertIn("stacks", [e.kind for e in events])
        names = [p["name"] for p in self.presets.list_stacks()]
        self.assertIn("Imported", names)

    def test_apply_merge_saves_the_file_stack_not_the_merged_stack(self):
        self.open_target = self.stack_file()
        preview = json.loads(self.bridge.import_file("stack"))
        current = [dict(self.block_a)]
        out = self.result(self.bridge.apply_imported(
            json.dumps(preview), "merge", json.dumps(current)))
        self.assertTrue(out["ok"])
        self.assertEqual(out["preset_saved"], "Imported")
        # list entry = the file's content; working stack = the merge
        self.assertEqual(self.presets.load_stack("Imported"),
                         [dict(self.block_a), dict(self.block_b)])
        self.assertEqual([b["block_id"] for b in out["stack"]],
                         ["PAUSE", "PAUSE", "CUSTOM_FIND"])

    def test_reimport_overwrites_the_older_copy_of_the_same_preset(self):
        self.open_target = self.stack_file()
        preview = json.loads(self.bridge.import_file("stack"))
        self.bridge.apply_imported(json.dumps(preview), "replace", "[]")
        # second import of the same-named file: still one preset
        self.open_target = self.stack_file()
        preview = json.loads(self.bridge.import_file("stack"))
        self.bridge.apply_imported(json.dumps(preview), "replace", "[]")
        self.assertEqual(
            [p["name"] for p in self.presets.list_stacks()], ["Imported"])

    def test_apply_without_a_preset_store_still_applies(self):
        self.open_target = self.stack_file()
        preview = json.loads(self.bridge.import_file("stack"))
        self.ctx.presets = None
        out = self.result(self.bridge.apply_imported(
            json.dumps(preview), "replace", "[]"))
        self.assertTrue(out["ok"])
        self.assertFalse(out["preset_saved"])


class TestRouterWiring(unittest.TestCase):
    """FileBridge is one of the domain bridges the Router publishes."""

    def test_file_bridge_slots_reach_the_wire(self):
        from bridge.router import BRIDGE_CLASSES, BRIDGE_SPECS
        from bridge.file_bridge import FileBridge
        self.assertIn(FileBridge, BRIDGE_CLASSES)
        slot_names = [name for name, _types, _ret
                      in BRIDGE_SPECS["FileBridge"][1]]
        for expected in ("export_stack", "export_stack_preset",
                         "export_custom_block", "import_file",
                         "apply_imported"):
            self.assertIn(expected, slot_names)
        signal_names = [name for name, _types
                        in BRIDGE_SPECS["FileBridge"][0]]
        self.assertIn("export_done", signal_names)
        self.assertIn("import_preview", signal_names)


if __name__ == "__main__":
    unittest.main(verbosity=2)
