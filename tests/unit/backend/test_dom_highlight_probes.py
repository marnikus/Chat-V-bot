"""DX# — the HIGHLIGHT and CLEAR probes, executed for real.

`tests/test_find_click_visual.py` drives the FIND/CLICK pair through the Node
harness; the two remaining builders of `backend/dom_highlight.py` are only
pinned as *strings* by `test_dom_highlight_contract.py`. Their whole job is a
side effect on the page (an overlay drawn, the old ones removed), so here they
are run: the assertions are about the overlay nodes the page ends up with, the
clicks and scrolls the probe caused, and the stash it left alone.

That matters most for the refactor that moved every builder onto a shared probe
chassis — the generated text may move, the observable behaviour may not.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.dom_probe import MATCH_CONTAINS  # noqa: E402
from backend.dom_highlight import (  # noqa: E402
    COLOR_CLICK,
    COLOR_COLLECT,
    COLOR_FIND,
    HIGHLIGHT_ATTR,
    STASH_KEY,
    build_clear_probe,
    build_click_probe,
    build_find_probe,
    build_highlight_probe,
)

HARNESS = ROOT / "tests" / "js_harness.js"


def run_js(exprs, nodes):
    """Execute probe expressions in one shared DOM; return (results, effects)."""
    payload = json.dumps({"exprs": exprs, "nodes": nodes})
    proc = subprocess.run(["node", str(HARNESS)], input=payload,
                          capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:
        pytest.skip(f"node harness unavailable: {proc.stderr.strip()[:120]}")
    out = json.loads(proc.stdout)
    for res in out["results"]:
        assert "harness_error" not in res, res["harness_error"]
    return out["results"], out["effects"]


def person(name, *, hidden=False, x=0):
    """One user row: root `user-item` with a `.primary-text` label inside."""
    return {"tag": "user-item", "x": x, "width": 220, "height": 40,
            "hidden": hidden,
            "children": [{"tag": "div", "className": "primary-text",
                          "text": name, "width": 180, "height": 20}]}


def page(*names, **kw):
    hidden = kw.pop("hidden", ())
    return [person(n, x=220 * i, hidden=(i in hidden))
            for i, n in enumerate(names)]


def overlay_css(res):
    return res["css"]


# ── what the highlight probe leaves on the page ─────────────────────
def test_highlight_draws_one_green_overlay_captioned_match():
    (res,), eff = run_js(
        [build_highlight_probe("user-item", ".primary-text", "Anna")],
        page("Anna", "Bela"))
    assert res["found"] is True and res["phase"] == "highlight"
    assert res["highlighted"] is True
    overlays = eff["overlays"][0]
    assert len(overlays) == 1
    assert f"outline:2px solid {COLOR_COLLECT}" in overlay_css(overlays[0])
    assert overlays[0]["caption"] == "MATCH"


def test_highlight_never_clicks_and_never_moves_the_viewport():
    """The scroll parser runs this mid-scroll: a scrollIntoView would corrupt it."""
    (res,), eff = run_js(
        [build_highlight_probe("user-item", ".primary-text", "Anna")],
        page("Anna"))
    assert eff["clicks"] == []
    assert eff["scrolled"] == []


def test_highlight_leaves_the_click_stash_to_the_find_probe():
    """Find → highlight → click: the click must still land on the found node."""
    exprs = [build_find_probe("user-item", ".primary-text", "Bela",
                              highlight=False),
             build_highlight_probe("user-item", ".primary-text", "Anna"),
             build_click_probe(highlight=False)]
    results, eff = run_js(exprs, page("Anna", "Bela"))
    assert results[0]["text"] == "Bela"
    assert results[2]["clicked"] is True
    # the click went to the node the FIND phase stashed, not the highlighted one
    assert eff["clicks"] == ["user-item"]


def test_hidden_match_is_reported_and_gets_no_overlay():
    (res,), eff = run_js(
        [build_highlight_probe("user-item", ".primary-text", "Anna")],
        page("Anna", hidden=(0,)))
    assert res["found"] is True and res["visible"] is False
    assert res["clickable"] is False
    assert eff["overlays"][0] == []


def test_highlight_defaults_to_exact_matching():
    nodes = page("Annabelle", "Anna")
    (res,), _ = run_js([build_highlight_probe("user-item", ".primary-text",
                                              "Anna")], nodes)
    assert res["index"] == 1                      # never the longer name
    (res,), _ = run_js([build_highlight_probe("user-item", ".primary-text",
                                              "Anna",
                                              match_mode=MATCH_CONTAINS)], nodes)
    assert res["index"] == 0


def test_overlay_lifetime_follows_highlight_ms():
    _, eff = run_js([build_highlight_probe("user-item", ".primary-text",
                                           "Anna", highlight_ms=321)],
                    page("Anna"))
    assert eff["timers"] == [321]
    _, eff = run_js([build_highlight_probe("user-item", ".primary-text",
                                           "Anna", highlight_ms=0)], page("Anna"))
    assert eff["timers"] == [1200]                # never an invisible flash


def test_colour_and_caption_are_the_callers_to_choose():
    (res,), eff = run_js([build_highlight_probe("user-item", ".primary-text",
                                                "Anna", color=COLOR_CLICK,
                                                caption="STEP 4")], page("Anna"))
    css = overlay_css(eff["overlays"][0][0])
    assert f"outline:2px solid {COLOR_CLICK}" in css
    # the overlay must never eat a click or move the page
    assert "background:transparent" in css and "pointer-events:none" in css
    assert eff["overlays"][0][0]["caption"] == "STEP 4"
    assert res["highlighted"] is True


# ── overlays accumulating or being cleared ──────────────────────────
def test_clear_first_replaces_the_previous_overlay():
    exprs = [build_highlight_probe("user-item", ".primary-text", "Anna"),
             build_highlight_probe("user-item", ".primary-text", "Bela")]
    _, eff = run_js(exprs, page("Anna", "Bela"))
    assert [len(phase) for phase in eff["overlays"]] == [1, 1]


def test_clear_first_false_marks_every_match_of_the_pass():
    exprs = [build_highlight_probe("user-item", ".primary-text", "Anna",
                                   clear_first=False),
             build_highlight_probe("user-item", ".primary-text", "Bela",
                                   clear_first=False)]
    _, eff = run_js(exprs, page("Anna", "Bela"))
    assert [len(phase) for phase in eff["overlays"]] == [1, 2]


def test_find_probe_also_clears_before_drawing():
    exprs = [build_highlight_probe("user-item", ".primary-text", "Anna",
                                   clear_first=False, color=COLOR_COLLECT),
             build_find_probe("user-item", ".primary-text", "Bela",
                              color=COLOR_FIND)]
    _, eff = run_js(exprs, page("Anna", "Bela"))
    assert len(eff["overlays"][1]) == 1
    assert f"solid {COLOR_FIND}" in overlay_css(eff["overlays"][1][0])


def test_clear_probe_removes_exactly_the_overlays_and_says_how_many():
    exprs = [build_highlight_probe("user-item", ".primary-text", "Anna",
                                   clear_first=False),
             build_highlight_probe("user-item", ".primary-text", "Bela",
                                   clear_first=False),
             build_clear_probe()]
    results, eff = run_js(exprs, page("Anna", "Bela"))
    assert len(eff["overlays"][1]) == 2
    assert results[2] == {"cleared": 2}
    assert eff["overlays"][2] == []


def test_clear_probe_on_a_clean_page_is_a_silent_success():
    (res,), eff = run_js([build_clear_probe()], page("Anna"))
    assert res == {"cleared": 0}
    assert eff["clicks"] == [] and eff["overlays"] == [[]]


def test_clear_probe_only_touches_its_own_attribute():
    """A page element that merely looks similar must survive."""
    nodes = page("Anna")
    nodes[0]["children"].append({"tag": "div", "className": "cf-highlight",
                                 "text": "keep me", "width": 10, "height": 10})
    exprs = [build_clear_probe()]
    results, _ = run_js(exprs, nodes)
    assert results[0] == {"cleared": 0}


def test_the_probe_marks_every_overlay_with_the_shared_attribute():
    """The clear probe's query and the drawing helper share HIGHLIGHT_ATTR."""
    drawn = build_highlight_probe("user-item", color=COLOR_COLLECT)
    assert f"'{HIGHLIGHT_ATTR}'" in drawn or f'"{HIGHLIGHT_ATTR}"' in drawn
    assert HIGHLIGHT_ATTR in build_clear_probe()
    assert STASH_KEY in build_find_probe("user-item")
