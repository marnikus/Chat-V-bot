"""Bridge API for the archive + collector, and the grid window set (M6).

Two things are proven here.

1. **Request/response over QWebChannel.** Reads hit an async database, so a
   `@Slot` cannot answer inline: JS passes a `req_id` and Python answers on
   a signal carrying the same id. Concurrent requests must never cross.

2. **The grid grew by three windows.** The window set is validated on both
   sides and a mismatching layout is REJECTED (RULE 13), so adding windows
   without a migration would silently destroy every saved arrangement.
   A stored v1 payload must therefore be UPGRADED, keeping the user's
   arrangement and appending the new windows.

Run with:  python3 tests/test_history_bridge.py
"""

import asyncio
import json
import os
import sys
import tempfile
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QObject  # noqa: E402

from backend.bridge import Bridge  # noqa: E402
from backend.config_manager import ConfigManager  # noqa: E402
from backend.history_service import HistoryService  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_chat_parser_delta import FakePage, raw  # noqa: E402

LEGACY_WINDOWS = ["stats", "filters", "stack", "config", "composer",
                  "people", "log"]
NEW_WINDOWS = ["history", "userdb", "collector"]
ALL_WINDOWS = LEGACY_WINDOWS + NEW_WINDOWS


def leaf(i):
    return {"t": "leaf", "id": i}


def split(d, kids, sizes):
    return {"t": "split", "dir": d, "children": kids, "sizes": sizes}


def legacy_payload(tree):
    return json.dumps({"v": 1, "tree": tree}, ensure_ascii=False)


def v1_custom_tree():
    """A recognisable custom v1 arrangement: one flat column of all 7."""
    return split("col", [leaf(i) for i in LEGACY_WINDOWS],
                 [16, 14, 14, 14, 14, 14, 14])


class ConnectedPage(FakePage):
    is_connected = True


async def wait_for(box, timeout=3.0):
    step, waited = 0.01, 0.0
    while not box and waited < timeout:
        await asyncio.sleep(step)
        waited += step
    return box


class BridgeCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.dir = tempfile.mkdtemp()
        self.cfg = ConfigManager(os.path.join(self.dir, "config.json"))
        self.page = ConnectedPage([raw(f"m{i}", idx=i) for i in range(8)])
        self.service = HistoryService(
            cdp=self.page, config=self.cfg,
            db_path=os.path.join(self.dir, "history.db"))
        await self.service.init()
        self.service.collector.configure(my_nick="Me")
        br = Bridge.__new__(Bridge)
        QObject.__init__(br)
        br._config = self.cfg
        br._engine = types.SimpleNamespace(load_stack=lambda blocks: None)
        br._memory = None
        br._presets = None
        br.attach_history(self.service)
        self.bridge = br
        self.errors = []
        br.history_error.connect(lambda scope, msg:
                                 self.errors.append((scope, msg)))

    async def asyncTearDown(self):
        await self.service.close()

    async def seed(self, nick="Nick", count=8):
        self.page.partner = nick
        self.page.messages = [raw(f"m{i}", from_nick=nick, idx=i)
                              for i in range(count)]
        await self.service.collector.tick()

    async def ask(self, slot, *args, signal=None):
        box = []
        signal.connect(lambda *a: box.append(a))
        slot(*args)
        await wait_for(box)
        self.assertTrue(box, "the bridge never answered")
        return box[-1]


class TestHistoryReads(BridgeCase):
    async def test_open_answers_on_the_request_id(self):
        await self.seed()
        req, payload = await self.ask(self.bridge.history_open, "r1", "Nick",
                                      "{}", signal=self.bridge.history_page_ready)
        self.assertEqual(req, "r1")
        data = json.loads(payload)
        self.assertEqual(data["nick"], "Nick")
        self.assertEqual(len(data["items"]), 8)
        self.assertEqual(data["items"][-1]["ord"], 8)
        self.assertIn("stats", data)

    async def test_paging_older_rows(self):
        await self.seed(count=30)
        _r, first = await self.ask(self.bridge.history_open, "r1", "Nick",
                                   json.dumps({"limit": 10}),
                                   signal=self.bridge.history_page_ready)
        oldest = json.loads(first)["items"][0]["ord"]
        _r2, older = await self.ask(
            self.bridge.history_page, "r2", "Nick",
            json.dumps({"before_ord": oldest, "limit": 10}),
            signal=self.bridge.history_page_ready)
        data = json.loads(older)
        self.assertEqual(data["items"][-1]["ord"], oldest - 1)
        self.assertTrue(data["has_more"])

    async def test_two_requests_do_not_cross(self):
        await self.seed()
        box = []
        self.bridge.history_page_ready.connect(lambda *a: box.append(a))
        self.bridge.history_open("A", "Nick", "{}")
        self.bridge.history_open("B", "Nick", "{}")
        while len(box) < 2:
            await asyncio.sleep(0.01)
        self.assertEqual({b[0] for b in box[:2]}, {"A", "B"})

    async def test_unknown_person_is_an_empty_page_not_an_error(self):
        _req, payload = await self.ask(self.bridge.history_open, "r", "Ghost",
                                       "{}", signal=self.bridge.history_page_ready)
        data = json.loads(payload)
        self.assertEqual(data["items"], [])
        self.assertTrue(data["missing"])
        self.assertEqual(self.errors, [])

    async def test_search_within_a_person_and_globally(self):
        await self.seed()
        _r, payload = await self.ask(
            self.bridge.history_search, "s1",
            json.dumps({"q": "m3", "scope": "person", "nick": "Nick"}),
            signal=self.bridge.history_search_ready)
        self.assertEqual(json.loads(payload)["total"], 1)
        _r, payload = await self.ask(
            self.bridge.history_search, "s2",
            json.dumps({"q": "m3", "scope": "global"}),
            signal=self.bridge.history_search_ready)
        self.assertEqual(json.loads(payload)["groups"][0]["nick"], "Nick")

    async def test_stats_expose_both_identities(self):
        await self.seed()
        _r, payload = await self.ask(self.bridge.history_stats, "st", "Nick",
                                     signal=self.bridge.history_stats_ready)
        data = json.loads(payload)
        self.assertEqual(data["nick"], "Nick")
        self.assertEqual(data["my_nicks"], ["Me"])


class TestUserDatabase(BridgeCase):
    async def test_page_and_stats(self):
        await self.seed("Nick", 4)
        await self.seed("Other", 2)
        _r, payload = await self.ask(self.bridge.userdb_page, "u1",
                                     json.dumps({"limit": 10}),
                                     signal=self.bridge.userdb_page_ready)
        data = json.loads(payload)
        self.assertEqual(data["total"], 2)
        self.assertEqual({p["nick"] for p in data["items"]}, {"Nick", "Other"})
        _r, payload = await self.ask(self.bridge.userdb_stats, "u2",
                                     signal=self.bridge.userdb_page_ready)
        self.assertEqual(json.loads(payload)["persons"], 2)

    async def test_nick_search(self):
        await self.seed("Ангелина", 2)
        await self.seed("Nick", 2)
        _r, payload = await self.ask(self.bridge.userdb_page, "u3",
                                     json.dumps({"q": "ангел"}),
                                     signal=self.bridge.userdb_page_ready)
        data = json.loads(payload)
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["items"][0]["nick"], "Ангелина")

    async def test_delete_and_restore_notify_the_ui(self):
        await self.seed("Nick", 3)
        box = []
        self.bridge.userdb_changed.connect(lambda p: box.append(json.loads(p)))
        self.assertTrue(self.bridge.history_delete_person("Nick", False))
        await wait_for(box)
        self.assertEqual(box[-1]["action"], "deleted")
        box.clear()
        self.assertTrue(self.bridge.history_restore_person("Nick"))
        await wait_for(box)
        self.assertEqual(box[-1]["action"], "restored")

    async def test_hard_delete_removes_the_messages(self):
        await self.seed("Nick", 3)
        self.bridge.history_delete_person("Nick", True)
        await asyncio.sleep(0.1)
        rows = await self.service.db.fetchall("SELECT COUNT(*) FROM messages")
        self.assertEqual(rows[0][0], 0)


class TestMediaAndClipboard(BridgeCase):
    async def test_media_path_answers_with_url_when_not_cached(self):
        self.page.messages = [raw("", kind="gif", idx=0,
                                  media={"url": "https://x/y.gif",
                                         "kind": "gif"})]
        await self.service.collector.tick()
        _r, payload = await self.ask(self.bridge.history_open, "r", "Nick",
                                     "{}", signal=self.bridge.history_page_ready)
        ref = json.loads(payload)["items"][0]["media"]["id"]
        _r, info = await self.ask(self.bridge.media_path, "m1", str(ref),
                                  signal=self.bridge.media_ready)
        data = json.loads(info)
        self.assertEqual(data["url"], "https://x/y.gif")

    def test_copy_text_never_needs_the_browser_clipboard(self):
        self.assertIsInstance(self.bridge.copy_text("hello"), bool)


class TestMyNickAndCollector(BridgeCase):
    async def test_my_nick_is_stored_and_broadcast(self):
        box = []
        self.bridge.my_nick_changed.connect(box.append)
        self.bridge.set_my_nick("  HiHoney  ")
        self.assertEqual(self.bridge.get_my_nick(), "HiHoney")
        self.assertEqual(box[-1], "HiHoney")
        reopened = ConfigManager(self.cfg._path)
        self.assertEqual(reopened.get("collector", "my_nick"), "HiHoney")
        self.assertIn("HiHoney", reopened.get_state("my_nick_recent", []))

    async def test_collector_settings_round_trip(self):
        self.bridge.collector_set(json.dumps({"heartbeat_ms": 2222,
                                              "require_two_participants": False}))
        state = json.loads(self.bridge.collector_state())
        self.assertEqual(state["settings"]["heartbeat_ms"], 2222)
        self.assertFalse(state["settings"]["require_two_participants"])
        reopened = ConfigManager(self.cfg._path)
        self.assertEqual(reopened.get("collector", "heartbeat_ms"), 2222)

    async def test_collector_status_reaches_the_ui(self):
        box = []
        self.bridge.collector_status.connect(lambda p: box.append(json.loads(p)))
        await self.service.collector.tick()
        self.assertTrue(box)
        self.assertIn("state", box[-1])

    async def test_commands_are_accepted(self):
        self.bridge.collector_command("pause")
        self.assertTrue(json.loads(self.bridge.collector_state())["paused"])
        self.bridge.collector_command("resume")
        self.assertFalse(json.loads(self.bridge.collector_state())["paused"])
        self.bridge.collector_command("nonsense")   # must not raise

    async def test_history_settings_round_trip(self):
        self.bridge.save_history_settings(json.dumps({
            "preview": {"preload_rows": 25, "show_images": False}}))
        got = json.loads(self.bridge.get_history_settings())
        self.assertEqual(got["preview"]["preload_rows"], 25)
        self.assertFalse(got["preview"]["show_images"])
        reopened = ConfigManager(self.cfg._path)
        self.assertEqual(reopened.get("history", "preview", "preload_rows"), 25)


class TestGridWindowSetV2(unittest.TestCase):
    def make_bridge(self):
        tmp = tempfile.mkdtemp()
        cfg = ConfigManager(os.path.join(tmp, "config.json"))
        br = Bridge.__new__(Bridge)
        QObject.__init__(br)
        br._config = cfg
        br._engine = types.SimpleNamespace(load_stack=lambda _b: None)
        return br, cfg

    def test_window_set_contains_the_three_new_windows(self):
        self.assertEqual(sorted(Bridge.WINDOW_IDS), sorted(ALL_WINDOWS))

    def test_default_tree_contains_every_window(self):
        tree = Bridge._default_grid_tree()
        self.assertEqual(sorted(Bridge._leaf_ids(tree)), sorted(ALL_WINDOWS))
        self.assertIsNone(Bridge._validate_grid_tree(tree))

    def test_v1_payload_is_upgraded_not_rejected(self):
        tree, err = Bridge._parse_grid_payload(legacy_payload(v1_custom_tree()))
        self.assertIsNone(err)
        self.assertEqual(sorted(Bridge._leaf_ids(tree)), sorted(ALL_WINDOWS))

    def test_upgrade_keeps_the_users_arrangement(self):
        tree, _err = Bridge._parse_grid_payload(legacy_payload(v1_custom_tree()))
        flat = json.dumps(tree)
        # the original flat column is still there, in order, before the new row
        order = [i for i in Bridge._leaf_ids(tree) if i in LEGACY_WINDOWS]
        self.assertEqual(order, LEGACY_WINDOWS)
        for new in NEW_WINDOWS:
            self.assertIn(new, flat)

    def test_saving_a_v1_layout_stores_v2(self):
        br, cfg = self.make_bridge()
        self.assertTrue(br.save_grid_layout(legacy_payload(v1_custom_tree())))
        stored = json.loads(cfg.get_state("grid_layout"))
        self.assertEqual(stored["v"], 2)
        self.assertEqual(sorted(Bridge._leaf_ids(stored["tree"])),
                         sorted(ALL_WINDOWS))

    def test_v2_payload_round_trips_unchanged(self):
        br, _cfg = self.make_bridge()
        canonical = json.dumps({"v": 2, "tree": Bridge._default_grid_tree()})
        self.assertTrue(br.save_grid_layout(canonical))
        got = json.loads(br.get_grid_layout())
        self.assertEqual(got["v"], 2)

    def test_unknown_version_is_still_rejected(self):
        _tree, err = Bridge._parse_grid_payload(
            json.dumps({"v": 9, "tree": Bridge._default_grid_tree()}))
        self.assertIn("version", err)

    def test_incomplete_v2_set_is_still_rejected(self):
        tree = split("row", [leaf("stats"), leaf("log")], [50, 50])
        _t, err = Bridge._parse_grid_payload(json.dumps({"v": 2, "tree": tree}))
        self.assertIn("window set", err)

    def test_a_rejected_payload_leaves_the_stored_one_intact(self):
        br, cfg = self.make_bridge()
        br.save_grid_layout(legacy_payload(v1_custom_tree()))
        good = cfg.get_state("grid_layout")
        self.assertFalse(br.save_grid_layout("{garbage"))
        self.assertEqual(cfg.get_state("grid_layout"), good)


if __name__ == "__main__":
    unittest.main(verbosity=2)
