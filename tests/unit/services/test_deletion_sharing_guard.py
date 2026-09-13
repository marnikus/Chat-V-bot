"""`_reject_new_sharing` — the mid-deletion media-reference guard.

Round G, step G6. This guard had NO test, and under that cover it had stopped
working: `raise_refusal` signals by raising `_PhaseRefusal`, which subclasses
`Exception`, and the call sat inside a `try:` whose `except Exception: pass`
caught it one frame later. The guard computed the right answer, raised the
right refusal, and then swallowed it — a deletion that should have been refused
proceeded, which is data loss.

The guard's whole job is to notice that *while we were deleting*, some other
world started referencing a file we are about to remove. These tests pin the
refusal, the two ways a reference can match, the fail-safe on an unresolvable
reference, and the quiet path when nothing new appeared.
"""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")))

# Round H (H2) split the pipeline at its irreversible boundary. This guard is
# a pre-boundary phase, so it moved to `db_deletion_pre`; the shared state and
# refusal types stayed in `db_deletion_state`. The test follows the code to the
# module that OWNS each name rather than patching a re-export -- monkeypatching
# a name on a package that merely re-exports it does nothing to the call site.
from services import db_deletion_pre as flow  # noqa: E402
from services import db_deletion_state as state  # noqa: E402


def _state(candidates, keep_snapshot=()):
    return state._DeleteState(
        path="/w/victim.db",
        registry=SimpleNamespace(active_path=lambda: None),
        target="/w/victim.db",
        plan=SimpleNamespace(candidates=frozenset(candidates)),
        keep_snapshot=frozenset(keep_snapshot),
    )


class TestRejectNewSharing(unittest.TestCase):

    def test_a_new_reference_to_a_doomed_file_refuses_the_deletion(self):
        """The regression. A reference that appeared mid-run and points at a
        deletion candidate must abort the run, not be swallowed."""
        doomed = os.path.abspath("/w/media/pic.jpg")
        st = _state(candidates=[doomed], keep_snapshot=[])

        with self.assertRaises(state._PhaseRefusal) as caught:
            flow._reject_new_sharing(st, [doomed])

        self.assertIn("media references changed",
                      caught.exception.outcome["error"])
        self.assertFalse(caught.exception.outcome["ok"])

    def test_a_reference_already_present_before_the_run_is_not_new(self):
        """keep_snapshot is the 'before' picture: anything in it was already
        shared when we planned, and the plan accounted for it."""
        known = os.path.abspath("/w/media/pic.jpg")
        st = _state(candidates=[known], keep_snapshot=[known])
        flow._reject_new_sharing(st, [known])      # must not raise

    def test_a_new_reference_to_an_unrelated_file_is_ignored(self):
        st = _state(candidates=[os.path.abspath("/w/media/pic.jpg")])
        flow._reject_new_sharing(st, [os.path.abspath("/other/thing.jpg")])

    def test_nothing_new_at_all_is_a_no_op(self):
        st = _state(candidates=[os.path.abspath("/w/media/pic.jpg")])
        flow._reject_new_sharing(st, [])

    def test_a_reference_matching_only_after_canonicalisation_still_refuses(self):
        """Two spellings of one path (symlink, case, ..) must not slip past —
        the guard compares canonical forms as well as absolute ones."""
        doomed = os.path.abspath("/w/media/pic.jpg")
        st = _state(candidates=[doomed])
        with mock.patch.object(flow.db_deletion, "canonical",
                               side_effect=lambda p: doomed):
            with self.assertRaises(state._PhaseRefusal):
                flow._reject_new_sharing(st, ["/w/./media/../media/pic.jpg"])

    def test_an_unresolvable_reference_is_treated_as_dangerous(self):
        """Fail safe: if we cannot tell what a reference points at, we refuse
        rather than delete. `_dangerous_refs` is exercised directly because the
        failure has to happen per-reference, inside the loop."""
        def boom(path):
            if path == "??":
                raise OSError("cannot resolve")
            return os.path.abspath(path)

        with mock.patch.object(flow.db_deletion, "canonical",
                               side_effect=boom):
            dangerous = flow._dangerous_refs({"??"}, ["/w/media/pic.jpg"])
        self.assertEqual(dangerous, {"??"})

    def test_a_broken_candidate_set_does_not_abort_the_deletion(self):
        """If the guard itself cannot run, the deletion continues — that was
        the original intent of the outer try, and it is preserved. Only the
        refusal is no longer caught by it."""
        st = _state(candidates=[])
        st.plan = SimpleNamespace(candidates=object())   # not iterable
        flow._reject_new_sharing(st, ["/w/media/pic.jpg"])   # must not raise


if __name__ == "__main__":
    unittest.main()
