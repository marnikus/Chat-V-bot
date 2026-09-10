"""services/preset_io — the portable export file format (v1).

Design: docs/STACK_PRESET_EXPORT_IMPORT_DESIGN_2026-09-10.md §3, §7.

Pins the whole validation table: every reject reason returns a distinct
``Err`` code; every compatibility problem becomes a warning (unknown
block type, missing selector, version mismatch, malformed library
entry); the file round-trips with all parameters intact; a failed
write never touches the previous good file.

Run:  python3 tests/unit/services/test_preset_io.py  (or pytest)
"""

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from services.preset_io import (ACTION_BLOCK_FORMAT, FORMAT_VERSION,  # noqa: E402
                                STACK_PRESET_FORMAT, build_block_export,
                                build_stack_export, export_text,
                                parse_export, preview_dict,
                                read_export_file, write_export)

BLOCK_A = {"block_id": "PAUSE", "pre_delay_ms": 250, "enabled": True}
BLOCK_B = {"block_id": "CUSTOM_FIND", "custom_name": "open menu",
           "selector": "#menu", "label_selector": ".t",
           "match_text": "{{nick}}", "click_enabled": True,
           "click_selector": "", "highlight_enabled": True,
           "confirm_pause_ms": 700, "highlight_ms": 1200,
           "pre_delay_ms": 500, "enabled": True}
LIBRARY = [{"name": "open menu", "block": BLOCK_B, "updated_at": "t0"}]


def _stack_file(**over):
    data = {"format": STACK_PRESET_FORMAT, "format_version": FORMAT_VERSION,
            "app_version": "9.9.9", "exported_at": "2026-09-10T00:00:00",
            "name": "My Campaign", "stack": [dict(BLOCK_A), dict(BLOCK_B)],
            "custom_blocks": [dict(e) for e in LIBRARY]}
    data.update(over)
    return json.dumps(data, ensure_ascii=False)


def _block_file(**over):
    data = {"format": ACTION_BLOCK_FORMAT, "format_version": FORMAT_VERSION,
            "app_version": "9.9.9", "exported_at": "2026-09-10T00:00:00",
            "name": "open menu", "block": dict(BLOCK_B)}
    data.update(over)
    return json.dumps(data, ensure_ascii=False)


class TestBuilders(unittest.TestCase):

    def test_stack_export_shape_and_parameters(self):
        payload = build_stack_export("My Campaign",
                                     [dict(BLOCK_A), dict(BLOCK_B)], LIBRARY)
        self.assertEqual(payload["format"], STACK_PRESET_FORMAT)
        self.assertEqual(payload["format_version"], FORMAT_VERSION)
        self.assertTrue(payload["app_version"])
        self.assertIn("exported_at", payload)
        self.assertEqual(payload["name"], "My Campaign")
        # every parameter of every block survives (RULE 3 round trip)
        self.assertEqual(payload["stack"], [dict(BLOCK_A), dict(BLOCK_B)])
        self.assertEqual(payload["custom_blocks"], LIBRARY)

    def test_stack_export_requires_a_name(self):
        with self.assertRaises(ValueError):
            build_stack_export("  ", [BLOCK_A], [])

    def test_stack_export_filters_non_dict_entries(self):
        payload = build_stack_export("p", [BLOCK_A, "junk", None],
                                     [LIBRARY[0], 42])
        self.assertEqual(payload["stack"], [dict(BLOCK_A)])
        self.assertEqual(payload["custom_blocks"], [dict(LIBRARY[0])])

    def test_block_export_shape(self):
        payload = build_block_export("open menu", dict(BLOCK_B))
        self.assertEqual(payload["format"], ACTION_BLOCK_FORMAT)
        self.assertEqual(payload["block"], BLOCK_B)
        self.assertEqual(payload["name"], "open menu")

    def test_block_export_requires_name_and_dict(self):
        with self.assertRaises(ValueError):
            build_block_export("", BLOCK_B)
        with self.assertRaises(ValueError):
            build_block_export("x", "not a dict")


class TestFileIO(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def path(self, name="p.json"):
        return os.path.join(self.dir, name)

    def test_round_trip_stack(self):
        payload = build_stack_export("My Campaign",
                                     [dict(BLOCK_A), dict(BLOCK_B)], LIBRARY)
        path = self.path()
        self.assertTrue(write_export(path, payload).is_ok)
        self.assertTrue(read_export_file(path).is_ok)
        parsed = parse_export(read_export_file(path).unwrap())
        self.assertFalse(parsed.is_err)
        preview = parsed.unwrap()
        self.assertEqual(preview.kind, "stack")
        self.assertEqual(preview.name, "My Campaign")
        self.assertEqual(list(preview.stack), [dict(BLOCK_A),
                                               dict(BLOCK_B)])
        self.assertEqual(list(preview.custom_blocks), LIBRARY)
        self.assertEqual(preview.warnings, ())
        self.assertIsNone(preview.block)

    def test_round_trip_block(self):
        payload = build_block_export("open menu", dict(BLOCK_B))
        path = self.path()
        write_export(path, payload)
        preview = parse_export(read_export_file(path).unwrap()).unwrap()
        self.assertEqual(preview.kind, "block")
        self.assertEqual(preview.block, BLOCK_B)
        self.assertEqual(preview.stack, ())
        self.assertEqual(preview.custom_blocks, ())
        self.assertEqual(preview.warnings, ())

    def test_export_text_is_human_readable(self):
        # indent 2, trailing newline, and non-ascii names survive as-is
        # (ensure_ascii off — selectors/nicks stay readable in the file)
        text = export_text(build_block_export("привет", BLOCK_A))
        self.assertIn('\n  "format"', text)
        self.assertTrue(text.endswith("\n"))
        self.assertIn("привет", text)
        self.assertNotIn("\\u043f", text)

    def test_failed_write_leaves_previous_file_intact(self):
        path = self.path()
        good = build_block_export("a", BLOCK_A)
        self.assertTrue(write_export(path, good).is_ok)
        before = open(path, encoding="utf-8").read()
        # the parent path is an existing FILE: the write must fail, and
        # the good file must survive untouched
        blocked = os.path.join(path, "sub.json")
        result = write_export(blocked, good)
        self.assertTrue(result.is_err)
        self.assertEqual(result.err().code, "write_failed")
        self.assertEqual(open(path, encoding="utf-8").read(), before)
        self.assertFalse(os.path.exists(blocked))

    def test_write_to_directory_target_fails_and_cleans_tmp(self):
        target = self.path("adir")
        os.makedirs(target)
        result = write_export(target, build_block_export("a", BLOCK_A))
        self.assertTrue(result.is_err)
        self.assertEqual(result.err().code, "write_failed")
        self.assertTrue(os.path.isdir(target), "the dir survives")
        self.assertFalse(os.path.exists(target + ".tmp"),
                         "the tmp file is cleaned up")

    def test_unserialisable_payload_is_a_write_error_not_a_raise(self):
        result = write_export(self.path(), {"x": object()})
        self.assertTrue(result.is_err)
        self.assertEqual(result.err().code, "write_failed")

    def test_read_missing_file_is_typed_error(self):
        result = read_export_file(self.path("nope.json"))
        self.assertTrue(result.is_err)
        self.assertEqual(result.err().code, "read_failed")

    def test_preview_dict_is_json_serialisable(self):
        import core.version
        text = _stack_file(app_version=core.version.APP_VERSION)
        preview = parse_export(text).unwrap()
        data = json.loads(json.dumps(preview_dict(preview),
                                     ensure_ascii=False))
        self.assertEqual(data["kind"], "stack")
        self.assertEqual(data["name"], "My Campaign")
        self.assertEqual(len(data["stack"]), 2)
        self.assertEqual(data["warnings"], [])


class TestParseRejections(unittest.TestCase):
    """Every hard failure: a distinct, stable Err code (design §3.3)."""

    def code(self, text):
        result = parse_export(text)
        self.assertTrue(result.is_err, f"expected a rejection for {text!r}")
        return result.err().code

    def test_not_json(self):
        self.assertEqual(self.code("{nope"), "not_json")
        self.assertEqual(self.code(None), "not_json")

    def test_bad_shape(self):
        self.assertEqual(self.code("[1, 2]"), "bad_shape")
        self.assertEqual(self.code('"just a string"'), "bad_shape")

    def test_unknown_format(self):
        self.assertEqual(self.code('{"format": "other/format"}'),
                         "unknown_format")
        self.assertEqual(self.code("{}"), "unknown_format")

    def test_no_name(self):
        self.assertEqual(self.code(_stack_file(name="   ")), "no_name")
        self.assertEqual(self.code(_block_file(name=42)), "no_name")

    def test_bad_stack_shape(self):
        self.assertEqual(self.code(_stack_file(stack="nope")), "bad_stack")
        self.assertEqual(
            self.code(_stack_file(stack=[dict(BLOCK_A), "junk"])),
            "bad_stack")

    def test_bad_block_shape(self):
        self.assertEqual(self.code(_block_file(block="nope")), "bad_block")

    def test_bad_version(self):
        self.assertEqual(self.code(_stack_file(format_version="1")),
                         "bad_version")
        self.assertEqual(self.code(_stack_file(format_version=0)),
                         "bad_version")
        self.assertEqual(self.code(_stack_file(format_version=True)),
                         "bad_version")

    def test_unsupported_newer_version(self):
        result = parse_export(_stack_file(format_version=99))
        self.assertTrue(result.is_err)
        self.assertEqual(result.err().code, "unsupported_version")
        self.assertIn("99", result.err().detail)

    def test_newer_version_rejected_for_block_files_too(self):
        self.assertEqual(self.code(_block_file(format_version=2)),
                         "unsupported_version")


class TestParseWarnings(unittest.TestCase):
    """Soft problems: accepted with human-readable warnings."""

    def preview(self, text):
        result = parse_export(text)
        self.assertFalse(result.is_err,
                         f"expected acceptance, got {result.err()}")
        return result.unwrap()

    def test_app_version_mismatch_warns(self):
        preview = self.preview(_stack_file())   # app_version "9.9.9"
        self.assertTrue(any("9.9.9" in w for w in preview.warnings))

    def test_same_app_version_does_not_warn(self):
        import core.version
        text = _stack_file(app_version=core.version.APP_VERSION)
        self.assertEqual(self.preview(text).warnings, ())

    def test_older_format_version_warns(self):
        # v1 has no older version yet: simulate by claiming the app reads
        # v2, then a v1 file must be accepted WITH a warning.
        import services.preset_io as io_mod
        with mock.patch.object(io_mod, "FORMAT_VERSION", 2):
            preview = self.preview(_stack_file())
        self.assertTrue(any("v1 < v2" in w for w in preview.warnings))
        self.assertEqual(preview.format_version, 1)

    def test_unknown_block_id_warns_and_is_not_dropped(self):
        stack = [dict(BLOCK_A), {"block_id": "NOT_A_BLOCK", "enabled": True}]
        preview = self.preview(_stack_file(stack=stack))
        self.assertTrue(any("NOT_A_BLOCK" in w for w in preview.warnings))
        # RULE 4: the import itself must not silently drop the block —
        # it stays in the preview/stack and the engine decides at run.
        self.assertEqual(len(preview.stack), 2)

    def test_missing_block_id_warns(self):
        preview = self.preview(_stack_file(stack=[dict(BLOCK_A), {}]))
        self.assertTrue(any("block #2" in w for w in preview.warnings))

    def test_custom_find_without_selector_warns(self):
        bad = dict(BLOCK_B)
        bad["selector"] = ""
        preview = self.preview(_stack_file(stack=[dict(BLOCK_A), bad]))
        self.assertTrue(any("selector" in w for w in preview.warnings))
        self.assertTrue(any("open menu" in w for w in preview.warnings))

    def test_custom_find_with_selector_is_clean(self):
        import core.version
        text = _stack_file(app_version=core.version.APP_VERSION)
        self.assertEqual(self.preview(text).warnings, ())

    def test_builtins_without_selector_do_not_warn(self):
        # CLICK_USER & co. have defaults baked into the block; an empty
        # selector there is legitimate, not a lost selector.
        import core.version
        stack = [{"block_id": "CLICK_USER", "enabled": True}]
        text = _stack_file(stack=stack, app_version=core.version.APP_VERSION)
        self.assertEqual(self.preview(text).warnings, ())

    def test_malformed_library_entries_are_skipped_with_warning(self):
        import core.version
        # entry one: not a dict / no dict block; entry two: dict block but
        # an unusable name; entry three: good
        raw = [{"block": "junk"},
               {"name": "  ", "block": dict(BLOCK_A)},
               dict(LIBRARY[0])]
        text = _stack_file(custom_blocks=raw,
                           app_version=core.version.APP_VERSION)
        preview = self.preview(text)
        self.assertEqual(len(preview.custom_blocks), 1)
        self.assertEqual(preview.custom_blocks[0]["name"], "open menu")
        self.assertEqual(len(preview.warnings), 2)
        self.assertTrue(any("no name" in w for w in preview.warnings))

    def test_non_list_library_is_skipped_with_warning(self):
        preview = self.preview(_stack_file(custom_blocks="nope"))
        self.assertEqual(preview.custom_blocks, ())
        self.assertTrue(any("library" in w for w in preview.warnings))

    def test_absent_library_key_is_fine(self):
        # hand-made files may omit custom_blocks entirely
        import core.version
        data = json.loads(_stack_file())
        del data["custom_blocks"]
        data["app_version"] = core.version.APP_VERSION
        preview = self.preview(json.dumps(data))
        self.assertEqual(preview.custom_blocks, ())
        self.assertEqual(preview.warnings, ())

    def test_block_file_unknown_type_warns(self):
        preview = self.preview(_block_file(block={"block_id": "GHOST"}))
        self.assertTrue(any("GHOST" in w for w in preview.warnings))

    def test_block_file_missing_selector_warns(self):
        bad = dict(BLOCK_B)
        bad["selector"] = "  "
        preview = self.preview(_block_file(block=bad))
        self.assertTrue(any("selector" in w for w in preview.warnings))

    def test_block_file_without_block_id_warns(self):
        preview = self.preview(_block_file(block={"selector": "#x"}))
        self.assertTrue(any("block_id" in w for w in preview.warnings))


class TestPreviewKinds(unittest.TestCase):

    def test_stack_preview_has_empty_block_and_vice_versa(self):
        stack = parse_export(_stack_file()).unwrap()
        block = parse_export(_block_file()).unwrap()
        self.assertIsNone(stack.block)
        self.assertEqual(stack.custom_blocks, (
            {"name": "open menu", "block": BLOCK_B, "updated_at": "t0"},))
        self.assertEqual(block.stack, ())
        self.assertEqual(block.custom_blocks, ())
        self.assertEqual(block.block, BLOCK_B)


if __name__ == "__main__":
    unittest.main(verbosity=2)
