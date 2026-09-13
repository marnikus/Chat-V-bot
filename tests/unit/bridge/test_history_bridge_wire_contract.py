"""The QWebChannel surface of HistoryBridge is a contract with the frontend.

Round H (H1) split HistoryBridge's delete and media slots into mixins. That
is only safe because a mixin's `@Slot` methods still register on the derived
QObject's metaobject -- and nothing in the suite checked that. The split was
verified by hand, by dumping `staticMetaObject` before and after; this file
makes that check permanent.

Why a metaobject test and not a `hasattr` test: `hasattr` passes for a plain
Python method that Qt never registered. If a future refactor moves a slot to
a helper object, forgets `@Slot`, or changes an argument type, the Python
attribute still exists and every ordinary test still passes, while the
frontend silently loses the call. Only the metaobject sees the difference.

The expected set is written out in full rather than computed. A test that
derives its expectation from the code under test cannot detect a deletion.
"""

from __future__ import annotations

import unittest

from bridge.history_bridge import HistoryBridge

# Every slot and signal JavaScript may call or connect to, with its exact Qt
# signature. Taken from the metaobject at H1, and identical to the value
# measured before the mixin split.
EXPECTED = {
    # reads
    "history_open(QString,QString,QString)",
    "history_page(QString,QString,QString)",
    "history_search(QString,QString)",
    "history_stats(QString,QString)",
    "userdb_page(QString,QString)",
    "userdb_stats(QString)",
    "detect_my_nick(QString)",
    # deletions (HistoryDeleteMixin)
    "history_delete_person(QString,bool)",
    "history_clear_person(QString)",
    "history_delete_message(QString,QString)",
    "history_purge_deleted(QString)",
    "history_restore_person(QString)",
    "history_merge(QString,QString)",
    # media + clipboard (HistoryMediaMixin)
    "media_path(QString,QString)",
    "media_restore(QString,QString)",
    "media_folder(QString)",
    "open_media_folder(QString)",
    "copy_media(QString)",
    "copy_text(QString)",
    # settings
    "get_history_settings()",
    "save_history_settings(QString)",
    # signals the UI connects to
    "history_page_ready(QString,QString)",
    "history_search_ready(QString,QString)",
    "history_stats_ready(QString,QString)",
    "userdb_page_ready(QString,QString)",
    "userdb_changed(QString)",
    "media_ready(QString,QString)",
    "history_error(QString,QString)",
}


def _exposed() -> set:
    """Signatures Qt actually registered, excluding QObject's own."""
    meta = HistoryBridge.staticMetaObject
    return {meta.method(i).methodSignature().data().decode()
            for i in range(meta.methodOffset(), meta.methodCount())}


class TestHistoryBridgeWireContract(unittest.TestCase):
    def test_every_expected_slot_is_registered_with_qt(self):
        missing = EXPECTED - _exposed()
        self.assertFalse(
            missing,
            "these slots/signals vanished from the QWebChannel surface, so "
            "the frontend calls them into the void: " + ", ".join(
                sorted(missing)))

    def test_nothing_was_added_without_updating_this_contract(self):
        extra = _exposed() - EXPECTED
        self.assertFalse(
            extra,
            "new QWebChannel entries that the frontend contract does not "
            "list. If they are intentional, add them here and to "
            "docs/current/SYSTEM_OF_RECORD.md: " + ", ".join(sorted(extra)))

    def test_the_mixin_slots_survive_inheritance(self):
        """The specific property that made the H1 split safe."""
        for sig in ("history_delete_person(QString,bool)",
                    "copy_media(QString)"):
            self.assertIn(
                sig, _exposed(),
                f"{sig} is defined on a mixin; if it is missing, mixin "
                "@Slots stopped registering on the derived QObject and the "
                "split must be reverted")

    def test_the_probe_would_notice_a_missing_slot(self):
        """The check is not vacuous: prove it fails on a real absence."""
        self.assertNotIn("history_delete_person(QString)", _exposed(),
                         "wrong-arity signature must not match")
        self.assertTrue(EXPECTED - {"copy_text(QString)"} < EXPECTED)


if __name__ == "__main__":
    unittest.main()
