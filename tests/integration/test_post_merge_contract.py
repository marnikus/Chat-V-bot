"""INTEGRATION-01 post-merge contract — the cleanup holds, or the suite fails.

Design ref: docs/INTEGRATION_FIXES_DESIGN_2026-09-10.md (I1–I6, P1–P3).

After areas A–D merged, the only work left is cross-area: shim/alias
retirement, the last stores→backend edge, dead code, the two functions over
CC 25, and the push-binding contract. This file pins the POST-cleanup state:

  * the 11 backend shims + run_service alias + backend.chat_agent_js path
    are GONE and every re-exported name resolves from its canonical home;
  * stores/ has ZERO backend edges; the services→backend edge set is exact
    (runtime vs TYPE_CHECKING vs function-local classified);
  * repo-wide max CC ≤ 25 (the plan's own counter) and the 7 vulture-90
    findings stay fixed — without depending on vulture/radon;
  * the sync-push contract (on_binding returns an awaitable the CDP layer
    schedules) and the pre-split behaviour of _execute_cycle/_normalized.

Process note: everything this file asserts about REMOVED or MOVED modules is
imported function-locally — module-top imports would turn the red phase into
a collection error instead of honest failures.

Run with:  python3 tests/integration/test_post_merge_contract.py
"""

import ast
import asyncio
import importlib
import inspect
import os
import subprocess
import sys
import tempfile
import unittest
import warnings
from collections import defaultdict
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

# Stable homes only at module top (see the process note above).
from actions.base_action import ActionResult  # noqa: E402
from stores.user_memory import UserRecord  # noqa: E402


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _prod_py_files():
    out = []
    for pkg in ("core", "actions", "backend", "bridge", "services",
                "stores", "app"):
        base = os.path.join(ROOT, pkg)
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]
            for name in filenames:
                if name.endswith(".py"):
                    out.append(os.path.join(dirpath, name))
    out.append(os.path.join(ROOT, "main.py"))
    return sorted(out)


def _cc_of(node):
    """The plan's own cyclomatic counter (tools/metrics/deep.py), verbatim."""
    c = 1
    for n in ast.walk(node):
        if isinstance(n, (ast.If, ast.For, ast.AsyncFor, ast.While,
                          ast.ExceptHandler, ast.With, ast.AsyncWith,
                          ast.Assert, ast.IfExp)):
            c += 1
        elif isinstance(n, ast.BoolOp):
            c += len(n.values) - 1
        elif isinstance(n, ast.comprehension):
            c += 1 + len(n.ifs)
        elif isinstance(n, ast.Match):
            c += len(n.cases)
    return c


def _backend_edges(path):
    """(runtime, typeonly, deferred) backend edges of one file.

    runtime      top-level import, outside TYPE_CHECKING
    typeonly     under `if TYPE_CHECKING:`
    deferred     inside a function (lazy import)
    """
    tree = ast.parse(open(path, encoding="utf-8").read())
    runtime, typeonly, deferred = set(), set(), set()

    def record(modname, names, in_type, in_func):
        edges = set()
        if modname == "backend":
            edges = {"backend." + a for a in names if a != "*"}
        elif modname and modname.startswith("backend."):
            edges = {modname}
        elif modname == "backend":
            edges = {"backend"}
        target = (typeonly if in_type
                  else deferred if in_func else runtime)
        target.update(edges)

    def visit(node, in_type=False, in_func=False):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.If) and _is_typechecking(child.test):
                for stmt in child.body:
                    _visit_stmt(stmt, True, in_func)
                for stmt in child.orelse:
                    _visit_stmt(stmt, in_type, in_func)
                continue
            _visit_stmt(child, in_type, in_func)

    def _visit_stmt(node, in_type, in_func):
        func = in_func or isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "backend" or module.startswith("backend."):
                record(module, [a.name for a in node.names],
                       in_type, func)
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name == "backend" or a.name.startswith("backend."):
                    (typeonly if in_type
                     else deferred if func else runtime).add(a.name)
        visit(node, in_type, func)

    visit(tree)
    return runtime, typeonly, deferred


def _is_typechecking(test):
    if isinstance(test, ast.Name) and test.id == "TYPE_CHECKING":
        return True
    return (isinstance(test, ast.Attribute)
            and test.attr == "TYPE_CHECKING")


# ---------------------------------------------------------------------------
# P2 — the removal set is exactly the documented one
# ---------------------------------------------------------------------------

REMOVED_BACKEND_MODULES = [
    "backend.action_engine",
    "backend.chat_agent_js",
    "backend.collector",
    "backend.db_manager",
    "backend.history_db",
    "backend.history_models",
    "backend.history_repo",
    "backend.history_service",
    "backend.label_store",
    "backend.media_store",
    "backend.preset_store",
    "backend.user_memory",
]


class TestShimsAreRetired(unittest.TestCase):
    def test_the_eleven_shims_and_the_moved_module_are_gone(self):
        for mod in REMOVED_BACKEND_MODULES:
            # pop first: order-independent even if another module imported it
            sys.modules.pop(mod, None)
            with self.subTest(module=mod):
                with self.assertRaises(
                        ImportError, msg=f"{mod} still importable"):
                    importlib.import_module(mod)

    def test_the_live_bridge_shim_stays(self):
        from backend.bridge import Bridge, BridgeContext  # noqa: F401

    def test_every_reexported_name_resolves_from_its_canonical_home(self):
        from services.run import (ActionEngine, RunCoordinator,  # noqa
                                  RunHooks, RunProgress, RunState,
                                  RunStateMachine, RunTracer,
                                  normalize_blocks, norm_level,
                                  USER_SCOPED_BLOCKS, STANDALONE_NICK,
                                  RETIRED_BLOCK_KEYS)
        from actions.base_action import (BaseAction, ActionResult,  # noqa
                                         get_action_class,
                                         all_action_ids)
        from services.collector_service import (Collector,  # noqa
                                                CollectorState, DEFAULTS)
        from services.db_service import (DbManager, TRASH_DIR, SUFFIXES,  # noqa
                                         safe_db_name, db_stem,
                                         folder_size, file_group_size)
        from stores.history_db import (HistoryDB, SCHEMA_VERSION,  # noqa
                                       TABLE_COLUMNS)
        from stores.history_models import (MAX_LIVE_ITEMS, Alignment,  # noqa
                                           MessageRecord, fingerprint)
        from stores.history_repo import HistoryRepo, align_batch  # noqa
        from services.history import (HistoryService, HISTORY_DEFAULTS,  # noqa
                                      MAX_FILE_MB_DEFAULT, OLD_MAX_FILE_MB,
                                      _merge, _db_stem)
        from stores.label_store import (LabelStore, PALETTE,  # noqa
                                        DEFAULT_COLOR, MAX_NAME,
                                        normalize_color, FILTER_KEY)
        from stores.media_store import MediaStore, slugify_nick  # noqa
        from stores.preset_store import PresetStore  # noqa
        from stores.user_memory import (UserMemory, UserRecord,  # noqa
                                        _SCHEMA)
        self.assertIs(ActionEngine, RunCoordinator)


class TestRunServiceAliasIsRetired(unittest.TestCase):
    def test_alias_package_is_gone(self):
        sys.modules.pop("services.run_service", None)
        with self.assertRaises(ImportError):
            importlib.import_module("services.run_service")
        self.assertFalse(os.path.exists(
            os.path.join(ROOT, "services", "run_service")))

    def test_services_run_exports_everything_the_alias_did(self):
        import services.run as run
        for name in ("STANDALONE_NICK", "USER_SCOPED_BLOCKS",
                     "RETIRED_BLOCK_KEYS", "RunCoordinator", "RunTracer",
                     "norm_level", "normalize_blocks", "RunProgress",
                     "ActionEngine", "RetryPolicy", "RunHooks",
                     "RunProgressChanged", "RunState", "RunStateMachine"):
            with self.subTest(name=name):
                self.assertTrue(hasattr(run, name), name)


class TestChatAgentJsLivesInCore(unittest.TestCase):
    def test_core_home_has_the_full_api(self):
        from core import chat_agent_js as agent
        self.assertIsInstance(agent.AGENT_VERSION, int)
        self.assertGreater(agent.AGENT_VERSION, 0)
        for fn in ("agent_source", "state_expression",
                   "install_expression", "slice_expression",
                   "drain_expression", "scroll_top_expression",
                   "restore_scroll_expression", "fetch_media_expression"):
            with self.subTest(fn=fn):
                self.assertTrue(callable(getattr(agent, fn)), fn)

    def test_agent_path_resolves_to_the_shipped_js_asset(self):
        from core import chat_agent_js as agent
        self.assertTrue(os.path.isfile(agent.AGENT_PATH),
                        f"AGENT_PATH missing: {agent.AGENT_PATH}")
        self.assertTrue(agent.AGENT_PATH.endswith(
            os.path.join("backend", "js", "chat_agent.js")))
        source = agent.agent_source()
        self.assertIsInstance(source, str)
        self.assertGreater(len(source), 1000)

    def test_core_stays_dependency_free(self):
        runtime, typeonly, deferred = _backend_edges(
            os.path.join(ROOT, "core", "chat_agent_js.py"))
        self.assertEqual(runtime | typeonly | deferred, set())
        tree = ast.parse(open(os.path.join(ROOT, "core", "chat_agent_js.py"),
                              encoding="utf-8").read())
        mods = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods.add(node.module.split(".")[0])
        self.assertLessEqual(mods, {"__future__", "json", "os"})


class TestActionResultLivesInCore(unittest.TestCase):
    def test_all_three_paths_are_the_same_object(self):
        from core.action_result import ActionResult as core_result
        from actions.base import ActionResult as base_result
        from actions.base_action import ActionResult as action_result
        self.assertIs(base_result, core_result)
        self.assertIs(action_result, core_result)
        self.assertEqual((core_result.OK, core_result.FAIL,
                          core_result.SKIP), ("ok", "fail", "skip"))

    def test_backend_imports_no_actions_module(self):
        offenders = {}
        for dirpath, dirnames, filenames in os.walk(
                os.path.join(ROOT, "backend")):
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]
            for name in filenames:
                if not name.endswith(".py"):
                    continue
                tree = ast.parse(open(os.path.join(dirpath, name),
                                      encoding="utf-8").read())
                found = set()
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom):
                        module = node.module or ""
                        if module == "actions" or module.startswith(
                                "actions."):
                            found.add(module or "actions")
                    elif isinstance(node, ast.Import):
                        for alias in node.names:
                            if alias.name == "actions" or \
                                    alias.name.startswith("actions."):
                                found.add(alias.name)
                if found:
                    offenders[os.path.relpath(
                        os.path.join(dirpath, name),
                        ROOT).replace(os.sep, "/")] = sorted(found)
        self.assertEqual(offenders, {},
                         "backend/ must not import actions/ (I7 moved the "
                         "last edge, ActionResult, to core/)")


class TestImportOrderIsCycleFree(unittest.TestCase):
    #: every one of these must import cleanly FIRST in a fresh interpreter.
    #: (Pre-I7, `backend.visual_click` first died in the
    #: visual_click ⇄ actions/__init__.scan() cycle.)
    FIRST_IMPORTS = (
        "backend.visual_click",
        "actions.find_click_runner",
        "actions",
        "services.collector_service",
        "backend.chat_parser",
        "app.bootstrap",
        "main",
    )

    def test_first_import_order_does_not_matter(self):
        env = dict(os.environ)
        env["QT_QPA_PLATFORM"] = "offscreen"
        for module in self.FIRST_IMPORTS:
            with self.subTest(first=module):
                proc = subprocess.run(
                    [sys.executable, "-c",
                     f"import {module}; print('ok')"],
                    cwd=ROOT, env=env, capture_output=True, text=True,
                    timeout=120)
                self.assertEqual(
                    proc.returncode, 0,
                    f"importing {module} first crashed:\n{proc.stderr[-2000:]}")
                self.assertIn("ok", proc.stdout)


# ---------------------------------------------------------------------------
# P1 — layering
# ---------------------------------------------------------------------------

class TestStoresHasNoUpwardEdge(unittest.TestCase):
    def test_zero_backend_edges_in_stores(self):
        offenders = {}
        for name in sorted(os.listdir(os.path.join(ROOT, "stores"))):
            if not name.endswith(".py"):
                continue
            runtime, typeonly, deferred = _backend_edges(
                os.path.join(ROOT, "stores", name))
            found = runtime | typeonly | deferred
            if found:
                offenders[f"stores/{name}"] = sorted(found)
        self.assertEqual(offenders, {},
                         "stores/ must not import backend/ (I3 moved the "
                         "last edge to core/)")


class TestServicesBackendEdgesArePinned(unittest.TestCase):
    #: the exact post-cleanup set (design §2/F7). services/ and backend/ are
    #: one business-logic layer; these edges are accepted — but no new ones.
    RUNTIME = {
        "services/cdp_service.py": {"backend.tab_matcher"},
        "services/collector_service.py": {"backend.chat_parser",
                                          "backend.history_query"},
        "services/history/__init__.py": {"backend.chat_parser",
                                         "backend.history_query"},
        "services/undo_service.py": {"backend.config_manager"},
    }
    TYPEONLY = {
        "services/run/coordinator.py": {"backend.cdp_client",
                                        "backend.criteria_engine"},
    }
    DEFERRED = {
        "services/run/progress.py": {"backend.person_filter"},
    }

    def _collect(self):
        runtime, typeonly, deferred = {}, {}, {}
        for dirpath, dirnames, filenames in os.walk(
                os.path.join(ROOT, "services")):
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]
            for name in filenames:
                if not name.endswith(".py"):
                    continue
                path = os.path.join(dirpath, name)
                rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
                r, t, d = _backend_edges(path)
                if r:
                    runtime[rel] = r
                if t:
                    typeonly[rel] = t
                if d:
                    deferred[rel] = d
        return runtime, typeonly, deferred

    def test_runtime_edges_are_exactly_the_accepted_set(self):
        runtime, _, _ = self._collect()
        self.assertEqual(runtime, self.RUNTIME)

    def test_type_checking_edges_are_exactly_the_accepted_set(self):
        _, typeonly, _ = self._collect()
        self.assertEqual(typeonly, self.TYPEONLY)

    def test_function_local_edges_are_exactly_the_accepted_set(self):
        _, _, deferred = self._collect()
        self.assertEqual(deferred, self.DEFERRED)


# ---------------------------------------------------------------------------
# P3 — gates as tests (no radon/vulture dependency)
# ---------------------------------------------------------------------------

class TestComplexityGate(unittest.TestCase):
    def test_no_production_function_is_over_cc_25(self):
        offenders = []
        for path in _prod_py_files():
            tree = ast.parse(open(path, encoding="utf-8").read())
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    cc = _cc_of(node)
                    if cc > 25:
                        offenders.append(
                            f"{os.path.relpath(path, ROOT)}:{node.lineno} "
                            f"{node.name} CC={cc}")
        self.assertEqual(offenders, [],
                         "Gate 7 allows no function over CC 25:\n"
                         + "\n".join(sorted(offenders)))


class TestDeadCodeGates(unittest.TestCase):
    def test_registry_has_no_iterator_import(self):
        tree = ast.parse(open(os.path.join(ROOT, "actions", "registry.py"),
                              encoding="utf-8").read())
        for node in ast.walk(tree):
            if (isinstance(node, ast.ImportFrom)
                    and node.module == "typing"):
                names = [a.name for a in node.names]
                self.assertNotIn("Iterator", names)
        text = open(os.path.join(ROOT, "actions", "registry.py"),
                    encoding="utf-8").read()
        self.assertNotIn("Iterator", text)

    def test_execute_takes_no_dead_scroll_parser(self):
        tree = ast.parse(open(os.path.join(ROOT, "services", "run",
                                           "coordinator.py"),
                              encoding="utf-8").read())
        for node in ast.walk(tree):
            if (isinstance(node, ast.AsyncFunctionDef)
                    and node.name == "execute"):
                args = [a.arg for a in node.args.args]
                self.assertEqual(args, ["self"],
                                 f"execute{args} still takes dead params")
        text = open(os.path.join(ROOT, "services", "run", "coordinator.py"),
                    encoding="utf-8").read()
        self.assertNotIn("scroll_parser", text)

    def test_hook_params_are_marked_unused(self):
        tree = ast.parse(open(os.path.join(ROOT, "services", "run",
                                           "hooks.py"),
                              encoding="utf-8").read())
        seen = {}
        for node in ast.walk(tree):
            if (isinstance(node, ast.FunctionDef)
                    and node.name in ("pre_run", "post_run",
                                      "on_action_complete")):
                seen[node.name] = [a.arg for a in node.args.args]
        self.assertEqual(set(seen), {"pre_run", "post_run",
                                     "on_action_complete"})
        for name, args in seen.items():
            with self.subTest(hook=name):
                self.assertEqual(args[0], "self")
                self.assertTrue(args[1].startswith("_"),
                                f"{name}{args}: first param must be "
                                f"marked unused")

    def test_lease_exit_args_are_marked_unused(self):
        tree = ast.parse(open(os.path.join(ROOT, "backend", "cdp_client.py"),
                              encoding="utf-8").read())
        for node in ast.walk(tree):
            if (isinstance(node, ast.AsyncFunctionDef)
                    and node.name == "__aexit__"):
                args = [a.arg for a in node.args.args]
                self.assertEqual(args[0], "self")
                for arg in args[1:]:
                    self.assertTrue(arg.startswith("_"),
                                    f"__aexit__{args}: unused args must "
                                    f"be marked")


# ---------------------------------------------------------------------------
# push-binding contract (regression pin — green before and after)
# ---------------------------------------------------------------------------

class TestPushBindingContract(unittest.TestCase):
    def test_on_binding_returns_none_for_foreign_names(self):
        from services.history.runtime import PushBindings
        host = mock.Mock()
        bindings = PushBindings(host)
        self.assertIsNone(bindings.on_binding({"name": "other"}))
        self.assertIsNone(bindings.on_binding(None))
        self.assertIsNone(bindings.on_binding({}))
        host.collector.handle_push.assert_not_called()

    def test_on_binding_hands_the_coroutine_back_for_the_cdp_layer(self):
        from services.history.runtime import PushBindings
        seen = []

        async def fake_push(payload):
            seen.append(payload)
            return 7

        host = mock.Mock()
        host.collector.handle_push = fake_push
        result = PushBindings(host).on_binding(
            {"name": "__cvbPush", "payload": "[1]"})
        self.assertTrue(inspect.isawaitable(result))
        self.assertEqual(asyncio.run(result), 7)
        self.assertEqual(seen, ["[1]"])


class TestCdpDispatchSchedulesAwaitables(unittest.IsolatedAsyncioTestCase):
    async def test_async_listener_result_is_scheduled_not_dropped(self):
        from backend.cdp_client import CDPClient
        client = CDPClient()
        called = []

        async def listener(params):
            called.append(params)

        client.on_event("Runtime.bindingCalled", listener)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            client._dispatch_event({"method": "Runtime.bindingCalled",
                                    "params": {"name": "__cvbPush"}})
            await asyncio.sleep(0.05)
        leaked = [w for w in caught
                  if issubclass(w.category, RuntimeWarning)]
        self.assertEqual(leaked, [],
                         "scheduled coroutine leaked a RuntimeWarning")
        self.assertEqual(called, [{"name": "__cvbPush"}])
        await client.disconnect()


# ---------------------------------------------------------------------------
# pre-split behaviour pins for I5 (green before and after)
# ---------------------------------------------------------------------------

class _FakeMemory:
    def __init__(self, users=None):
        self._users = list(users or [])
        self.marked = []

    async def get_queue(self):
        return [u for u in self._users if not u.messaged]

    async def get_all(self):
        return list(self._users)

    async def upsert_user(self, user):
        self._users.append(user)

    async def mark_messaged(self, nick):
        self.marked.append(nick)


def _pause_block():
    block = mock.Mock()
    block.block_id = "PAUSE"
    block.enabled = True
    block.display_name = "Pause"
    block.icon = "⏸"
    block.execute = mock.AsyncMock(return_value=ActionResult.OK)
    return block


def _user_block():
    block = mock.Mock()
    block.block_id = "CLICK_USER"
    block.enabled = True
    block.display_name = "Click User"
    block.icon = "👆"
    # plain Mock auto-creates truthy attrs — pin the two the engine reads
    block.use_person_from_memory = False
    block.respect_order = False
    block.execute = mock.AsyncMock(return_value=ActionResult.OK)
    return block


class TestExecuteCycleOutcomes(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from services.run import RunCoordinator, RunTracer
        self._old_cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)
        self.addCleanup(os.chdir, self._old_cwd)
        self.addCleanup(self._tmp.cleanup)
        self.memory = _FakeMemory()
        self.engine = RunCoordinator(cdp=None, memory=self.memory,
                                     criteria=None)
        self.engine._tracer = RunTracer("pin")
        self.addCleanup(self.engine._tracer.close)
        self.logs = []
        self.engine.log_msg.connect(self.logs.append)

    async def test_empty_stack_reports_empty_stack(self):
        self.engine._stack = []
        self.assertEqual(await self.engine._execute_cycle(), "empty_stack")

    async def test_user_blocks_with_empty_queue_report_empty(self):
        self.engine._stack = [_user_block()]
        self.assertEqual(await self.engine._execute_cycle(), "empty")

    async def test_standalone_runs_once_without_users(self):
        self.engine._stack = [_pause_block()]
        self.assertEqual(await self.engine._execute_cycle(), "worked")
        self.assertEqual(self.engine.progress.total, 1)

    async def test_stop_between_users_reports_stopped(self):
        self.memory._users = [UserRecord(nick="a"), UserRecord(nick="b")]
        self.engine._stack = [_pause_block()]
        self.engine._stop_requested = True
        self.assertEqual(await self.engine._execute_cycle(), "stopped")

    async def test_queue_run_marks_each_user_messaged(self):
        self.memory._users = [UserRecord(nick="a"), UserRecord(nick="b")]
        self.engine._stack = [_pause_block()]
        self.assertEqual(await self.engine._execute_cycle(), "worked")
        self.assertEqual(self.memory.marked, ["a", "b"])


class TestLabelNormalizationMatrix(unittest.TestCase):
    def _normalized(self, raw):
        from stores.label_state import LabelState
        owner = mock.Mock()
        owner._db = None
        owner._memory = raw
        owner._config = None
        return LabelState(owner)._normalized()

    def test_defs_dedup_by_id_and_casefolded_name(self):
        out = self._normalized({"defs": [
            {"id": "1", "name": "VIP", "color": "red"},
            {"id": "1", "name": "duplicate id", "color": "blue"},
            {"id": "2", "name": "vip", "color": "green"},
            {"id": "3", "name": "  kept  ", "color": "nonsense"},
            "not-a-dict",
            {"id": "", "name": "no id"},
            {"id": "4", "name": ""},
        ], "assign": {}, "filter": {}, "next_id": 0})
        self.assertEqual([d["id"] for d in out["defs"]], ["1", "3"])
        self.assertEqual(out["defs"][1]["name"], "kept")

    def test_assign_keeps_only_known_ids_and_clean_nicks(self):
        out = self._normalized({"defs": [{"id": "1", "name": "A"}],
                                "assign": {" nick ": ["1", "1", "ghost"],
                                           "": ["1"],
                                           "bad": "not-a-list"},
                                "filter": {}, "next_id": 0})
        self.assertEqual(out["assign"], {"nick": ["1"]})

    def test_exclusion_wins_over_inclusion(self):
        out = self._normalized({"defs": [{"id": "1", "name": "A"},
                                         {"id": "2", "name": "B"}],
                                "assign": {},
                                "filter": {"include": ["1", "2", "ghost"],
                                           "exclude": ["2", "ghost"]},
                                "next_id": 5})
        self.assertEqual(out["filter"], {"include": ["1"],
                                         "exclude": ["2"]})
        self.assertEqual(out["next_id"], 5)


if __name__ == "__main__":
    unittest.main()
