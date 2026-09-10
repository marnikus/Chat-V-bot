"""app.bootstrap — composition-root and queue-path contract.

Moved here from the stale ``main.*`` section of ``tests/test_main_entry.py``:
``build_container`` and ``_queue_path`` are now ``app.bootstrap.create_container``
and ``app.bootstrap.queue_path``.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.bootstrap import create_container, queue_path  # noqa: E402

REQUIRED_CONTAINER_KEYS = (
    "config", "bus", "cdp", "memory", "criteria", "engine", "history", "bridge",
)


class TestQueuePath(unittest.TestCase):
    def setUp(self):
        self._cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)
        if os.path.exists("chatbot.db"):
            os.remove("chatbot.db")

    def tearDown(self):
        os.chdir(self._cwd)
        self._tmp.cleanup()

    @staticmethod
    def _cfg(db_path="history.db"):
        class Cfg:
            def get(self, section, key, default=None):
                if section == "history" and key == "db_path":
                    return db_path
                return default

        return Cfg()

    def test_legacy_chatbot_db_wins_when_file_exists(self):
        Path("chatbot.db").write_bytes(b"x")
        self.assertEqual(queue_path(self._cfg("/abs/world.db")), "chatbot.db")

    def test_world_path_when_no_legacy_file(self):
        self.assertFalse(os.path.exists("chatbot.db"))
        self.assertEqual(queue_path(self._cfg("/abs/world.db")), "/abs/world.db")

    def test_default_world_name_when_config_omits_path(self):
        class Empty:
            def get(self, section, key, default=None):
                return default

        self.assertEqual(queue_path(Empty()), "history.db")

    def test_legacy_check_is_not_absolute_install_root(self):
        # A leftover chatbot.db next to the repo root must not steal the queue
        # when CWD is a temporary directory.
        self.assertEqual(queue_path(self._cfg("world-in-tmp.db")),
                         "world-in-tmp.db")


class TestBuildContainer(unittest.TestCase):
    def test_registers_all_composition_root_keys_lazily(self):
        container = create_container()
        for key in REQUIRED_CONTAINER_KEYS:
            self.assertTrue(container.has(key), f"missing {key}")
        for key in REQUIRED_CONTAINER_KEYS:
            self.assertNotIn(key, container._instances)

    def test_config_get_does_not_build_engine_or_history(self):
        container = create_container()
        self.assertIsNotNone(container.get("config"))
        self.assertNotIn("engine", container._instances)
        self.assertNotIn("history", container._instances)
        self.assertNotIn("bridge", container._instances)

    def test_cdp_reads_chrome_host_port_from_config(self):
        container = create_container()

        class FakeCfg:
            def get(self, section, key, default=None):
                if section == "chrome" and key == "host":
                    return "10.0.0.9"
                if section == "chrome" and key == "port":
                    return 9333
                if section == "history" and key == "db_path":
                    return "history.db"
                return default

        container.register_value("config", FakeCfg())
        cdp = container.get("cdp")
        self.assertEqual(getattr(cdp, "host", None) or getattr(cdp, "_host", None),
                         "10.0.0.9")
        port = getattr(cdp, "port", None)
        if port is None:
            port = getattr(cdp, "_port", None)
        self.assertEqual(int(port), 9333)

    def test_no_dependency_cycle_among_registered_keys(self):
        container = create_container()
        container.get("config")
        container.get("bus")
        container.get("criteria")


if __name__ == "__main__":
    unittest.main(verbosity=2)
