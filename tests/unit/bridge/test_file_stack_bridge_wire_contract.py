"""The QWebChannel surfaces of FileBridge and StackBridge are contracts.

Round I (I3) extracts a `PresetApplier` collaborator out of
`bridge/file_bridge.py`. That is only safe if every `@Slot` the frontend calls
still registers on the derived QObject with the SAME Qt signature — and before
this file, only `HistoryBridge` had that protection (see
`test_history_bridge_wire_contract.py`, added by H1). The guard must exist
BEFORE the refactor, or "the tests still pass" proves nothing about the wire.

Why a metaobject test and not `hasattr`: `hasattr` passes for a plain Python
method that Qt never registered. Move a slot onto a helper object, forget
`@Slot`, or widen an argument type, and the Python attribute still exists,
every ordinary test still passes, and the frontend silently calls into the
void. Only the metaobject sees the difference.

StackBridge is here as well as FileBridge because I3 touches the preset path
that both of them sit on, and because it is the larger surface of the two: 29
entries that nothing was checking.

The expected sets are written out in full rather than computed. A test that
derives its expectation from the code under test cannot detect a deletion.
"""

from __future__ import annotations

import unittest

from bridge.file_bridge import FileBridge
from bridge.stack_bridge import StackBridge

# Measured from the metaobject at I3, before the PresetApplier extraction.
FILE_EXPECTED = {
    # slots the frontend calls
    "export_custom_block(QString)",
    "export_stack(QString)",
    "export_stack_preset(QString)",
    "import_file(QString)",
    "import_preview(QString)",
    "apply_imported(QString,QString,QString)",
    # signal the UI connects to
    "export_done(QString)",
}

STACK_EXPECTED = {
    # stack state
    "get_stack_json()",
    "snapshot_stack(QString)",
    "run_stack(QString)",
    "pause_stack()",
    "resume_stack()",
    "stop_stack()",
    # message + criteria
    "get_message()",
    "save_message(QString)",
    "get_criteria()",
    "save_criteria(QString)",
    # stack presets
    "list_stack_presets()",
    "load_stack_preset(QString)",
    "save_stack_preset(QString,QString)",
    "delete_stack_preset(QString)",
    # template presets
    "list_template_presets()",
    "load_template_preset(QString)",
    "save_template_preset(QString,QString)",
    "delete_template_preset(QString)",
    # custom blocks
    "list_custom_blocks()",
    "save_custom_block(QString,QString)",
    "delete_custom_block(QString)",
    # signals the UI connects to
    "custom_blocks_updated(QString)",
    "preset_list_updated(QString)",
    "template_list_updated(QString)",
    "template_loaded(QString,QString)",
    "stack_loaded(QString,QString)",
    "stack_complete()",
    "step_complete(QString,QString)",
    "step_started(int,QString,QString)",
}


def _exposed(cls) -> set:
    """Signatures Qt actually registered on `cls`, excluding QObject's own."""
    meta = cls.staticMetaObject
    return {meta.method(i).methodSignature().data().decode()
            for i in range(meta.methodOffset(), meta.methodCount())}


class _WireContractMixin:
    bridge_cls: type
    expected: set

    def test_every_expected_slot_is_registered_with_qt(self):
        missing = self.expected - _exposed(self.bridge_cls)
        self.assertFalse(
            missing,
            f"these {self.bridge_cls.__name__} slots/signals vanished from "
            "the QWebChannel surface, so the frontend calls them into the "
            "void: " + ", ".join(sorted(missing)))

    def test_nothing_was_added_without_updating_this_contract(self):
        extra = _exposed(self.bridge_cls) - self.expected
        self.assertFalse(
            extra,
            f"new {self.bridge_cls.__name__} QWebChannel entries that the "
            "frontend contract does not list. If they are intentional, add "
            "them here and to docs/current/SYSTEM_OF_RECORD.md: "
            + ", ".join(sorted(extra)))

    def test_the_probe_reads_a_non_empty_surface(self):
        """A guard over an empty set would pass against a deleted class."""
        self.assertGreaterEqual(len(_exposed(self.bridge_cls)), 7)


class TestFileBridgeWireContract(_WireContractMixin, unittest.TestCase):
    bridge_cls = FileBridge
    expected = FILE_EXPECTED

    def test_arity_and_type_changes_are_caught(self):
        """Not vacuous: a near-miss signature must NOT satisfy the contract."""
        exposed = _exposed(FileBridge)
        self.assertIn("apply_imported(QString,QString,QString)", exposed)
        for near_miss in ("apply_imported(QString,QString)",
                          "apply_imported(QString,QString,QString,QString)",
                          "apply_imported(QString,QString,bool)"):
            self.assertNotIn(
                near_miss, exposed,
                "a wrong-arity or wrong-type signature must not match, or "
                "this guard cannot see a changed slot")


class TestStackBridgeWireContract(_WireContractMixin, unittest.TestCase):
    bridge_cls = StackBridge
    expected = STACK_EXPECTED

    def test_arity_and_type_changes_are_caught(self):
        exposed = _exposed(StackBridge)
        self.assertIn("save_stack_preset(QString,QString)", exposed)
        for near_miss in ("save_stack_preset(QString)",
                          "save_stack_preset(QString,QString,QString)"):
            self.assertNotIn(near_miss, exposed)


if __name__ == "__main__":
    unittest.main()
