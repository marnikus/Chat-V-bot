"""AREA B2 — the god classes stay facades: state, privates and behaviour.

Design ref: docs/REFACTOR_2026-09-09_AREA_B_DESIGN.md §2.1 (the pattern) and
§2.2–§2.6 (what moves where).

A split is only safe when three things keep being true through the facade, and
this file pins all three for every class AREA B decomposes:

1. **state lives on the aggregate** — production code and other areas' tests
   set attributes on the object (`store.paused = True`, `store.now = clock`,
   `db._repair_tables = helper`, `store._data = …`). If B2 moved that state
   into a collaborator, those writes would silently stop working;
2. **the privates other code calls are still reachable** — `repo._last_ord`,
   `store._fetch_one`, `store._free_name`, `db._repair_tables`… (the plan's
   rule "old public names stay and delegate" covers the names other areas'
   tests reach for too);
3. **behaviour is unchanged** — one end-to-end scenario per extracted
   collaborator.

Run with:  python3 tests/unit/stores/test_stores_split_behaviour.py
"""

import asyncio
import base64
import importlib
import inspect
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)

from stores.history_db import SCHEMA_VERSION, HistoryDB        # noqa: E402
from stores.history_models import MessageRecord, fingerprint  # noqa: E402
from stores.history_repo import HistoryRepo                    # noqa: E402
from stores.label_store import LabelStore                      # noqa: E402
from stores.media_store import MediaStore                      # noqa: E402
from stores.preset_store import PresetStore                    # noqa: E402
from stores.user_memory import UserMemory, UserRecord         # noqa: E402


def convo(n, start=0, nick="Nick"):
    return [rec(text=f"m{i}", direction="out" if i % 2 else "in",
                from_nick="Me" if i % 2 else nick,
                time="17:%02d" % ((start + i) % 60), idx=start + i)
            for i in range(start, start + n)]


def rec(text="hi", direction="in", from_nick="Nick", time="17:31",
        kind="text", media=None, occ=0, idx=0):
    payload = media["url"] if media else text
    return MessageRecord(
        fp=fingerprint(direction, from_nick, time, kind, payload, occ),
        direction=direction, from_nick=from_nick, kind=kind, text=text,
        media_url=(media or {}).get("url", ""),
        media_kind=(media or {}).get("kind", ""),
        ts_display=time, occ=occ, idx=idx)


def fetcher(payload: bytes):
    """Stand-in for the Python downloader: always answers with `payload`."""
    async def get(url):
        return {"ok": True, "b64": base64.b64encode(payload).decode(),
                "mime": "image/png", "bytes": len(payload)}
    return get


class FakeCdp:
    """A browser that answers nothing — the Python fallback has to do the work."""

    def __init__(self):
        self.sent = []

    async def evaluate(self, expression, *a, **kw):
        raise RuntimeError("no CORS headers")

    async def get_cookies(self, url=""):
        return "sid=1"

    async def send(self, method, params=None):
        self.sent.append((method, params or {}))
        return {}


class _FakeConfig:
    """Just enough of `backend/config_manager` for LabelStore's config mode."""

    def __init__(self):
        self.data: dict = {}

    def get(self, *keys, default=None):
        node = self.data
        for key in keys:
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return node

    def set(self, *keys_and_value):
        *keys, value = keys_and_value
        node = self.data
        for key in keys[:-1]:
            node = node.setdefault(key, {})
        node[keys[-1]] = value

    def save(self, force: bool = False) -> bool:
        return True


class AggregateCase(unittest.IsolatedAsyncioTestCase):
    """A real DB + every aggregate wired the way `backend/config_manager` is."""

    async def asyncSetUp(self):
        self.dir = tempfile.mkdtemp()
        self.db = HistoryDB(os.path.join(self.dir, "history.db"))
        await self.db.init()
        self.cache = os.path.join(self.dir, "saved_media")
        self.cdp = FakeCdp()
        self.media = MediaStore(self.db, cdp=self.cdp, cache_dir=self.cache)
        self.repo = HistoryRepo(self.db, media=self.media, session_id="s1")

    async def asyncTearDown(self):
        await self.db.close()

    async def file_for(self, url: str, nick: str = "Nick",
                       day: str = "2026-09-06") -> int:
        media_id = await self.media.register(url, kind="image", nick=nick,
                                             day=day)
        self.assertIsNotNone(media_id)
        return media_id


class TestStateStaysOnTheAggregate(AggregateCase):
    async def test_media_cache_dir_redirects_every_write(self):
        self.media.cache_dir = os.path.join(self.dir, "elsewhere")
        self.assertTrue(
            self.media._person_dir("Nick").startswith(
                os.path.join(self.dir, "elsewhere")),
            "the layout collaborator must resolve the folder at call time")

    async def test_media_clock_decides_the_day_folder(self):
        self.media.now = lambda: datetime(2025, 1, 2, 3, 4)
        self.assertEqual(self.media._day(), "2025-01-02")

    async def test_media_switches_gate_the_queue(self):
        await self.file_for("https://cdn.example.com/a.png")
        self.media.paused = True
        self.assertEqual(await self.media.process_pending(), 0,
                         "paused must stop the queue")
        self.media.paused = False
        self.media.enabled = False
        info = await self.media.download_one(1)
        self.assertEqual(info["state"], "pending",
                         "disabled must not touch the network")
        self.media.enabled = True
        self.media._http_fetcher = fetcher(b"z" * 32)
        self.assertEqual(await self.media.process_pending(), 1)

    async def test_media_caps_are_read_at_call_time(self):
        media_id = await self.file_for("https://cdn.example.com/big.png")
        self.media._http_fetcher = fetcher(b"x" * 4096)
        self.media.max_file_bytes = 64
        self.assertEqual((await self.media.download_one(media_id))["state"],
                         "skipped")
        self.media.max_file_bytes = 1024 * 1024
        self.assertEqual((await self.media.download_one(media_id))["state"],
                         "cached",
                         "raising the cap after a failure must let the retry "
                         "succeed — the fetcher may not snapshot the limit")

    async def test_repo_holds_the_db_and_media_store_it_was_given(self):
        self.assertIs(self.repo.db, self.db)
        self.assertIs(self.repo.media, self.media)
        self.assertEqual(self.repo.session_id, "s1")
        self.assertEqual(self.repo._scan_seq, 0,
                         "the recovery scan counter is aggregate state")

    async def test_history_db_repair_hook_is_still_an_instance_attribute(self):
        """`init()` runs `self._repair_tables()` — a swap on the instance wins
        (the pattern `tests/test_db_schema_migration.py` relies on)."""
        other = HistoryDB(os.path.join(self.dir, "second.db"))
        called = []

        async def fake_repair():
            called.append(1)
        other._repair_tables = fake_repair
        await other.init()
        self.assertEqual(called, [1])
        await other.close()

    async def test_label_store_dirty_flag_follows_real_writes(self):
        labels = LabelStore(_FakeConfig(), db=self.db)
        labels.create("VIP", "#ff0000")
        self.assertTrue(labels._dirty, "a write through the db must schedule "
                                        "a flush (the store keeps `_dirty`)")
        labels._dirty = False
        ghost = await self.repo.ensure_person("Ghost")
        labels.unassign(str(ghost), "lbl_999")
        self.assertFalse(labels._dirty,
                         "a no-op unassign must not mark the world dirty")

    async def test_user_memory_queries_read_the_live_db_attribute(self):
        memory = UserMemory(os.path.join(self.dir, "people.db"))
        await memory.init()
        try:
            self.assertIsNotNone(memory._db)
            await memory.upsert_user(UserRecord(nick="Nick", gender="f"))
            stats = await memory.get_stats()
            self.assertEqual(stats["total"], 1)
            self.assertEqual(stats["queued"], 1)
            self.assertEqual((await memory.get_user("Nick")).gender, "f")
        finally:
            await memory.close()

    async def test_preset_store_payload_is_the_live_dict(self):
        path = os.path.join(self.dir, "presets.json")
        PresetStore._by_path.pop(path, None)
        store = PresetStore(path=path)
        store.save_template("t1", "hello")
        self.assertIn("t1", store._data["template_presets"])
        store._data["template_presets"]["injected"] = {"body": "x",
                                                        "created_at": "now"}
        self.assertIn("injected", [row["name"] for row in store.list_templates()])
        PresetStore._by_path.pop(path, None)


class TestPrivatesStayReachable(AggregateCase):
    """Names other code reaches for inside a store — they must survive B2.

    `tests/` of the other areas and `backend/` poke these; the plan's rule
    "old names stay and delegate" covers them exactly like the public API.
    """

    #: expected on the class (method or property), whatever the split does
    ON_CLASS = {
        "HistoryRepo": ["_last_ord", "_recount", "_ui_record", "_after_write",
                        "_media_id", "_resequence", "recover_media",
                        "has_repairable_media", "_all_person_keys",
                        "_existing_dup_keys", "_take_empty_slot",
                        "_touch_cursor", "_slot_key", "_media_key",
                        "_person_dict", "_ord_of", "_empty_slot_rows",
                        "_fill_slot", "_record_gap", "_prepend", "append"],
        "MediaStore": ["_fetch_one", "_free_name", "_person_dir", "_marker",
                       "_write_marker", "_target_path", "_day", "_abs_url",
                       "_twin", "_fail", "_skip", "_evict",
                       "_finish_network_body", "_fetch_in_page",
                       "_fetch_via_python", "_fetch_via_network", "_as_id",
                       "folder_for", "NICK_MARKER"],
        "HistoryDB": ["_table_columns", "_repair_tables", "_verify_schema",
                      "_rebuild_legacy_messages", "_rebuild_messages_constraint",
                      "_has_legacy_messages_constraint", "_migrate_dup_keys",
                      "db_fetch_legacy", "_count_rows", "_person_for_nick",
                      "_read_version", "_try_fts", "_add_missing_columns",
                      "LATE_COLUMNS", "normalise_nick"],
        "LabelStore": ["_normalized", "_write", "_raw", "_save", "_raw_config",
                       "_memory_state", "_initial_state", "_schedule_flush",
                       "_guarded_flush", "db", "SECTION"],
        "UserMemory": ["_row"],
        "PresetStore": ["_now"],
    }
    #: set by `__init__` on the instance — the aggregate, never a copy
    ON_INSTANCE = {
        "repo": ["_scan_seq"],
        "media": ["_dirs", "_http_fetcher"],
        "db": ["path", "_conn", "_want_fts"],
    }

    def test_every_reachable_method_is_still_on_the_class(self):
        for cls_name, names in self.ON_CLASS.items():
            klass = globals()[cls_name]
            for name in names:
                with self.subTest(cls=cls_name, name=name):
                    self.assertTrue(hasattr(klass, name),
                                    f"{cls_name}.{name} is gone — B2 must "
                                    "delegate, not remove")

    def test_instance_state_lives_on_the_aggregate(self):
        for attr, names in self.ON_INSTANCE.items():
            owner = getattr(self, attr)
            for name in names:
                with self.subTest(cls=type(owner).__name__, name=name):
                    self.assertTrue(hasattr(owner, name),
                                    f"{type(owner).__name__}.{name} must stay a "
                                    "live attribute (settable from outside)")

    async def test_the_stores_the_facade_builds_are_reachable_too(self):
        labels = LabelStore(_FakeConfig(), db=self.db)
        self.assertIsInstance(labels._dirty, bool)
        self.assertIs(labels.db, self.db)
        self.assertTrue(callable(labels._write))
        path = os.path.join(self.dir, "presets.json")
        PresetStore._by_path.pop(path, None)
        presets = PresetStore(path=path)
        self.assertEqual(presets.path, path)
        self.assertTrue(hasattr(presets, "_data"))
        PresetStore._by_path.pop(path, None)


class TestCollaboratorScenarios(AggregateCase):
    async def test_identity_person_lookup_is_one_row_per_nick(self):
        person = await self.repo.ensure_person("  Nick  ")
        self.assertEqual(person, await self.repo.ensure_person("Nick"))
        self.assertEqual((await self.repo.get_person("Nick"))["nick"], "Nick")
        self.assertIsNone(await self.repo.get_person("nobody"))
        self.assertEqual(await self.repo.possible_duplicates(), [],
                         "no similar nicks yet")

    async def test_append_is_idempotent_through_the_planner(self):
        batch = convo(5)
        first = await self.repo.append("Nick", batch, my_nick="Me", dom_count=5)
        second = await self.repo.append("Nick", batch, my_nick="Me", dom_count=5)
        self.assertEqual(first.added, 5)
        self.assertEqual(second.added, 0)
        self.assertEqual(second.skipped, 5)
        cursor = await self.repo.get_cursor(first.person_id)
        self.assertEqual(len(cursor["tail_fps"]), 5)
        self.assertEqual(cursor["last_ord"], first.last_ord)

    async def test_prepend_shifts_ord_and_keeps_it_dense(self):
        first = await self.repo.append("Nick", convo(3, start=3), my_nick="Me",
                                       dom_count=3)
        early = [rec(text="first", direction="in", from_nick="Nick",
                     time="09:00", idx=0)]
        again = await self.repo.append("Nick", early, my_nick="Me", dom_count=4,
                                       prepend=True)
        self.assertEqual(again.added, 1)
        self.assertEqual(again.first_ord, 1)
        rows = await self.db.fetchdicts(
            "SELECT ord FROM messages WHERE person_id=? ORDER BY ord",
            (first.person_id,))
        self.assertEqual([r["ord"] for r in rows], list(range(1, len(rows) + 1)))
        self.assertEqual(await self.repo._last_ord(first.person_id), len(rows))

    async def test_recovery_fills_an_empty_slot_and_marks_the_row(self):
        empty = rec(text="", kind="image", time="17:45", idx=7)
        result = await self.repo.append("Nick", [empty], my_nick="Me",
                                        dom_count=1)
        self.assertEqual(result.added, 1, "the empty slot is archived")
        self.assertTrue(await self.repo.has_repairable_media(result.person_id))
        filled = rec(text="", kind="image",
                     media={"url": "https://c/x.png", "kind": "image"},
                     time="17:45", idx=7)
        report = await self.repo.recover_media(
            result.person_id, [filled], media=self.media, nick="Nick")
        self.assertEqual(set(report), {"repaired", "requeued", "scanned"})
        self.assertEqual(report["repaired"], 1,
                         "the URL found in the DOM must land on the archived "
                         "line (HRP-34)")
        self.assertEqual(self.repo._scan_seq, 1,
                         "the scan counter lives on the aggregate")
        self.assertFalse(await self.repo.has_repairable_media(result.person_id))

    async def test_lifecycle_tokens_gate_the_deletes(self):
        await self.repo.append("Nick", convo(3), my_nick="Me", dom_count=3)
        token = HistoryRepo.new_op_token()
        self.assertNotEqual(token, HistoryRepo.new_op_token())
        issued = await self.repo.soft_delete_history("Nick", token)
        self.assertEqual(await self.repo.deleted_count("Nick"), 3)
        self.assertFalse(await self.repo.soft_delete_history("Nick", "wrong"),
                         "a stale token must be refused, not crash")
        self.assertEqual(await self.repo.restore_deleted("Nick", issued or token), 3)
        self.assertEqual(await self.repo.deleted_count("Nick"), 0)

    async def test_media_layout_claim_survives_a_restart(self):
        """`Anski` and `Ански` transliterate to the same folder: the marker
        keeps the owner, the late-comer gets a hashed variant — and a new
        process must reach the same conclusion (MED-04)."""
        mine = self.media._target_path("Anski", "image", "2026-09-06", ".png")
        self.assertTrue(os.path.isfile(
            os.path.join(os.path.dirname(os.path.dirname(mine)),
                         MediaStore.NICK_MARKER)))
        store = MediaStore(self.db, cdp=self.cdp, cache_dir=self.cache)
        self.assertEqual(store._person_dir("Anski"),
                         self.media._person_dir("Anski"),
                         "the owner keeps its folder across a restart")
        other = store._person_dir("Ански")
        self.assertNotEqual(other, store._person_dir("Anski"))
        self.assertTrue(other.startswith(os.path.abspath(self.cache)))

    async def test_media_cache_policy_evicts_and_reports(self):
        self.media._http_fetcher = fetcher(b"y" * 2048)
        self.media.max_cache_bytes = 4 * 1024
        for i in range(4):
            await self.file_for(f"https://cdn.example.com/{i}.png")
        self.assertGreaterEqual(await self.media.process_pending(), 3)
        await self.media.evict_if_needed()
        usage = await self.media.cache_usage()
        self.assertLessEqual(usage["bytes"], self.media.max_cache_bytes)
        self.assertGreaterEqual(await self.media.clear_cache(), 1)
        self.assertEqual((await self.media.cache_usage())["files"], 0)

    async def test_schema_migrator_repairs_a_legacy_file(self):
        legacy = os.path.join(self.dir, "legacy.db")
        con = sqlite3.connect(legacy)
        con.executescript(
            "CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "nick TEXT, direction TEXT, ts_display TEXT, kind TEXT, text TEXT,"
            " media_url TEXT, fp TEXT UNIQUE, occ INTEGER, idx INTEGER);")
        con.execute("INSERT INTO messages (nick, direction, ts_display, kind,"
                    " text, fp, occ, idx) VALUES"
                    " ('Nick', 'in', '17:31', 'text', 'old', 'fp1', 0, 0)")
        con.commit()
        con.close()
        db = HistoryDB(legacy)
        await db.init()
        self.assertIn("person_id", await db._table_columns("messages"))
        self.assertIn("dup_key", await db._table_columns("messages"))
        self.assertEqual(await db.scalar("SELECT COUNT(*) FROM messages"), 1)
        self.assertEqual(await db._read_version(), SCHEMA_VERSION,
                         "the repaired file is stamped with the current version")
        await db.close()

    async def test_label_filter_and_world_round_trip(self):
        labels = LabelStore(_FakeConfig(), db=self.db)
        vip = labels.create("VIP", "not-a-colour")
        self.assertTrue(vip["color"].startswith("#"),
                        "a garbage colour falls back to the palette")
        self.assertIsNone(labels.create("vip"), "names are unique, case-free")
        person = await self.repo.ensure_person("Nick")
        self.assertTrue(labels.assign(str(person), vip["id"]))
        self.assertEqual([d["name"] for d in labels.labels_for(str(person))],
                         ["VIP"])
        labels.set_filter(include=[vip["id"]])
        self.assertTrue(labels.filter_active)
        self.assertTrue(labels.allows(str(person)))
        self.assertFalse(labels.allows("999"))
        self.assertTrue(labels.reject_reason("999"))
        snapshot = labels.snapshot()
        labels.set_filter()
        labels.restore(snapshot)
        self.assertEqual(labels.filter(), snapshot["filter"])

    async def test_user_query_reads_the_people_table(self):
        memory = UserMemory(os.path.join(self.dir, "people2.db"))
        await memory.init()
        try:
            await memory.upsert_many([UserRecord(nick="A", gender="f"),
                                      UserRecord(nick="B", gender="m")])
            self.assertEqual(await memory.count_unmessaged(), 2)
            self.assertEqual(sorted(u.nick for u in await memory.get_queue()),
                             ["A", "B"])
            self.assertEqual((await memory.get_user("A")).gender, "f")
            await memory.mark_messaged("A")
            self.assertEqual(await memory.count_unmessaged(), 1)
        finally:
            await memory.close()

    async def test_preset_migration_imports_a_legacy_table(self):
        legacy = os.path.join(self.dir, "chatbot.db")
        con = sqlite3.connect(legacy)
        con.executescript("CREATE TABLE templates (name TEXT PRIMARY KEY,"
                          " body TEXT);"
                          "CREATE TABLE stacks (name TEXT PRIMARY KEY,"
                          " blocks TEXT);")
        con.execute("INSERT INTO templates VALUES ('old', 'body text')")
        con.execute("INSERT INTO stacks VALUES ('stack', "
                    "'[\"kind=text\", \"hi\"]')")
        con.commit()
        con.close()
        path = os.path.join(self.dir, "presets.json")
        PresetStore._by_path.pop(path, None)
        store = PresetStore(path=path)
        self.assertTrue(store.import_legacy(legacy))
        self.assertIn("old", [row["name"] for row in store.list_templates()])
        self.assertIn("stack", [row["name"] for row in store.list_stacks()])
        self.assertFalse(store.import_legacy(legacy),
                         "a second import must not run at all")
        PresetStore._by_path.pop(path, None)


class TestSplitIsInternal(AggregateCase):
    """The plan's rule: the old names stay and delegate (no second copy)."""

    COLLABORATORS = [
        (HistoryRepo, "identity", "stores.history_repo_identity"),
        (HistoryRepo, "planner", "stores.history_repo_append"),
        (HistoryRepo, "media_recovery", "stores.history_repo_media"),
        (HistoryRepo, "lifecycle", "stores.history_repo_lifecycle"),
        (MediaStore, "layout", "stores.media_layout"),
        (MediaStore, "fetcher", "stores.media_fetch"),
        (MediaStore, "policy", "stores.media_cache"),
        (HistoryDB, "migrator", "stores.history_schema_repair"),
        (LabelStore, "defs", "stores.label_definitions"),
        (LabelStore, "assignments", "stores.label_assignments"),
        (LabelStore, "filters", "stores.label_filter"),
        (UserMemory, "query", "stores.user_query"),
        (PresetStore, "migration", "stores.preset_migration"),
    ]

    def test_facade_and_collaborator_are_not_two_implementations(self):
        for klass, attr, module in self.COLLABORATORS:
            try:
                target = importlib.import_module(module)
            except ImportError:
                self.skipTest(f"{module} is B2 work")
                return
            functions = {name for name, value in vars(target).items()
                         if inspect.isfunction(value)}
            for name, member in inspect.getmembers(klass, inspect.isfunction):
                if name.startswith("__"):
                    continue
                with self.subTest(cls=klass.__name__, name=name):
                    self.assertNotIn(
                        name, functions,
                        f"{module}.{name} and {klass.__name__}.{name} are two "
                        "implementations — one must call the other")

    def test_a_collaborator_is_built_from_the_aggregate_only(self):
        for klass, attr, module in self.COLLABORATORS:
            try:
                target = importlib.import_module(module)
            except ImportError:
                self.skipTest(f"{module} is B2 work")
                return
            for value in vars(target).values():
                if not (isinstance(value, type)
                        and value.__module__ == module
                        and not value.__name__.startswith("_")):
                    continue
                params = list(inspect.signature(value.__init__).parameters)
                with self.subTest(cls=f"{module}.{value.__name__}"):
                    self.assertEqual(
                        params[:2], ["self", "owner"],
                        "a collaborator is constructed from the aggregate so "
                        "it always reads live state (design §2.1)")


if __name__ == "__main__":
    unittest.main()
