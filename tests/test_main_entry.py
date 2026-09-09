"""Smoke tests for main.py — start, DI registry, DB init, close/exit.

The stale ``main.MainWindow`` / ``main.build_container`` / ``main._queue_path``
contracts moved to ``app.window`` and ``app.bootstrap`` and are now covered by
``tests/unit/app/``.  This file keeps the entry-point smoke tests that still
belong to ``main``.

Qt is still required for the ``main()`` smoke path (QApplication + the web
view), but the stubs are installed only for the duration of each test and are
always restored, so no other test module sees a fake ``PySide6``.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tests.unit.app.qt_stubs import QApplication, load_main  # noqa: E402

SHIPPED_BLOCKS = [
    "ATTACH_IMAGE", "CLICK_BACK", "CLICK_MAIN_TAB", "CLICK_SEND",
    "CLICK_USER", "COLLECT_HISTORY", "CONDITIONAL_SKIP", "CUSTOM_FIND",
    "MARK_MESSAGED", "PAUSE", "REPEAT_LOOP", "SCROLL_PARSE",
    "SEARCH_USERS", "TAKE_PERSON", "TYPE_MESSAGE", "WAIT_PAGE_LOAD",
]


class TestRegistryScanOnEnginePath(unittest.TestCase):
    def test_shipped_blocks_registered_after_actions_import(self):
        import actions  # noqa: F401
        from actions.registry import ActionRegistry

        ids = ActionRegistry.all_ids()
        missing = [b for b in SHIPPED_BLOCKS if b not in ids]
        self.assertEqual(missing, [], f"scan missed {missing}")

    def test_main_does_not_leave_registry_empty_if_engine_imported(self):
        load_main()
        from actions.registry import ActionRegistry

        self.assertGreaterEqual(len(ActionRegistry.all_ids()),
                                len(SHIPPED_BLOCKS))


class TestMainSmokeStartExit(unittest.TestCase):
    def setUp(self):
        self.main = load_main()
        self._cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)
        QApplication.quit_on_last = True

    def tearDown(self):
        os.chdir(self._cwd)
        self._tmp.cleanup()

    def test_main_disables_quit_on_last_window_and_returns_0(self):
        with mock.patch.object(self.main.asyncio, "set_event_loop"):
            rc = self.main.main()
        self.assertEqual(rc, 0)
        self.assertIs(False, QApplication.quit_on_last)
        self.assertTrue(QApplication.instances)

    def test_ui_index_html_exists_for_loader(self):
        ui = Path(ROOT) / "ui" / "index.html"
        self.assertTrue(ui.is_file(), f"missing {ui}")

    def test_main_does_not_call_sys_exit(self):
        src = Path(ROOT, "main.py").read_text(encoding="utf-8")
        body = src.split('if __name__')[0]
        self.assertNotIn("sys.exit", body)


class TestDbInitContract(unittest.TestCase):
    def test_user_memory_init_creates_users_table(self):
        from stores.user_memory import UserMemory

        async def run():
            with tempfile.TemporaryDirectory() as d:
                path = os.path.join(d, "q.db")
                memory = UserMemory(path)
                await memory.init()
                self.assertTrue(memory.is_open)
                await memory.close()
                self.assertFalse(memory.is_open)

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main(verbosity=2)
