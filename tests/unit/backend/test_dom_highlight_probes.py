"""DX# — the HIGHLIGHT and CLEAR probes, executed for real.

`tests/unit/test_find_click_visual.py` drives the FIND/CLICK pair through the Node
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

from backend.probe_requests import (  # noqa: E402
    ClickProbeSpec, FindProbeSpec, HighlightSpec)
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

_JS = {}                            # key -> (results, effects); see fixture
_SPECS = {}                         # key -> builder of (exprs, nodes)


def spec(key):
    """Register one probe payload; the module fixture runs all in ONE spawn."""
    def deco(build):
        _SPECS[key] = build
        return build
    return deco


@pytest.fixture(scope="module", autouse=True)
def _node_batch():
    """W3.2 — one node process per file instead of one per probe payload."""
    builders = list(_SPECS.items())
    payload = json.dumps({"payloads": [
        (lambda built: {"exprs": built[0], "nodes": built[1]})(build())
        for _, build in builders]})
    proc = subprocess.run(["node", str(HARNESS)], input=payload,
                          capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        pytest.skip(f"node harness unavailable: {proc.stderr.strip()[:120]}")
    out = json.loads(proc.stdout)["payloads"]
    for (key, _), pair in zip(builders, out):
        for res in pair["results"]:
            assert "harness_error" not in res, res["harness_error"]
        _JS[key] = (pair["results"], pair["effects"])


def run_js(key):
    """The (results, effects) pair of a registered probe payload."""
    return _JS[key]


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
@spec("highlight_draws")
def _p_highlight_draws():
    return ([build_highlight_probe("user-item", HighlightSpec(".primary-text", "Anna"))],
            page("Anna", "Bela"))


def test_highlight_draws_one_green_overlay_captioned_match():
    (res,), eff = run_js("highlight_draws")
    assert res["found"] is True and res["phase"] == "highlight"
    assert res["highlighted"] is True
    overlays = eff["overlays"][0]
    assert len(overlays) == 1
    assert f"outline:2px solid {COLOR_COLLECT}" in overlay_css(overlays[0])
    assert overlays[0]["caption"] == "MATCH"


@spec("highlight_never_clicks")
def _p_highlight_never_clicks():
    return ([build_highlight_probe("user-item", HighlightSpec(".primary-text", "Anna"))],
            page("Anna"))


def test_highlight_never_clicks_and_never_moves_the_viewport():
    """The scroll parser runs this mid-scroll: a scrollIntoView would corrupt it."""
    (_,), eff = run_js("highlight_never_clicks")
    assert eff["clicks"] == []
    assert eff["scrolled"] == []


@spec("stash_stays_with_find")
def _p_stash_stays_with_find():
    return ([build_find_probe("user-item", FindProbeSpec(".primary-text", "Bela", highlight=False)),
             build_highlight_probe("user-item", HighlightSpec(".primary-text", "Anna")),
             build_click_probe(spec=ClickProbeSpec(highlight=False))],
            page("Anna", "Bela"))


def test_highlight_leaves_the_click_stash_to_the_find_probe():
    """Find → highlight → click: the click must still land on the found node."""
    results, eff = run_js("stash_stays_with_find")
    assert results[0]["text"] == "Bela"
    assert results[2]["clicked"] is True
    # the click went to the node the FIND phase stashed, not the highlighted one
    assert eff["clicks"] == ["user-item"]


@spec("hidden_match")
def _p_hidden_match():
    return ([build_highlight_probe("user-item", HighlightSpec(".primary-text", "Anna"))],
            page("Anna", hidden=(0,)))


def test_hidden_match_is_reported_and_gets_no_overlay():
    (res,), eff = run_js("hidden_match")
    assert res["found"] is True and res["visible"] is False
    assert res["clickable"] is False
    assert eff["overlays"][0] == []


@spec("defaults_exact")
def _p_defaults_exact():
    return ([build_highlight_probe("user-item", HighlightSpec(".primary-text", "Anna"))],
            page("Annabelle", "Anna"))


@spec("defaults_contains")
def _p_defaults_contains():
    return ([build_highlight_probe("user-item", HighlightSpec(".primary-text", "Anna", match_mode=MATCH_CONTAINS))],
            page("Annabelle", "Anna"))


def test_highlight_defaults_to_exact_matching():
    (res,), _ = run_js("defaults_exact")
    assert res["index"] == 1                      # never the longer name
    (res,), _ = run_js("defaults_contains")
    assert res["index"] == 0


@spec("lifetime_321")
def _p_lifetime_321():
    return ([build_highlight_probe("user-item", HighlightSpec(".primary-text", "Anna", highlight_ms=321))],
            page("Anna"))


@spec("lifetime_0")
def _p_lifetime_0():
    return ([build_highlight_probe("user-item", HighlightSpec(".primary-text", "Anna", highlight_ms=0))],
            page("Anna"))


def test_overlay_lifetime_follows_highlight_ms():
    _, eff = run_js("lifetime_321")
    assert eff["timers"] == [321]
    _, eff = run_js("lifetime_0")
    assert eff["timers"] == [1200]                # never an invisible flash


@spec("colour_and_caption")
def _p_colour_and_caption():
    return ([build_highlight_probe("user-item", HighlightSpec(".primary-text", "Anna", color=COLOR_CLICK, caption="STEP 4"))],
            page("Anna"))


def test_colour_and_caption_are_the_callers_to_choose():
    (res,), eff = run_js("colour_and_caption")
    css = overlay_css(eff["overlays"][0][0])
    assert f"outline:2px solid {COLOR_CLICK}" in css
    # the overlay must never eat a click or move the page
    assert "background:transparent" in css and "pointer-events:none" in css
    assert eff["overlays"][0][0]["caption"] == "STEP 4"
    assert res["highlighted"] is True


# ── overlays accumulating or being cleared ──────────────────────────
@spec("clear_first_replaces")
def _p_clear_first_replaces():
    return ([build_highlight_probe("user-item", HighlightSpec(".primary-text", "Anna")),
             build_highlight_probe("user-item", HighlightSpec(".primary-text", "Bela"))],
            page("Anna", "Bela"))


def test_clear_first_replaces_the_previous_overlay():
    _, eff = run_js("clear_first_replaces")
    assert [len(phase) for phase in eff["overlays"]] == [1, 1]


@spec("clear_first_false")
def _p_clear_first_false():
    return ([build_highlight_probe("user-item", HighlightSpec(".primary-text", "Anna", clear_first=False)),
             build_highlight_probe("user-item", HighlightSpec(".primary-text", "Bela", clear_first=False))],
            page("Anna", "Bela"))


def test_clear_first_false_marks_every_match_of_the_pass():
    _, eff = run_js("clear_first_false")
    assert [len(phase) for phase in eff["overlays"]] == [1, 2]


@spec("find_also_clears")
def _p_find_also_clears():
    return ([build_highlight_probe("user-item", HighlightSpec(".primary-text", "Anna", clear_first=False, color=COLOR_COLLECT)),
             build_find_probe("user-item", FindProbeSpec(".primary-text", "Bela", color=COLOR_FIND))],
            page("Anna", "Bela"))


def test_find_probe_also_clears_before_drawing():
    _, eff = run_js("find_also_clears")
    assert len(eff["overlays"][1]) == 1
    assert f"solid {COLOR_FIND}" in overlay_css(eff["overlays"][1][0])


@spec("clear_counts")
def _p_clear_counts():
    return ([build_highlight_probe("user-item", HighlightSpec(".primary-text", "Anna", clear_first=False)),
             build_highlight_probe("user-item", HighlightSpec(".primary-text", "Bela", clear_first=False)),
             build_clear_probe()],
            page("Anna", "Bela"))


def test_clear_probe_removes_exactly_the_overlays_and_says_how_many():
    results, eff = run_js("clear_counts")
    assert len(eff["overlays"][1]) == 2
    assert results[2] == {"cleared": 2}
    assert eff["overlays"][2] == []


@spec("clear_clean_page")
def _p_clear_clean_page():
    return ([build_clear_probe()], page("Anna"))


def test_clear_probe_on_a_clean_page_is_a_silent_success():
    (res,), eff = run_js("clear_clean_page")
    assert res == {"cleared": 0}
    assert eff["clicks"] == [] and eff["overlays"] == [[]]


@spec("clear_only_its_own")
def _p_clear_only_its_own():
    nodes = page("Anna")
    nodes[0]["children"].append({"tag": "div", "className": "cf-highlight",
                                 "text": "keep me", "width": 10, "height": 10})
    return ([build_clear_probe()], nodes)


def test_clear_probe_only_touches_its_own_attribute():
    """A page element that merely looks similar must survive."""
    results, _ = run_js("clear_only_its_own")
    assert results[0] == {"cleared": 0}


@spec("isolation_draws")
def _p_isolation_draws():
    return ([build_highlight_probe("user-item", HighlightSpec(".primary-text", "Anna", clear_first=False))],
            page("Anna"))


@spec("isolation_clear")
def _p_isolation_clear():
    return ([build_clear_probe()], page("Anna"))


def test_batch_payloads_are_isolated_per_fresh_page():
    """The batch must behave like separate processes: no page/effects bleed."""
    _, eff = run_js("isolation_draws")
    assert len(eff["overlays"][0]) == 1
    (res,), _ = run_js("isolation_clear")
    assert res == {"cleared": 0}          # would be 1 if the batch leaked state


def test_the_probe_marks_every_overlay_with_the_shared_attribute():
    """The clear probe's query and the drawing helper share HIGHLIGHT_ATTR."""
    drawn = build_highlight_probe("user-item", HighlightSpec(color=COLOR_COLLECT))
    assert f"'{HIGHLIGHT_ATTR}'" in drawn or f'"{HIGHLIGHT_ATTR}"' in drawn
    assert HIGHLIGHT_ATTR in build_clear_probe()
    assert STASH_KEY in build_find_probe("user-item")
