"""Visual confirmation overlays + two-phase find/click probes.

The "Find & Click" blocks perform their work in TWO separate CDP round trips so
that the user can *see* what happened before anything is clicked:

  Phase 1 — FIND   : locate the element, report success/failure, draw a thin
                     RED outline over it, then pause.
  Phase 2 — CLICK  : re-check the stashed element, report clickability, draw a
                     thin ORANGE outline over the click target, then click.

Both phases return the same structured JSON diagnostic shape used by
``backend.dom_probe`` so the existing logging contract keeps working.

The overlay is a separate ``div`` with ``pointer-events:none`` and a transparent
background, so it can never intercept the click nor affect page layout.
"""

# Round H (H5) RETIRED the `# ideal-size: 527` exemption that stood here — the
# same text H4 retired from config_manager.py, and wrong for the same reason.
# It argued from two shapes only (a package, or a re-export shim) and concluded
# the file could not shrink. The actual content said otherwise: 219 of the 590
# lines were JavaScript SOURCE held in Python strings, touched by 4 of the 16
# definitions and owned by no public symbol at all. Those moved to
# backend/dom_highlight_js.py; the AREA D snapshot did not move.

import json
from dataclasses import dataclass
from typing import Optional

# The marker constants live in the JS module because the JS is what defines
# them as a wire format (it stamps the attribute and stashes the styles); they
# stay importable from HERE because backend/scroll_parser/viewport.py and the
# contract tests already import them from this module.
from backend.dom_highlight_js import (COLOR_CLICK, COLOR_COLLECT, COLOR_FIND,
                                      HIGHLIGHT_ATTR, STASH_KEY, _base_out_js,
                                      _CLICK_BODY,
                                      _FIND_BODY, _HELPERS_JS, _HIGHLIGHT_BODY,
                                      _PROBE_JS)
from backend.dom_probe import MATCH_CONTAINS, MATCH_EXACT, _js_str  # noqa: F401


def _probe(body: str, **fields) -> str:
    """Fill in a probe body, then wrap it in the chassis.

    Two passes, and the order is the point: the body's own ``%(name)s``
    placeholders are resolved first, and the finished script then goes in as a
    *value* of the chassis template. A label that happens to contain a ``%`` —
    "100% done" in a nickname — therefore never has to survive a second
    formatting pass, exactly as it didn't when every builder inlined the
    wrapper and formatted the whole script in one go.
    """
    script = body % fields
    return _PROBE_JS % {"out": _base_out_js(), "helpers": _HELPERS_JS,
                        "body": script.strip("\n")}


@dataclass(frozen=True, slots=True)
class ElementMatch:
    """WHICH element a probe is looking for.

    One CSS selector finds candidate nodes; `label_selector` optionally points
    at a child holding the visible text, and `match_text` is compared against
    it. This is the half of a probe that says *what*, as opposed to `Overlay`
    which says *how it looks*. Both find-style builders take exactly these
    four, which is why they are one value and not eight parameters.
    """

    selector: str
    label_selector: Optional[str] = None
    match_text: Optional[str] = None
    match_mode: str = MATCH_CONTAINS

    def as_js(self) -> dict:
        """The four values as JS literals, ready for a probe template."""
        return {
            "selector": _js_str(self.selector),
            "label_selector": (_js_str(self.label_selector)
                               if self.label_selector else "null"),
            "match_text": (_js_str(self.match_text)
                           if self.match_text else "null"),
            "exact": "true" if self.match_mode == MATCH_EXACT else "false",
        }


@dataclass(frozen=True, slots=True)
class Overlay:
    """HOW the outline drawn on a matched element looks.

    Colour and caption are what the user reads to tell the two phases apart
    (RULE 1: red FOUND, orange CLICK), and `ms` is how long it stays. Each
    builder supplies its own defaults for these — they are the phase's
    identity, not a caller's choice.
    """

    color: str
    caption: str
    ms: int = 1200
    enabled: bool = True

    def as_js(self) -> dict:
        return {
            "color": _js_str(self.color),
            "caption": _js_str(self.caption),
            "hms": int(self.ms),
            "highlight": "true" if self.enabled else "false",
        }


def build_find_probe(
    selector: str,
    label_selector: Optional[str] = None,
    match_text: Optional[str] = None,
    match_mode: str = MATCH_CONTAINS,
    highlight: bool = True,
    highlight_ms: int = 1200,
    color: str = COLOR_FIND,
    caption: str = "FOUND",
    max_candidates: int = 6,
) -> str:
    """Phase 1 probe: find the element, highlight it in RED, do NOT click.

    The matched node is stashed on ``window.__cfStash`` so the click phase can
    act on the exact same element instead of re-querying the DOM.

    The keyword signature stays — `backend/visual_click.py` and the probe
    contract tests call it by name — but the body now builds the two domain
    values, so a new probe style composes them instead of copying nine
    parameters again.
    """
    match = ElementMatch(selector, label_selector, match_text, match_mode)
    overlay = Overlay(color, caption, highlight_ms, highlight)
    return _probe(_FIND_BODY, **match.as_js(), **overlay.as_js(),
                  stash=STASH_KEY, maxcand=int(max_candidates))


def build_click_probe(
    click_selector: Optional[str] = None,
    highlight: bool = True,
    highlight_ms: int = 1200,
    color: str = COLOR_CLICK,
    caption: str = "CLICK",
    do_click: bool = True,
) -> str:
    """Phase 2 probe: highlight the click target in ORANGE, then click it.

    Operates on the element stashed by :func:`build_find_probe`. When
    ``click_selector`` is given, the click target is that element *inside* the
    stashed node; otherwise the stashed node itself is clicked.
    """
    return _probe(_CLICK_BODY,
                  click_selector=_js_str(click_selector) if click_selector else "null",
                  highlight="true" if highlight else "false",
                  do_click="true" if do_click else "false",
                  color=_js_str(color),
                  caption=_js_str(caption),
                  hms=int(highlight_ms),
                  stash=STASH_KEY)


def build_highlight_probe(
    selector: str,
    label_selector: Optional[str] = None,
    match_text: Optional[str] = None,
    match_mode: str = MATCH_EXACT,
    color: str = COLOR_COLLECT,
    caption: str = "MATCH",
    highlight_ms: int = 900,
    clear_first: bool = True,
) -> str:
    """Highlight an element WITHOUT clicking it or touching the click stash.

    Used for pure visual confirmation — e.g. showing which person just matched
    the filter during Scroll & Parse. Deliberately does NOT call
    ``scrollIntoView``: moving the viewport mid-scroll would corrupt the
    parser's position tracking.
    """
    match = ElementMatch(selector, label_selector, match_text, match_mode)
    overlay = Overlay(color, caption, highlight_ms)
    js = {**match.as_js(), **overlay.as_js()}
    js.pop("highlight")        # this probe ONLY highlights; there is no toggle
    return _probe(_HIGHLIGHT_BODY, **js,
                  clear="true" if clear_first else "false")


def build_clear_probe() -> str:
    """Remove every leftover highlight overlay from the page."""
    return """
(function(){
  try {
    var old = document.querySelectorAll('[%(attr)s]');
    for (var k = 0; k < old.length; k++) {
      if (old[k].parentNode) old[k].parentNode.removeChild(old[k]);
    }
    return JSON.stringify({cleared: old.length});
  } catch (err) { return JSON.stringify({cleared: 0}); }
})()
""" % {"attr": HIGHLIGHT_ATTR}


# ── interpretation of the two phases ─────────────────────────────────────
def _candidate_lines(result: dict) -> str:
    """What the probe DID see, as one readable line — or an empty string.

    A miss is far more useful with the near-misses under it: that is how a user
    tells "wrong selector" from "right node, wrong text" without opening the
    debugger pane.
    """
    cands = result.get("candidates") or []
    if not cands:
        return ""
    parts = [
        f"[{c.get('index')}] “{str(c.get('text', ''))[:40]}” "
        f"({'visible' if c.get('visible') else 'hidden'}, "
        f"{'clickable' if c.get('clickable') else 'not clickable'})"
        for c in cands[:4]
    ]
    return " Candidates: " + "; ".join(parts) + "."


def interpret_find(result, label: str = "element") -> tuple[str, str]:
    """Turn a FIND-phase result into a (message, level) pair."""
    if not result:
        return f"❌ FIND failed: no data returned for {label} " \
               "(page context unavailable?)", "error"
    if result.get("error"):
        return f"❌ FIND error while searching {label}: {result['error']}", "error"
    total = int(result.get("total", 0) or 0)
    if not result.get("found"):
        return (f"❌ FIND failed: {label} — selector matched {total} node(s), "
                "none with the required text/properties."
                + _candidate_lines(result)), "error"
    text = str(result.get("text", ""))[:60]
    idx = result.get("index", -1)
    msg = (f"✅ FIND success: {label} — matched node #{idx} “{text}” "
           f"({_found_state(result)})" + _outline_suffix(result))
    return msg, ("success" if result.get("visible") else "warn")


def _found_state(result: dict) -> str:
    """The visibility / disabled description of the matched node."""
    state = ("visible" if result.get("visible")
             else "⚠ NOT visible (hidden/zero-size)")
    if result.get("disabled"):
        state += ", ⚠ disabled (or pointer-events:none)"
    return state


def _outline_suffix(result: dict) -> str:
    """The 🟥-outline / highlight-off tail of a FIND success message.

    An invisible element is never reported as "highlight off": nothing was
    drawn and the level already says warn.
    """
    if result.get("highlighted"):
        rect = result.get("rect") or {}
        if not rect:
            return " — 🟥 red outline drawn"
        return (f" — 🟥 red outline drawn at {int(rect.get('x', 0))},"
                f"{int(rect.get('y', 0))} {int(rect.get('width', 0))}"
                f"×{int(rect.get('height', 0))}px")
    if result.get("visible"):
        return " — (highlight off)"
    return ""


def _unclickable_reason(result) -> str:
    """Why the probe refused to click, in the user's words.

    Both causes can hold at once and both are reported — "not visible" alone
    would send someone hunting for a CSS issue when the control is also
    disabled.
    """
    why = []
    if not result.get("visible"):
        why.append("not visible (hidden/zero-size)")
    if result.get("disabled"):
        why.append("disabled or pointer-events:none")
    return ", ".join(why) or "not interactive"


def interpret_click(result, label: str = "element") -> tuple[str, str]:
    """Turn a CLICK-phase result into a (message, level) pair."""
    if not result:
        return f"❌ CLICK failed: no data returned for {label}", "error"
    if result.get("error") and not result.get("clicked"):
        return f"❌ CLICK failed: {label} — {result['error']}", "error"
    target = result.get("target_desc") or "the found element"
    if not result.get("clickable"):
        return (f"❌ CLICK failed: {target} is NOT clickable "
                f"— {_unclickable_reason(result)}", "error")
    if result.get("clicked"):
        return (f"✅ CLICK success: clicked {target} “"
                f"{str(result.get('text', ''))[:40]}”", "success")
    return (f"⚠ CLICK not dispatched: {target} is clickable but no click was "
            "performed", "warn")


def interpret_click_target(result) -> tuple[str, str]:
    """Message emitted right after the orange outline, before the click."""
    if not isinstance(result, dict):
        return "⚠ CLICK target unknown — no data returned", "warn"
    target = result.get("target_desc") or "the found element"
    if result.get("clickable"):
        msg = f"✅ CLICK target is clickable: {target}"
        if result.get("highlighted"):
            msg += " — 🟧 orange outline drawn"
        return msg, "success"
    return f"⚠ CLICK target {target} is not clickable", "warn"
