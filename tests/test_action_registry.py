"""`actions.registry` — the block palette contract (P0).

SPEC-FIRST: every case below is written from the *documented* contract, not
from the implementation (docs/ACTIONS_TEST_DESIGN_2026-09-09.md §1):

  * module docstring — "@register(\"MY_BLOCK\") registers the action class",
    "No manual import list needed; discover() scans the package";
  * `register` docstring — "block_id must be non-empty";
  * `discover` docstring — "Returns number of newly discovered block ids";
  * `actions/__init__.py` docstring — "discover() scans the package and fires
    @register decorators **(or __init_subclass__ hooks)**".

That last line is the whole point of REG-01/REG-02: the two documented
registration mechanisms must feed ONE registry, because the package
re-exports `get_action_class` / `all_action_ids` as the app's palette API.

Run with:  python3 tests/test_action_registry.py
"""

import importlib
import os
import re
import sys
import tempfile
import textwrap
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import actions  # noqa: E402
from actions import registry  # noqa: E402
from actions.base_action import BaseAction  # noqa: E402
from actions.pause import Pause  # noqa: E402

ACTIONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "..", "actions")

_BLOCK_ID_RE = re.compile(r'^\s*block_id\s*=\s*"([A-Z_0-9]+)"', re.M)


def declared_block_ids() -> dict:
    """Every block id the package *declares*, read straight from the source.

    Derived from the files, not from any registry, so a block that fails to
    import is still expected to show up in the palette.
    """
    found = {}
    for name in sorted(os.listdir(ACTIONS_DIR)):
        if not name.endswith(".py") or name == "__init__.py":
            continue
        with open(os.path.join(ACTIONS_DIR, name), encoding="utf-8") as fh:
            for bid in _BLOCK_ID_RE.findall(fh.read()):
                found[bid] = name
    return found


class RegistryIsolation(unittest.TestCase):
    """Save/restore the process-global registry (no public clear() exists)."""

    def setUp(self):
        self._snapshot = dict(registry._REGISTRY)

    def tearDown(self):
        registry._REGISTRY.clear()
        registry._REGISTRY.update(self._snapshot)


class TestPaletteApi(RegistryIsolation):
    """REG-01 .. REG-03 — the package API must see every registered block."""

    def test_get_action_class_resolves_a_block_registered_by_subclass_hook(self):
        """REG-01: PAUSE registers via __init_subclass__, not @register.

        The package docstring promises both mechanisms fill the palette, so
        the re-exported getter has to find it.
        """
        self.assertIs(actions.get_action_class("PAUSE"), Pause)

    @unittest.expectedFailure  # BUG-02: see docs/ACTIONS_TEST_DESIGN_2026-09-09.md §12
    def test_all_action_ids_contains_every_declared_block(self):
        """REG-02: the palette lists every block the package declares.

        BLOCKED by BUG-02, not by the registry: `actions/collect_history.py`
        imports `backend.chat_parser`, which dies with
        `NameError: name 'TABLE_ORDER' is not defined` inside
        `backend/history_db_parts/helpers.py` (the schema constants were lost
        in the <150-LOC split and exist nowhere in the repo). Until they are
        restored, COLLECT_HISTORY cannot be imported and therefore cannot
        register. `unittest.expectedFailure` keeps the contract pinned: this
        turns into an "unexpected success" the day the schema is back.
        """
        declared = set(declared_block_ids())
        self.assertTrue(declared, "no block ids were discovered in actions/")
        registered = set(actions.all_action_ids())
        missing = declared - registered
        self.assertEqual(
            set(), missing,
            "these declared blocks are missing from the palette: "
            + ", ".join(f"{b} ({declared_block_ids()[b]})" for b in sorted(missing)))

    def test_unknown_block_id_returns_none_not_keyerror(self):
        """REG-03."""
        self.assertIsNone(actions.get_action_class("NO_SUCH_BLOCK"))
        self.assertIsNone(registry.get_action_class("NO_SUCH_BLOCK"))


class TestRegisterDecorator(RegistryIsolation):
    """REG-04 .. REG-07 — the @register path itself."""

    def test_register_returns_the_same_class_and_sets_block_id(self):
        """REG-04."""
        @registry.register("SPEC_TEST_ID")
        class Sample(BaseAction):
            async def execute(self, user_nick, cdp, engine=None):
                return "ok"

        self.assertIs(registry.get_action_class("SPEC_TEST_ID"), Sample)
        self.assertEqual(Sample.block_id, "SPEC_TEST_ID")
        self.assertIn("SPEC_TEST_ID", actions.all_action_ids())

    def test_empty_block_id_is_rejected(self):
        """REG-05: "register: block_id must be non-empty"."""
        with self.assertRaises(ValueError) as ctx:
            @registry.register("")
            class Bad(BaseAction):
                async def execute(self, user_nick, cdp, engine=None):
                    return "ok"
        self.assertIn("non-empty", str(ctx.exception))

    def test_duplicate_id_keeps_the_last_class_and_lists_the_id_once(self):
        """REG-06: duplicate — last writer wins, no duplicate palette entry."""
        @registry.register("SPEC_DUP")
        class First(BaseAction):
            async def execute(self, user_nick, cdp, engine=None):
                return "ok"

        @registry.register("SPEC_DUP")
        class Second(BaseAction):
            async def execute(self, user_nick, cdp, engine=None):
                return "ok"

        self.assertIs(registry.get_action_class("SPEC_DUP"), Second)
        self.assertEqual(actions.all_action_ids().count("SPEC_DUP"), 1)
        self.assertNotIn(First, registry._REGISTRY.values())

    def test_shadowing_a_real_block_is_reported(self):
        """REG-07: shadow — hijacking a live block must be visible in the log.

        A silent overwrite means a preset/plugin can quietly replace e.g.
        CLICK_SEND, and the user only finds out when the bot sends to the
        wrong place.
        """
        @registry.register("SPEC_SHADOWED")
        class Original(BaseAction):
            async def execute(self, user_nick, cdp, engine=None):
                return "ok"

        with self.assertLogs("chatbot", level="WARNING") as caught:
            @registry.register("SPEC_SHADOWED")
            class Replacement(BaseAction):
                async def execute(self, user_nick, cdp, engine=None):
                    return "ok"

        self.assertIs(registry.get_action_class("SPEC_SHADOWED"), Replacement)
        self.assertTrue(any("SPEC_SHADOWED" in line for line in caught.output),
                        f"no warning named the shadowed id: {caught.output}")


class TestDiscover(RegistryIsolation):
    """REG-08 .. REG-11 — the pkgutil scan."""

    def test_second_discover_reports_nothing_new_and_changes_nothing(self):
        """REG-08: "number of NEWLY discovered block ids"."""
        before = sorted(registry.all_action_ids())
        self.assertEqual(registry.discover(), 0)
        self.assertEqual(sorted(registry.all_action_ids()), before)

    def test_missing_package_returns_zero_without_raising(self):
        """REG-09."""
        self.assertEqual(registry.discover("no_such_package_xyz"), 0)

    def test_scan_skips_registry_and_base_action_modules(self):
        """REG-10: the scan never treats its own plumbing as a block."""
        seen = []
        real_import = importlib.import_module

        def spy(name, *a, **kw):
            seen.append(name)
            return real_import(name, *a, **kw)

        with mock.patch.object(importlib, "import_module", side_effect=spy):
            registry.discover()

        self.assertIn("actions.pause", seen)
        self.assertNotIn("actions.registry", seen)
        self.assertNotIn("actions.base_action", seen)

    def test_a_broken_block_module_neither_hides_the_others_nor_the_error(self):
        """REG-11: one bad module must not empty the palette, silently.

        This is the exact shape of BUG-02: a single NameError in one import
        chain made a whole block vanish from the app with nothing logged.
        """
        pkg_dir = tempfile.mkdtemp()
        name = "spec_broken_pkg"
        os.mkdir(os.path.join(pkg_dir, name))
        with open(os.path.join(pkg_dir, name, "__init__.py"), "w") as fh:
            fh.write("")
        with open(os.path.join(pkg_dir, name, "good_block.py"), "w") as fh:
            fh.write(textwrap.dedent('''
                from actions.base_action import BaseAction
                from actions.registry import register

                @register("SPEC_GOOD_BLOCK")
                class Good(BaseAction):
                    async def execute(self, user_nick, cdp, engine=None):
                        return "ok"
            '''))
        with open(os.path.join(pkg_dir, name, "bad_block.py"), "w") as fh:
            fh.write("raise RuntimeError('boom from bad_block')\n")

        sys.path.insert(0, pkg_dir)
        try:
            with self.assertLogs("chatbot", level="WARNING") as caught:
                new = registry.discover(name)
        finally:
            sys.path.remove(pkg_dir)
            for mod in [m for m in sys.modules if m.startswith(name)]:
                del sys.modules[mod]

        self.assertIs(registry.get_action_class("SPEC_GOOD_BLOCK").__name__,
                      "Good")
        self.assertGreaterEqual(new, 1)
        self.assertTrue(any("bad_block" in line for line in caught.output),
                        f"the import failure was swallowed: {caught.output}")


class TestEngineBuildPath(RegistryIsolation):
    """REG-13 — the palette is what `ActionEngine.load_stack` builds from.

    `load_stack` does `cls = get_action_class(b["block_id"]); cls(**data)`,
    so every id in the palette must produce a block that really is that
    block. A registry that resolves to the wrong class (duplicate or
    shadow) would silently run a different action than the preset names.
    """

    def test_every_registered_id_builds_its_own_block(self):
        built = {}
        for bid in actions.all_action_ids():
            cls = actions.get_action_class(bid)
            self.assertIsNotNone(cls, f"{bid} resolves to nothing")
            instance = cls()
            self.assertEqual(instance.block_id, bid,
                             f"{bid} built {instance.block_id}")
            built[bid] = cls
        self.assertGreaterEqual(len(built), 15)
        self.assertIs(built["PAUSE"], Pause)

    def test_no_two_ids_share_a_class(self):
        classes = [actions.get_action_class(bid)
                   for bid in actions.all_action_ids()]
        self.assertEqual(len(classes), len(set(classes)),
                         "one class is registered under several ids")


class TestActionContext(unittest.TestCase):
    """REG-12."""

    def test_defaults(self):
        sentinel = object()
        ctx = registry.ActionContext(cdp=sentinel)
        self.assertIs(ctx.cdp, sentinel)
        self.assertIsNone(ctx.memory)
        self.assertIsNone(ctx.criteria)
        self.assertIsNone(ctx.engine)
        self.assertEqual(ctx.user_nick, "")

    def test_every_collaborator_can_be_supplied(self):
        ctx = registry.ActionContext(cdp=None, memory=1, criteria=2,
                                     engine=3, user_nick="Ann")
        self.assertEqual((ctx.memory, ctx.criteria, ctx.engine,
                          ctx.user_nick), (1, 2, 3, "Ann"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
