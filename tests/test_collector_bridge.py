"""D10 — CollectorBridge contract (design IDs K-1..K-7).

  K-1  collector_state with no archive → the safe "off" payload
  K-2  collector_set MERGES (unspecified keys survive) + persists +
       announces collector_status; corrupt JSON is a no-op
  K-3  collector_command start/stop flips the collector state and
       announces; unknown commands announce NOTHING
  K-4  get/set_my_nick roundtrip + my_nick_changed + recent list +
       the collector's my_nick follows
  K-5  attach_archive wires the collector's Qt signals through

Run:  python -m pytest tests/test_collector_bridge.py
"""

import asyncio
import json
import os
import sys
import tempfile
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import QObject  # noqa: E402

from backend.bridge import Bridge  # noqa: E402
from backend.config_manager import ConfigManager  # noqa: E402
from backend.history_service import HistoryService  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_chat_parser_delta import FakePage, raw  # noqa: E402
from test_history_bridge import ConnectedPage  # noqa: E402

from bridge_harness import Recorder, TempWorld, make_bare  # noqa: E402


class CollectorCase(unittest.TestCase):
    def setUp(self):
        self.world = TempWorld()
        self.addCleanup(self.world.__exit__, None, None, None)
        self.br = make_bare(config=self.world.config)
        self.status = Recorder(self.br.collector_status)
        self.nick = Recorder(self.br.my_nick_changed)
        from bridge.collector_bridge import CollectorBridge
        self.br._bridge(CollectorBridge)

    # ── no archive yet ───────────────────────────────────────────
    def test_K1_off_payload_without_archive(self):
        payload = json.loads(self.br.collector_state())
        self.assertEqual(payload["state"], "off")
        self.assertEqual(payload["settings"], {})
        self.br.collector_set('{"my_nick": "x"}')      # safe no-op
        self.br.collector_command("start")             # safe no-op
        self.assertEqual(self.br.get_my_nick(), "")
        self.assertEqual(self.status.calls, [])

    # ── with the real archive service ────────────────────────────
    def _attach_archive(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(lambda: None)
        cfg = self.world.config
        cfg.set("history", "db_path",
                os.path.join(self.dir, "history.db"))
        page = ConnectedPage([raw(f"m{i}", idx=i) for i in range(2)])
        self.service = HistoryService(cdp=page, config=cfg,
                                      db_path=os.path.join(self.dir,
                                                           "history.db"))

        async def go():
            await self.service.init()
        asyncio.run(go())
        self.addCleanup(lambda: None)
        self.br.attach_history(self.service)
        return self.service

    def tearDown(self):
        service = getattr(self, "service", None)
        if service is not None:
            asyncio.run(service.close())

    def test_K2_state_and_settings_merge(self):
        service = self._attach_archive()
        payload = json.loads(self.br.collector_state())
        self.assertIn("state", payload)
        self.assertIn("settings", payload)

        # a baseline setting, then a second one: the first must survive
        async def go():
            self.br.collector_set(json.dumps({"heartbeat_ms": 1234}))
            await asyncio.sleep(0.02)
            self.assertEqual(len(self.status.calls), 1)
            self.br.collector_set(json.dumps({"my_nick": "Tester"}))
            await asyncio.sleep(0.02)
        asyncio.run(go())
        self.assertEqual(len(self.status.calls), 2)
        stored = self.world.config.get("collector", default={})
        self.assertEqual(stored.get("heartbeat_ms"), 1234,
                         "merge, not replace: earlier settings survive")
        self.assertEqual(stored.get("my_nick"), "Tester")
        # the merged settings are visible in the payload
        latest = json.loads(self.status.calls[-1])
        self.assertEqual(latest["settings"].get("heartbeat_ms"), 1234)

    def test_K2b_corrupt_settings_are_a_noop(self):
        self._attach_archive()
        before = json.loads(self.br.collector_state())
        for bad in ('{corrupt', '"a string"', '5'):
            self.br.collector_set(bad)
        after = json.loads(self.br.collector_state())
        self.assertEqual(before["settings"], after["settings"])
        self.assertEqual(len(self.status.calls), 0,
                         "rejected settings announce nothing")

    def test_K3_commands_flip_the_state(self):
        service = self._attach_archive()
        col = service.collector
        async def go():
            self.status.clear()
            self.br.collector_command("start")
            await asyncio.sleep(0.05)
            self.assertTrue(col.running)
            started = len(self.status.calls)
            self.assertGreaterEqual(started, 1, "start announces the state")
            self.status.clear()
            self.br.collector_command("stop")
            await asyncio.sleep(0.05)
            self.assertFalse(col.running)
            stopped = len(self.status.calls)
            self.assertGreaterEqual(stopped, 1, "stop announces the state")
            # a command never announces MORE than its own echo + one
            # genuine async state broadcast from the collector loop
            self.assertLessEqual(max(started, stopped), 2)

        self.status.clear()
        self.br.collector_command("make_me_a_sandwich")
        self.br.collector_command("")
        self.assertEqual(self.status.calls, [],
                         "unknown commands announce nothing")

    def test_K3b_pause_resume(self):
        service = self._attach_archive()
        col = service.collector
        async def go():
            self.br.collector_command("pause")
            await asyncio.sleep(0.02)
            self.assertTrue(col.paused)
            self.br.collector_command("resume")
            await asyncio.sleep(0.02)
            self.assertFalse(col.paused)
        asyncio.run(go())

    # ── My Nick ──────────────────────────────────────────────────
    def test_K4_my_nick_roundtrip_and_follows_the_collector(self):
        service = self._attach_archive()
        async def go():
            self.br.set_my_nick("  Misty  ")
            await asyncio.sleep(0.02)
        asyncio.run(go())
        self.assertEqual(self.br.get_my_nick(), "Misty")
        self.assertEqual(self.nick.calls, ["Misty"])
        self.assertEqual(service.collector.my_nick, "Misty",
                         "the live collector follows the header nick")
        stored = self.world.config.get("collector", "my_nick", default="")
        self.assertEqual(stored, "Misty")
        recent = self.world.config.get_state("my_nick_recent", [])
        self.assertEqual(recent, ["Misty"])
        # cleared nick: empty string, still announced
        self.br.set_my_nick("")
        self.assertEqual(self.nick.calls, ["Misty", ""])

    def test_K5_archive_signals_are_wired_through(self):
        service = self._attach_archive()
        log_rec = Recorder(self.br.collector_log)
        appended = Recorder(self.br.history_appended)
        col = service.collector
        col.collector_log.emit('{"level": "info"}')
        col.history_appended.emit('{"nick": "A", "items": [], "added": 0}')
        self.assertEqual(log_rec.calls, ['{"level": "info"}'])
        self.assertEqual(appended.calls,
                         ['{"nick": "A", "items": [], "added": 0}'])


if __name__ == "__main__":
    unittest.main()
