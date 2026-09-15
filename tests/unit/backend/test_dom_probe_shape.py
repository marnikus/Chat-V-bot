"""I-2 — the generated DOM probe is pinned byte-for-byte.

Round I step I-2 split `backend/dom_probe.py::build_probe` from a single
107-LOC function carrying one string into three named script fragments
(`_PROBE_HEAD`, `_PROBE_VISIBILITY`, `_PROBE_SCAN`) plus `_click_block`, and
`build_probe` became their composition at 25 LOC.

That refactor was only safe because the emitted JavaScript did not change — so
this file pins it. The digests below were captured from the **un-split**
function across the eight knob combinations `ProbeSpec` actually allows, and
the split was verified byte-identical against them before this test existed.

A digest is used rather than a golden literal because each probe is ~2.2 KB of
JavaScript; eight of them inline would bury the assertion. On mismatch the
message says which case moved, and `build_probe` is cheap to call, so the
failing string is one line away.
"""

from __future__ import annotations

import hashlib
import unittest

from backend.dom_probe import (MATCH_CONTAINS, MATCH_EXACT, ProbeSpec,
                               build_probe)

#: sha256 of the exact JavaScript each knob combination must still generate.
GOLDEN_SHA256 = {
    "plain": "6b2e7ccebb19ccd4dc32d6820aff7666b601f842436643f93647ac099fd91fdf",
    "label_child": "ae8d3b8c7886468746f91e775b2e98670eea8a7b2096d1c9197750ea2d791885",
    "contains": "591f0943f16f305e89e964e1170387c03be9817848e5e4b558f43a7640f18ebd",
    "exact": "0448105129b037f7abd77ee7fc8d1ef80682fa5a505e3c5588dbba34cee91d0b",
    "click_el": "c00cb5b73e6fe985278355ddb0d5a28e9975b8b66e7b628b11ada1bd7c9db66d",
    "click_root": "f5c9fe71ff7c3f969f0b5467603565586db9a20e61562cd59b351664ddb57439",
    "click_child": "8d77226740834d439bfa80e9bd7387d0e62c5beb32676e1d0d39b31a21d45a02",
    "everything": "e7d003229295b13cae10bb0567cc34dc42d96359ca84276648034b1908a6c8fd",
}

#: selector + ProbeSpec kwargs per case. `None` means "no spec at all", which
#: is the plain visibility probe every caller gets by default.
CASES = {
    "plain": ("div.row", None),
    "label_child": ("li.u", dict(label_selector="span.name", max_candidates=9)),
    "contains": ("li.u", dict(match_text="Ann", match_mode=MATCH_CONTAINS)),
    "exact": ("li.u", dict(match_text="Ann", match_mode=MATCH_EXACT)),
    "click_el": ("li.u", dict(click=True)),
    "click_root": ("li.u", dict(click=True, click_root=True)),
    "click_child": ("li.u", dict(click=True, click_selector="button.go")),
    "everything": ("a[href]", dict(label_selector=".n", match_text="x",
                                   match_mode=MATCH_EXACT, click=True,
                                   click_selector="i.ic", max_candidates=3)),
}


def _probe(case: str) -> str:
    selector, spec = CASES[case]
    return build_probe(selector, ProbeSpec(**spec) if spec else None)


class TestProbeShapeIsPinned(unittest.TestCase):

    def test_every_knob_combination_emits_the_pinned_javascript(self):
        for case, digest in sorted(GOLDEN_SHA256.items()):
            with self.subTest(case=case):
                got = hashlib.sha256(_probe(case).encode()).hexdigest()
                self.assertEqual(
                    digest, got,
                    f"{case}: the generated probe changed. If the change is "
                    f"intended, re-capture this digest from build_probe(); if "
                    f"not, the split moved JavaScript it should not have.")

    def test_the_pinned_cases_cover_every_documented_knob(self):
        """Guard the guard: a knob with no case is a knob with no pin."""
        self.assertEqual(set(GOLDEN_SHA256), set(CASES))
        seen = {k for _, spec in CASES.values() if spec for k in spec}
        for field in ("label_selector", "match_text", "match_mode", "click",
                      "click_root", "click_selector", "max_candidates"):
            self.assertIn(field, seen, f"no pinned case exercises {field}")

    def test_clicking_only_changes_the_click_block(self):
        """The click fragment is additive; nothing else may move."""
        plain = _probe("plain")
        clicked = _probe("click_el")
        self.assertNotIn("target.click()", plain)
        self.assertIn("target.click()", clicked)
        for needle in ("function probeVisible(el)", "var sel =",
                       "return JSON.stringify(out);"):
            self.assertIn(needle, clicked)


if __name__ == "__main__":
    unittest.main()
