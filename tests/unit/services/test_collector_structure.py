"""Round F step F2 exit gates — the `Collector` decomposition must not rot.

Design ref: docs/archive/2026-09-12-round-f-size-tail/
            ROUND_F2_F3_GOD_CLASS_DESIGN_2026-09-12.md

`services/collector_service.py::Collector` was a god class: 526 class LOC, 40
methods, LCOM 0.92. F2 moved the behaviour into six collaborators using the
convention `tests/unit/stores/test_stores_structure.py` already pins for
`stores/` — a part is built from the aggregate and nothing else, and the state
stays on the aggregate.

Three things make this split harder than the stores one, so each gets its own
gate here rather than a comment in the design doc:

  * `services/collector_tick.py` was extracted earlier and calls back into the
    Collector through `host.<name>` — 32 distinct names. That is a live
    protocol: if a name stops being reachable on the facade the tick state
    machine breaks at *runtime*, deep inside a heartbeat, not at import time.
  * `tests/integration/services/test_collector_tick_phases.py` patches
    `"services.collector_service.sync_conversation"`. A patch only bites if the
    code under test looks the name up in that module, so `_sync` must stay
    there — moving it would leave the patch silently vacuous and the test
    still green (the trap step F1 hit).
  * the facade deliberately keeps all 40 method NAMES. Bridges, the history
    services and the tests call them on the instance; only the bodies moved.

Run with:  python3 tests/unit/services/test_collector_structure.py
"""

import ast
import importlib
import inspect
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)

FACADE = "services.collector_service"

# attr on the facade -> module holding the behaviour
COLLABORATORS = {
    "_pacing": "services.collector_pacing",
    "_report": "services.collector_report",
    "_push": "services.collector_push",
    "_partner": "services.collector_partner",
    "_knobs": "services.collector_settings",
    "_loop": "services.collector_loop",
}

# the behaviour F2 moved out; each must be a thin delegator on the facade and a
# real body in its collaborator
MOVED = {
    "_pacing": ["note_probe_duration", "next_interval_ms", "on_run_started",
                "on_run_finished"],
    "_report": ["state_payload", "reset_state", "_payload", "_records",
                "_notify_people", "_no_new_text", "_log", "_set", "_emit"],
    "_push": ["_refuse", "_gate_status", "_push_ready", "_gate_check",
              "_append_push", "_announce_push", "handle_push"],
    "_partner": ["_remember_partner", "_notify_appended", "person_cleared"],
    "_knobs": ["configure", "settings"],
    "_loop": ["run", "tick"],
}


def _classes(module):
    return [v for v in vars(module).values()
            if isinstance(v, type) and v.__module__ == module.__name__
            and not v.__name__.startswith("_")]


class TestCollectorDecomposition(unittest.TestCase):

    def test_every_collaborator_module_exists(self):
        for target in COLLABORATORS.values():
            with self.subTest(module=target):
                self.assertTrue(_classes(importlib.import_module(target)),
                                f"{target} defines no public class")

    def test_the_facade_builds_each_collaborator_from_itself(self):
        """`__init__` composes the parts, passing `self` (design §2.1)."""
        klass = getattr(importlib.import_module(FACADE), "Collector")
        src = inspect.getsource(klass.__init__)
        for attr, target in COLLABORATORS.items():
            part = importlib.import_module(target)
            pattern = "|".join(f"{c.__name__}\\(self" for c in _classes(part))
            with self.subTest(part=attr):
                self.assertRegex(
                    src, pattern,
                    f"Collector.__init__ must build {attr} from one of "
                    f"{[c.__name__ for c in _classes(part)]}")

    def test_a_collaborator_takes_the_aggregate_and_nothing_else(self):
        for target in COLLABORATORS.values():
            part = importlib.import_module(target)
            for value in _classes(part):
                params = list(inspect.signature(value.__init__).parameters)
                with self.subTest(cls=f"{target}.{value.__name__}"):
                    self.assertEqual(
                        params[:2], ["self", "owner"],
                        "a collaborator is built from the aggregate only — "
                        "state stays on the aggregate")

    def test_the_tick_host_protocol_stays_reachable_on_the_facade(self):
        """Every `host.<name>` collector_tick.py uses must still resolve.

        Read straight out of collector_tick.py, so the gate follows the
        protocol instead of freezing a copy of it. The protocol mixes two kinds
        of name and each is checked the way it can actually exist:

          * methods and properties (`host._log`, `host.configure`,
            `host.my_nick`) live on the class;
          * plain state (`host._nick`, `host.repo`, `host._settings`) is
            assigned in `__init__`, so it exists on the INSTANCE and never on
            the class — which is exactly why F2 left all of it on the
            aggregate instead of moving it into the collaborators.
        """
        path = os.path.join(ROOT, "services", "collector_tick.py")
        with open(path, encoding="utf-8") as fh:
            tick = ast.parse(fh.read())
        wanted = set()
        for node in ast.walk(tick):
            if (isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "host"):
                wanted.add(node.attr)
        self.assertGreater(len(wanted), 25,
                           "expected the tick state machine to use the host "
                           f"protocol, found only {sorted(wanted)}")

        fpath = os.path.join(ROOT, "services", "collector_service.py")
        with open(fpath, encoding="utf-8") as fh:
            fsrc = fh.read()
        klass = next(n for n in ast.parse(fsrc).body
                     if isinstance(n, ast.ClassDef) and n.name == "Collector")
        on_class = {m.name for m in klass.body
                    if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))}
        on_class |= {t.id for m in klass.body
                     if isinstance(m, ast.Assign) for t in m.targets
                     if isinstance(t, ast.Name)}          # the Signals
        assigned = set()
        for node in ast.walk(klass):
            if (isinstance(node, ast.Attribute) and node.attr not in on_class
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "self" and isinstance(node.ctx,
                                                              ast.Store)):
                assigned.add(node.attr)

        for name in sorted(wanted):
            with self.subTest(host=name):
                self.assertTrue(
                    name in on_class or name in assigned,
                    f"collector_tick.py calls host.{name}, but Collector no "
                    "longer provides it as a method/property or as state set "
                    "in __init__ — the tick would break at runtime")


    def test_the_bodies_live_in_the_collaborators_not_the_facade(self):
        """A moved name is a bare `return self.<part>.<name>(...)` here, and
        real code over there.

        This is what stops the split being undone method by method: logic
        re-inlined into the facade stops being a single return.
        """
        path = os.path.join(ROOT, "services", "collector_service.py")
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        klass = next(n for n in tree.body
                     if isinstance(n, ast.ClassDef) and n.name == "Collector")
        on_facade = {m.name: m for m in klass.body
                     if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))}
        for attr, names in MOVED.items():
            part = importlib.import_module(COLLABORATORS[attr])
            owner = _classes(part)[0]
            for name in names:
                with self.subTest(name=name):
                    self.assertTrue(hasattr(owner, name),
                                    f"{owner.__name__} lost {name}")
                    self.assertIn(name, on_facade,
                                  f"Collector no longer exposes {name}")
                    body = [s for s in on_facade[name].body
                            if not (isinstance(s, ast.Expr)
                                    and isinstance(s.value, ast.Constant))]
                    self.assertEqual(
                        len(body), 1,
                        f"Collector.{name} should be a one-line delegator to "
                        f"{owner.__name__}, not a place to grow logic back")
                    self.assertIsInstance(body[0], ast.Return)
                    told = ast.unparse(body[0])
                    self.assertTrue(
                        attr in told or owner.__name__ in told,
                        f"Collector.{name} must delegate to {attr} "
                        f"(staticmethods/classmethods name {owner.__name__} "
                        f"directly), got: {told}")

    def test_sync_stays_in_the_facade_module(self):
        """`_sync` must keep resolving `sync_conversation` in this module.

        test_collector_tick_phases.py patches
        "services.collector_service.sync_conversation"; if `_sync` moved out,
        the patch would stop biting and that test would pass for the wrong
        reason.
        """
        mod = importlib.import_module(FACADE)
        self.assertTrue(hasattr(mod, "sync_conversation"),
                        "the patch target name is gone from the module")
        klass = getattr(mod, "Collector")
        src = inspect.getsource(klass._sync)
        self.assertIn("sync_conversation(", src,
                      "_sync must still call the module-level name the test "
                      "patches")
        for attr in COLLABORATORS:
            self.assertNotIn(f"self.{attr}.", src,
                             "_sync must stay a real body on the facade, not a "
                             "delegator — see the patch-target note above")

    def test_the_facade_stays_inside_the_size_band(self):
        """May shrink, may not grow (RULE 18.2 band, ratcheted at F2)."""
        path = os.path.join(ROOT, "services", "collector_service.py")
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        lines = src.split("\n")
        self.assertLessEqual(
            len(lines), 300,
            "RULE 18.2 puts a module in the 150-300 line band; over 300 means "
            "a second responsibility crept back in")
        tree = ast.parse(src)
        cls = next(n for n in tree.body
                   if isinstance(n, ast.ClassDef) and n.name == "Collector")
        self.assertLessEqual(
            cls.end_lineno - cls.lineno + 1, 239,
            "Collector was 526 class LOC before F2 and 239 after; the house "
            "facades in stores/ sit at 202-232")


if __name__ == "__main__":
    unittest.main()
