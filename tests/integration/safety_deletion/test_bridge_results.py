"""DbBridge result handling: payloads, log levels, refresh, no delete undo."""

import asyncio
import json
import os
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
if os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))) not in sys.path:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))))

from core.events import DbChanged, EventBus, LogMessage  # noqa: E402


def make_ctx(manager_result, *, world_changed=None):
    """Minimal ctx for DbBridge._db_action without Qt app."""
    bus = EventBus()
    box = {"db": [], "log": []}
    bus.subscribe(DbChanged, lambda e: box["db"].append(json.loads(e.payload)))
    bus.subscribe(LogMessage, lambda e: box["log"].append((e.message, e.level)))

    async def fake_delete(manager):
        res = dict(manager_result)
        return res

    fake_manager = types.SimpleNamespace(
        delete=fake_delete,
        attach=lambda svc: None,
    )
    undo_box = {"pushes": []}
    fake_undo = types.SimpleNamespace(
        push=lambda kind, val: undo_box["pushes"].append((kind, val)),
    )
    ctx = types.SimpleNamespace(
        bus=bus,
        archive=None,
        memory=None,
        label_store=lambda: types.SimpleNamespace(state=lambda: {}),
        undo=fake_undo,
        db_manager=lambda: fake_manager,
    )
    return ctx, box, undo_box


async def run_bridge_action(ctx, op="delete"):
    """Drive DbBridge._db_action without Qt signals (bus events only)."""
    # Import here to allow monkeypatch of restart_world
    from bridge import db_bridge as mod
    calls = {"restart": 0}
    orig_restart = mod.restart_world

    async def spy_restart(*a, **k):
        calls["restart"] += 1
        # don't need real archive; just record
        return None

    with mock.patch.object(mod, "restart_world", side_effect=spy_restart):
        # Build bridge without QObject init? Use __new__ to avoid Qt.
        from bridge.db_bridge import DbBridge
        br = DbBridge.__new__(DbBridge)
        # __init__ subscribes Qt signal; skip Qt, set ctx manually
        br.ctx = ctx
        # call the inner work directly (avoid _run_async ensure_future timing)
        # Replicate _db_action's work() by calling it and awaiting.
        # Instead, call _db_action and wait for bus events.
        # _db_action uses _run_async → ensure_future; we wait.
        br._run_async = lambda scope, coro: asyncio.ensure_future(coro)
        # _db_action needs db_manager property; our br.ctx provides it
        # db_manager property uses self.ctx.db_manager() + attach
        br._db_action(op, lambda m: m.delete("victim.db"),
                      "🗑 {name} deleted")
        # wait for db event
        for _ in range(200):
            await asyncio.sleep(0.01)
            # db event emitted via emit_db_change → bus
            # check via ctx.bus handlers? box is outside; poll by sleeping
            # Caller polls box; here just give time
            if _ > 5:
                break
        await asyncio.sleep(0.1)
    return calls


class TestBridgeResults(unittest.IsolatedAsyncioTestCase):
    async def test_success_payload_and_no_delete_undo(self):
        ctx, box, undo_box = make_ctx(
            {"ok": True, "path": "/tmp/a.db", "was_active": False,
             "before_path": "/tmp/a.db", "media_files_removed": 2})
        calls = await run_bridge_action(ctx, "delete")
        self.assertTrue(box["db"], "db_changed must be emitted")
        payload = box["db"][-1]
        self.assertTrue(payload.get("ok"))
        self.assertEqual(payload.get("action"), "delete")
        # success log, not warn
        levels = [lv for _, lv in box["log"]]
        self.assertIn("success", levels)
        # restart called for success delete (world rebuild)
        self.assertEqual(calls["restart"], 1)
        # never push delete undo
        self.assertEqual(undo_box["pushes"], [])

    async def test_scan_refusal_no_refresh_no_undo_warn(self):
        ctx, box, undo_box = make_ctx(
            {"ok": False, "op": "delete", "path": "/tmp/v.db",
             "error": "cannot verify other world", "phase": "scan",
             "partial": False, "world_changed": False,
             "active_path": "/tmp/a.db",
             "removed_paths": [], "retained_paths": [], "failed_paths": []})
        calls = await run_bridge_action(ctx, "delete")
        payload = box["db"][-1]
        self.assertFalse(payload.get("ok"))
        self.assertIn("verify", payload.get("error", ""))
        self.assertNotIn("success", [lv for _, lv in box["log"]])
        self.assertTrue(any(lv == "warn" for _, lv in box["log"]),
                        "refusal must warn, not succeed")
        self.assertEqual(calls["restart"], 0,
                         "no world change → no restart")
        self.assertEqual(undo_box["pushes"], [])
        self.assertNotIn("switched", payload,
                         "no switch → no switched flag")

    async def test_switch_only_change_refreshes_despite_failure(self):
        ctx, box, undo_box = make_ctx(
            {"ok": False, "op": "delete", "path": "/tmp/v.db",
             "error": "database file is in use", "phase": "database",
             "partial": False, "world_changed": True,
             "active_path": "/tmp/b.db",
             "removed_paths": [], "retained_paths": [], "failed_paths": []})
        calls = await run_bridge_action(ctx, "delete")
        payload = box["db"][-1]
        self.assertFalse(payload.get("ok"))
        self.assertTrue(payload.get("world_changed"))
        # Fixed: restart called even on failure when world moved (red on baseline)
        self.assertEqual(calls["restart"], 1,
                         "switch-only change must rebuild world state")
        self.assertTrue(payload.get("switched"),
                        "wire must tell JS to drop caches")
        self.assertNotIn("success", [lv for _, lv in box["log"]])
        self.assertEqual(undo_box["pushes"], [])

    async def test_partial_failure_truthful_no_success(self):
        ctx, box, undo_box = make_ctx(
            {"ok": False, "op": "delete", "path": "/tmp/v.db",
             "error": "media file busy", "phase": "media",
             "partial": True, "world_changed": True,
             "active_path": "/tmp/b.db",
             "removed_paths": ["/tmp/v.db"],
             "retained_paths": ["/tmp/s.jpg"],
             "failed_paths": ["/tmp/m.jpg"],
             "media_files_removed": 1})
        calls = await run_bridge_action(ctx, "delete")
        payload = box["db"][-1]
        self.assertFalse(payload.get("ok"))
        self.assertTrue(payload.get("partial"))
        self.assertEqual(payload.get("phase"), "media")
        self.assertEqual(payload.get("media_files_removed"), 1)
        self.assertEqual(calls["restart"], 1)
        self.assertTrue(payload.get("switched"))
        self.assertNotIn("success", [lv for _, lv in box["log"]])
        self.assertEqual(undo_box["pushes"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
