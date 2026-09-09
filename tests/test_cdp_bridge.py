"""D8 — CdpBridge contract (design IDs C-1b..C-6b).

  C-1b get_tabs() → "pending" now, the list arrives on tabs_received
  C-2b connect_tab → service connect; the client's connected/disconnected
       signals become connection_status payloads ("connected"/"disconnected")
  C-3b find_tab_by_url → tab_match_result(query, matches); empty query
       safely answers "[]"
  C-4b bookmarks: add/remove/duplicate contract + persistence;
       ONE url_presets_updated per change (no self-echo)
  C-5b set_last_url_preset persists; empty is a no-op
  C-6b an explicit connect refreshes the people queue (PeopleChanged)

Run:  python -m pytest tests/test_cdp_bridge.py
"""

import asyncio
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import QObject, Signal  # noqa: E402

from backend.bridge import Bridge  # noqa: E402

from bridge_harness import Recorder, TempWorld, make_bare  # noqa: E402


class FakeCdpClient(QObject):
    """CDP client stand-in: Qt connection signals + async API."""
    connected = Signal()
    disconnected = Signal()
    error = Signal(str)

    def __init__(self, tabs=None):
        super().__init__()
        self.tabs = list(tabs or [])
        self.connected_to = None

    async def fetch_tabs(self):
        return list(self.tabs)

    async def connect(self, ws_url):
        self.connected_to = ws_url
        self.connected.emit()
        return True


class CdpCase(unittest.TestCase):
    def setUp(self):
        self.world = TempWorld()
        self.addCleanup(self.world.__exit__, None, None, None)
        self.client = FakeCdpClient()
        self.br = make_bare(cdp=self.client, config=self.world.config)
        self.tabs = Recorder(self.br.tabs_received)
        self.status = Recorder(self.br.connection_status)
        self.match = Recorder(self.br.tab_match_result)
        self.presets = Recorder(self.br.url_presets_updated)
        # build the bridge eagerly so the bus subscriptions exist
        from bridge.cdp_bridge import CdpBridge
        self.br._bridge(CdpBridge)
        # install_status_forwarding runs when the cdp_service is first
        # built — touch it now so the client signals are wired
        self.br._ctx.cdp_service

    # ── discovery ────────────────────────────────────────────────
    def test_C1b_get_tabs_answers_on_the_signal(self):
        self.client.tabs = [{"id": "t1", "title": "chat",
                             "url": "https://x", "ws_url": "ws://x"}]

        class Tab:
            def __init__(self, d):
                self.__dict__.update(d)

        self.client.tabs = [Tab({"id": "t1", "title": "chat",
                                 "url": "https://x", "ws_url": "ws://x"})]

        async def go():
            self.assertEqual(self.br.get_tabs(), "pending")
            await asyncio.sleep(0.08)
        asyncio.run(go())
        self.assertEqual(len(self.tabs.calls), 1)
        payload = json.loads(self.tabs.calls[0])
        self.assertEqual(payload[0]["id"], "t1")
        self.assertEqual(payload[0]["ws_url"], "ws://x")

    def test_C1b_no_client_is_safe(self):
        br2 = make_bare(cdp=None, config=self.world.config)
        self.assertEqual(br2.get_tabs(), "pending")   # no raise

    # ── connect / disconnect ─────────────────────────────────────
    def test_C2b_connect_reaches_the_client_and_announces(self):
        async def go():
            self.br.connect_tab("ws://localhost:9222/devtools/page/1")
            await asyncio.sleep(0.08)
        asyncio.run(go())
        self.assertEqual(self.client.connected_to,
                         "ws://localhost:9222/devtools/page/1")
        self.assertEqual(self.status.calls[-1], "connected")

    def test_C6b_disconnect_is_forwarded(self):
        self.client.disconnected.emit()
        self.assertEqual(self.status.calls[-1], "disconnected")
        self.client.error.emit("boom")
        self.assertEqual(self.status.calls[-1], "error")

    # ── url matching ─────────────────────────────────────────────
    def test_C3b_find_tab_by_url(self):
        async def go():
            self.br.find_tab_by_url("virt-chat")
            await asyncio.sleep(0.08)
        asyncio.run(go())
        self.assertEqual(len(self.match.calls), 1)
        query, matches = self.match.calls[0]
        self.assertEqual(query, "virt-chat")
        self.assertIsInstance(json.loads(matches), list)

    def test_C3b_empty_query_answers_empty(self):
        async def go():
            self.br.find_tab_by_url("   ")
            await asyncio.sleep(0.08)
        asyncio.run(go())
        # the echo carries the CLEANED query
        self.assertEqual(self.match.calls[-1], ("", "[]"))

    # ── bookmarks ────────────────────────────────────────────────
    def test_C4b_bookmarks_crud_and_persistence(self):
        base = json.loads(self.br.get_url_presets())   # factory defaults
        mine = "https://example.org/room"
        self.assertNotIn(mine, base)

        self.br.add_url_preset(f"  {mine}  ")
        listed = json.loads(self.br.get_url_presets())
        self.assertEqual(len(listed), len(base) + 1)
        self.assertIn(mine, listed,
                     "whitespace stripped, bookmark stored")

        # duplicate add: kept once, still announced
        before = len(self.presets.calls)
        self.br.add_url_preset(mine)
        self.assertEqual(json.loads(self.br.get_url_presets()), listed)
        self.assertEqual(len(self.presets.calls), before + 1)

        # empty add: no crash, no change, no announcement
        self.br.add_url_preset("   ")
        self.assertEqual(len(self.presets.calls), before + 1)
        self.assertEqual(json.loads(self.br.get_url_presets()), listed)

        # remove + remove-missing
        self.br.remove_url_preset(mine)
        self.assertEqual(json.loads(self.br.get_url_presets()), base)
        self.br.remove_url_preset("ghost")            # safe

        # persisted to disk
        from backend.config_manager import ConfigManager
        cfg2 = ConfigManager(self.world.config_path)
        self.assertEqual(cfg2.bookmarks.all(), base)

    def test_C4b_one_signal_per_change(self):
        self.presets.clear()
        self.br.add_url_preset("https://x.example")
        self.assertEqual(len(self.presets.calls), 1,
                         "url_presets_updated must fire ONCE per change "
                         "(no bus self-echo)")

    def test_C5b_last_url_preset_persists(self):
        self.br.set_last_url_preset("https://ru.virt-chat.com/chat")
        self.assertEqual(
            self.world.config.get_state("last_url_preset"),
            "https://ru.virt-chat.com/chat")
        self.br.set_last_url_preset("   ")            # no-op
        self.assertEqual(
            self.world.config.get_state("last_url_preset"),
            "https://ru.virt-chat.com/chat")


if __name__ == "__main__":
    unittest.main()
