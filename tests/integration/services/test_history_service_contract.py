"""services/history — contract gaps beyond test_services_history.py.

test_services_history.py and test_history_service_lifecycle.py pin the
settings/media/gaze/migration/world-switch surfaces. This file pins the
remaining seams the AREA C refactor extracts and must preserve
(docs/REFACTOR_2026-09-09_AREA_C_DESIGN.md §6.3):

  * HistoryExportService: export_chat (json/text/csv), the collector
    runtime (stop state dict / restart branches), the push-binding routing
    (_on_binding / _on_disconnected / _rebind), migrate_install with no
    config, the legacy-queue merge failure path;
  * HistoryQueryService: get_meta_flag false branch, load_gaze value
    guards, preview merge through load_app_settings;
  * HistoryMutateService: apply_settings collector routing + persist after
    close, save_gaze with a closed world.

Run with:  python3 -m pytest tests/integration/services/test_history_service_contract.py
"""

import asyncio
import json
import os
import sys
import tempfile
import types
import unittest
from datetime import datetime
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

from backend.config_manager import ConfigManager  # noqa: E402
from services.history import HistoryService  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "tests"))
from test_chat_parser_delta import FakePage, raw  # noqa: E402

NOW = datetime(2026, 9, 6, 18, 30, 0)


class AddBindingCdp:
    def __init__(self, *args, **kw):
        self.page = FakePage(*args, **kw)
        self.binding_installs = []
        self.events = {}

    def __getattr__(self, name):
        return getattr(self.page, name)

    async def add_binding(self, name):
        self.binding_installs.append(name)
        return True

    def on_event(self, method, callback):
        self.events[method] = callback


class ServiceCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.dir = tempfile.mkdtemp()
        self.cfg = ConfigManager(os.path.join(self.dir, "config.json"))
        media_cfg = dict(self.cfg.get("history", "media", default={}) or {})
        media_cfg["cache_dir"] = os.path.join(self.dir, "saved_media")
        self.cfg.set("history", "media", media_cfg)
        self.page = AddBindingCdp([raw(f"m{i}", idx=i) for i in range(4)])
        self.db_path = os.path.join(self.dir, "history.db")
        self.service = HistoryService(cdp=self.page, config=self.cfg,
                                      db_path=self.db_path)
        await self.service.init()

    async def asyncTearDown(self):
        try:
            await self.service.close()
        except Exception:
            pass

    async def seed_messages(self, nick="Nick", n=4):
        batch = [raw(f"line {i}", direction="in" if i % 2 else "out",
                     from_nick="Me" if i % 2 else nick,
                     time=f"1{i}:0{i}") for i in range(n)]
        await self.service.repo.append(nick, batch, my_nick="Me", now=NOW)


# ══════════════════════════════════════════════════════════════════
# HistoryExportService — export_chat
# ══════════════════════════════════════════════════════════════════
class TestExportChat(ServiceCase):
    async def test_json_export_is_the_full_page(self):
        await self.seed_messages()
        text = await self.service.export_chat("Nick")
        payload = json.loads(text)
        self.assertGreaterEqual(payload["total"], 4)
        self.assertTrue(payload["items"])

    async def test_text_export_lines(self):
        await self.seed_messages()
        text = await self.service.export_chat("Nick", fmt="text")
        lines = text.splitlines()
        self.assertEqual(len(lines), 4)
        self.assertTrue(lines[0].startswith("["))

    async def test_csv_export_has_header_and_rows(self):
        await self.seed_messages()
        text = await self.service.export_chat("Nick", fmt="csv")
        lines = text.splitlines()
        self.assertEqual(lines[0], "time,from,text")
        self.assertEqual(len(lines), 5)

    async def test_unknown_person_exports_empty(self):
        payload = json.loads(await self.service.export_chat("Ghost"))
        self.assertEqual(payload["items"], [])


# ══════════════════════════════════════════════════════════════════
# HistoryExportService — collector runtime + push binding
# ══════════════════════════════════════════════════════════════════
class TestCollectorRuntime(ServiceCase):
    async def test_stop_collector_reports_state_and_restart_branches(self):
        self.service.start()
        state = await self.service._stop_collector()
        self.assertTrue(state["task"])
        self.assertIsNone(self.service._task)
        # restart from the task branch starts the loop again
        self.service._restart_collector({"task": True})
        self.assertIsNotNone(self.service._task)
        state = await self.service._stop_collector()
        # restart from the collector branch only flips the flag
        self.service._restart_collector({"collector": True})
        self.assertTrue(self.service.collector.running)
        self.assertIsNone(self.service._task)
        self.service.collector.stop()

    async def test_start_respects_disabled(self):
        self.service.apply_settings({"enabled": False})
        self.service.start()
        self.assertIsNone(self.service._task)

    async def test_on_binding_routes_push_payloads_only(self):
        with mock.patch.object(self.service.collector, "handle_push",
                               return_value=3) as pushed:
            self.assertIsNone(
                self.service._on_binding({"name": "other", "payload": "{}"}))
            pushed.assert_not_called()
            # the real handle_push is a coroutine — the binding handler
            # hands its result back for the CDP layer to schedule
            result = self.service._on_binding({"name": "__cvbPush",
                                               "payload": "{\"x\":1}"})
            self.assertEqual(await result, 3)
            pushed.assert_called_once_with("{\"x\":1}")

    async def test_on_binding_with_no_params_is_ignored(self):
        self.assertIsNone(self.service._on_binding(None))
        self.assertIsNone(self.service._on_binding({}))

    async def test_disconnect_and_rebind_cycle(self):
        self.service._binding = True
        self.service._on_disconnected()
        self.assertFalse(self.service._binding)
        await self.service._rebind()
        self.assertIn("__cvbPush", self.page.binding_installs)
        self.assertTrue(self.service._binding)

    async def test_install_push_binding_is_idempotent(self):
        self.service._binding = True
        await self.service._install_push_binding()
        first = len(self.page.binding_installs)
        await self.service._install_push_binding()
        self.assertEqual(len(self.page.binding_installs), first)

    async def test_push_binding_unavailable_is_silent(self):
        self.service._binding = False

        async def refuse(name):
            return False

        self.page.add_binding = refuse
        await self.service._install_push_binding()
        self.assertFalse(self.service._binding)


# ══════════════════════════════════════════════════════════════════
# HistoryExportService — migrate_install branches
# ══════════════════════════════════════════════════════════════════
class TestMigrationBranches(ServiceCase):
    async def test_no_config_yields_an_empty_report(self):
        self.service.config = None
        report = await self.service.migrate_install()
        self.assertFalse(any(report.values()))

    async def test_corrupt_legacy_queue_fails_softly(self):
        legacy = os.path.join(self.dir, "legacy.db")
        with open(legacy, "wb") as fh:
            fh.write(b"definitely not sqlite")
        self.service.memory = types.SimpleNamespace(db_path=legacy)
        report = await self.service.migrate_install()
        self.assertFalse(report["queue_merged"],
                         "a corrupt legacy queue must not kill migration")


# ══════════════════════════════════════════════════════════════════
# HistoryQueryService branches
# ══════════════════════════════════════════════════════════════════
class TestQueryBranches(ServiceCase):
    async def test_get_meta_flag_false_when_db_unreadable(self):
        service2 = HistoryService(cdp=self.page, config=self.cfg,
                                  db_path=os.path.join(self.dir, "h2.db"))
        self.assertFalse(await service2.get_meta_flag("anything"),
                         "a not-yet-opened db reads as 'flag unset'")
        await service2.close()

    async def test_load_gaze_ignores_bad_numbers(self):
        await self.service.seed_app_settings()
        await self.service.db.execute(
            "INSERT INTO gaze_data(key, value, updated_at) "
            "VALUES('partner', 'Nick', 'now')")
        await self.service.db.execute(
            "INSERT INTO gaze_data(key, value, updated_at) "
            "VALUES('added', 'not-a-number', 'now')")
        await self.service.db.commit()
        await self.service.load_gaze()
        self.assertEqual(self.service.collector._nick, "Nick")
        self.assertEqual(self.service.collector._added, 0)

    async def test_load_app_settings_merges_preview(self):
        await self.service.db.execute(
            "INSERT INTO app_settings(key, value, updated_at) "
            "VALUES('preview', '{\"page_size\": 7}', 'now')")
        await self.service.db.commit()
        await self.service.load_app_settings()
        preview = self.service.preview_settings()
        self.assertEqual(preview["page_size"], 7)
        self.assertEqual(preview["max_rows"], 400, "siblings are kept")

    async def test_load_app_settings_bad_json_is_ignored(self):
        await self.service.db.execute(
            "INSERT INTO app_settings(key, value, updated_at) "
            "VALUES('my_nick', '{oops', 'now')")
        await self.service.db.commit()
        await self.service.load_app_settings()   # must not raise


# ══════════════════════════════════════════════════════════════════
# HistoryMutateService branches
# ══════════════════════════════════════════════════════════════════
class TestMutateBranches(ServiceCase):
    async def test_apply_settings_routes_collector_and_persists(self):
        collector = self.service.collector
        with mock.patch.object(collector, "configure",
                               wraps=collector.configure) as cfg:
            self.service.apply_settings({
                "enabled": True,
                "media": {"max_file_mb": 40},
                "collector": {"my_nick": "Zoe", "heartbeat_ms": 777},
            })
            cfg.assert_called_once_with(my_nick="Zoe", heartbeat_ms=777)
        settings = self.service.settings()
        self.assertEqual(settings["media"]["max_file_mb"], 40)
        self.assertNotIn("collector", self.service._settings)

    async def test_apply_settings_after_close_does_not_raise(self):
        await self.service.close()
        self.service.apply_settings({"enabled": False})

    async def test_set_my_nick_trims_whitespace(self):
        self.assertEqual(self.service.set_my_nick("  Zoe  Doe "), "Zoe Doe")
        self.assertEqual(self.service.my_nick, "Zoe Doe")

    async def test_save_gaze_with_closed_world_is_a_noop(self):
        service2 = HistoryService(cdp=self.page, config=self.cfg,
                                  db_path=os.path.join(self.dir, "h3.db"))
        service2.collector._nick = "Nick"
        await service2.save_gaze()       # db never opened → no-op, no raise
        try:
            await service2.db.close()
        except Exception:
            pass


if __name__ == "__main__":
    unittest.main(verbosity=2)
