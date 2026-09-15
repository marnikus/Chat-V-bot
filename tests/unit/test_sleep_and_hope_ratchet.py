"""I-1.3 — a ratchet on tests that wait by sleeping and hoping.

Round H Area C proved the cost of this pattern twice over. In both cases the
production code launched work it did not await, the test slept a few tens of
milliseconds and assumed the work had landed, and the suite's verdict then
depended on how loaded the machine was:

  * `test_patch_lands_in_the_worlds_app_settings` failed **twice in a row** on
    the branch while a pristine-HEAD worktree ran the same suite clean. The
    cause was real — `create_task` with nothing holding the result, which
    CPython may collect before it runs — but it was invisible until allocation
    pressure rose.
  * `test_nick_placeholder.py::test_no_click_user_falls_back_to_the_step_user`
    failed once under `--cov` and has not reproduced since.

`asyncio.sleep(0.05)` is not a synchronisation primitive. It is a guess about
scheduling that happens to be right on an idle machine.

This gate does not try to convert all of them at once. Measured when it was
written: 100 `asyncio.sleep` call sites in `tests/`, of which **64 in 26 files**
are literal waits under 0.2 s — the scheduling guesses. The rest are either
`sleep(0)` (a correct, deterministic yield point) or `sleep(step)` /
`sleep(hold)` against a named interval the product owns, which is the thing
under test rather than a way of waiting for it. What the gate does is **freeze
the 64 per file**, so the count can only go down and every new one has to be
argued for here.

Two kinds of sleep are legitimate and are what the allowlist is for:

  * waiting on a timer the *product* owns (a debounce, a retry backoff, a
    pacing interval) — the sleep is the thing under test;
  * `asyncio.sleep(0)` used as an explicit yield point, which is a correct and
    deterministic way to let already-scheduled callbacks run.

Waiting for an unawaited task to happen to finish is neither. Await the task,
or drain the pending-task set the production code keeps.
"""

from __future__ import annotations

import ast
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TESTS = os.path.join(ROOT, "tests")

#: `asyncio.sleep(N)` with N at or above this is treated as "waiting on a real
#: product timer" and is not counted. Everything below it is a scheduling
#: guess. `sleep(0)` is excluded separately — see `_is_yield_point`.
SHORT_SLEEP = 0.2

#: Measured on 2026-09-14 at the start of Round I — 64 literal short sleeps
#: across 26 files. This is a ceiling per file, not a target: a file may go
#: down, never up. Removing a sleep is always allowed, and
#: `test_the_ceiling_is_not_stale` then forces the number down with it.
#: 2026-09-14 H-B: history_service_lifecycle 3->2 (converted one sleep to
#: yield), area_d_coverage_lift 0->1 (await_with_stop lambda sleep(0.01) is a
#: product timer check, not a scheduling guess, but counted by the scanner).
SHORT_SLEEP_CEILING = {
    "integration/run_safety/test_cleanup_contract.py": 3,
    "integration/run_safety/test_cycle_event_order.py": 1,
    "integration/run_safety/test_stop_contract.py": 6,
    "integration/safety_deletion/test_bridge_results.py": 2,
    "integration/safety_deletion/test_cancel_concurrency.py": 1,
    "integration/services/test_run_state_machine_contract.py": 1,
    "integration/services/test_services_collector_gaps.py": 1,
    "integration/services/test_services_history.py": 4,
    "integration/services/test_services_run.py": 5,
    "integration/services/test_services_undo.py": 3,
    "integration/services/test_services_undo_gaps.py": 2,
    "integration/services/test_undo_support_contract.py": 6,
    "test_action_engine_sequence.py": 1,
    "test_archive_delete_undo.py": 2,
    "test_area_d_coverage_lift.py": 1,
    "test_cdp_events.py": 3,
    "test_collector_state.py": 1,
    "test_db_switch_restart.py": 1,
    "test_history_bridge.py": 2,
    "test_history_service_lifecycle.py": 2,
    "test_live_status_and_order.py": 3,
    "test_people_undo.py": 1,
    "test_user_memory_unit.py": 1,
    "test_world_write_gate.py": 3,
    "unit/actions/test_wait_page_cancellation.py": 6,
    "unit/bridge_safety/helpers.py": 1,
    "unit/bridge_safety/test_boot_race.py": 1,
}


def _sleep_arg(node: ast.Call):
    """The literal passed to `asyncio.sleep`, or None if it is not a literal."""
    if not (isinstance(node.func, ast.Attribute) and node.func.attr == "sleep"):
        return None
    if not (isinstance(node.func.value, ast.Name)
            and node.func.value.id == "asyncio"):
        return None
    if not node.args:
        return None
    try:
        return ast.literal_eval(node.args[0])
    except ValueError:
        return None


def _short_sleeps(path: str) -> list[int]:
    """Line numbers of scheduling-guess sleeps in one test file."""
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        arg = _sleep_arg(node)
        if not isinstance(arg, (int, float)):
            continue            # sleep(step) — a named product interval
        if arg == 0:
            continue            # an explicit yield point, not a guess
        if arg < SHORT_SLEEP:
            out.append(node.lineno)
    return out


def _inventory() -> dict[str, list[int]]:
    found: dict[str, list[int]] = {}
    for dirpath, dirnames, filenames in os.walk(TESTS):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for name in sorted(filenames):
            if not name.endswith(".py"):
                continue
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, TESTS).replace(os.sep, "/")
            hits = _short_sleeps(full)
            if hits:
                found[rel] = hits
    return found


class TestShortSleepRatchet(unittest.TestCase):

    def test_no_file_gained_a_scheduling_guess(self):
        """The per-file count may fall; it may never rise.

        A new short sleep in an existing file, or a short sleep in a file with
        no entry above, fails here. Lower a number when you convert a sleep
        into a real wait — that is the point of the ratchet.
        """
        found = _inventory()
        grew = []
        for rel, lines in sorted(found.items()):
            ceiling = SHORT_SLEEP_CEILING.get(rel, 0)
            if len(lines) > ceiling:
                grew.append(f"{rel}: {len(lines)} short sleep(s) at lines "
                            f"{lines}, ceiling is {ceiling}")
        unlisted = sorted(set(found) - set(SHORT_SLEEP_CEILING))
        self.assertEqual([], grew,
                         "new sleep-and-hope waits:\n" + "\n".join(grew))
        self.assertEqual([], [r for r in unlisted if found[r]],
                         "these files have short sleeps and no ceiling entry")

    def test_the_ceiling_is_not_stale(self):
        """A file that improved must have its ceiling lowered.

        The other failure mode: the ratchet silently stops binding because
        nobody updated it after converting the sleeps. Stale entries are
        deleted, exactly as `CLONE_BASELINE` entries are.
        """
        found = _inventory()
        stale = [rel for rel, ceiling in SHORT_SLEEP_CEILING.items()
                 if len(found.get(rel, [])) < ceiling]
        self.assertEqual([], stale,
                         "these ceilings are above the real count — lower "
                         "them so the ratchet still binds: " + ", ".join(stale))

    def test_the_total_can_only_go_down(self):
        """The whole-suite number, so a file cannot trade with another."""
        found = _inventory()
        self.assertLessEqual(sum(len(v) for v in found.values()),
                             sum(SHORT_SLEEP_CEILING.values()))


if __name__ == "__main__":
    unittest.main()
