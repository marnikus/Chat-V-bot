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

# ideal-size: the builders and the two interpreters; the five JS payloads and
# their shared fragments live in backend/dom_highlight_js.py (Round J step
# J-4), which carries the note for the literals it hosts.

import json
from typing import Optional

from backend import dom_highlight_js as js
from backend.dom_highlight_js import (                     # noqa: F401
    HIGHLIGHT_ATTR, STASH_KEY,
)
from backend.dom_probe import MATCH_EXACT, _js_str
from backend.probe_requests import (  # noqa: F401  (re-exported: constants moved)
    COLOR_CLICK, COLOR_COLLECT, COLOR_FIND, ClickProbeSpec, FindProbeSpec,
    HighlightSpec)

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
    return js.PROBE_CHASSIS_JS % {"out": js.base_out_js(),
                                  "helpers": js.HELPERS_JS,
                                  "body": script.strip("\n")}


def build_find_probe(selector: str,
                     spec: Optional[FindProbeSpec] = None) -> str:
    """Phase 1 probe: find the element, highlight it in RED, do NOT click.

    The matched node is stashed on ``window.__cfStash`` so the click phase can
    act on the exact same element instead of re-querying the DOM. The knobs
    travel as one :class:`FindProbeSpec`; None means the RED-outline defaults.
    """
    spec = spec or FindProbeSpec()
    return _probe(js.FIND_BODY,
                  selector=_js_str(selector),
                  label_selector=(_js_str(spec.label_selector)
                                  if spec.label_selector else "null"),
                  match_text=(_js_str(spec.match_text) if spec.match_text
                              else "null"),
                  exact="true" if spec.match_mode == MATCH_EXACT else "false",
                  highlight="true" if spec.highlight else "false",
                  color=_js_str(spec.color),
                  caption=_js_str(spec.caption),
                  hms=int(spec.highlight_ms),
                  stash=STASH_KEY,
                  maxcand=int(spec.max_candidates))


def build_click_probe(click_selector: Optional[str] = None,
                      spec: Optional[ClickProbeSpec] = None) -> str:
    """Phase 2 probe: highlight the click target in ORANGE, then click it.

    Operates on the element stashed by :func:`build_find_probe`. When
    ``click_selector`` is given, the click target is that element *inside* the
    stashed node; otherwise the stashed node itself is clicked. The knobs
    travel as one :class:`ClickProbeSpec`.
    """
    spec = spec or ClickProbeSpec()
    return _probe(js.CLICK_BODY,
                  click_selector=(_js_str(click_selector) if click_selector
                                  else "null"),
                  highlight="true" if spec.highlight else "false",
                  do_click="true" if spec.do_click else "false",
                  color=_js_str(spec.color),
                  caption=_js_str(spec.caption),
                  hms=int(spec.highlight_ms),
                  stash=STASH_KEY)


def build_highlight_probe(selector: str,
                          spec: Optional[HighlightSpec] = None) -> str:
    """Highlight an element WITHOUT clicking it or touching the click stash.

    Used for pure visual confirmation — e.g. showing which person just matched
    the filter during Scroll & Parse. Deliberately does NOT call
    ``scrollIntoView``: moving the viewport mid-scroll would corrupt the
    parser's position tracking. The knobs travel as one
    :class:`HighlightSpec`; None means the GREEN "MATCH" defaults.
    """
    spec = spec or HighlightSpec()
    return _probe(js.HIGHLIGHT_BODY,
                  selector=_js_str(selector),
                  label_selector=(_js_str(spec.label_selector)
                                  if spec.label_selector else "null"),
                  match_text=(_js_str(spec.match_text) if spec.match_text
                              else "null"),
                  exact="true" if spec.match_mode == MATCH_EXACT else "false",
                  clear="true" if spec.clear_first else "false",
                  color=_js_str(spec.color),
                  caption=_js_str(spec.caption),
                  hms=int(spec.highlight_ms))


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


def interpret_click(result, label: str = "element") -> tuple[str, str]:
    """Turn a CLICK-phase result into a (message, level) pair."""
    if not result:
        return f"❌ CLICK failed: no data returned for {label}", "error"
    if result.get("error") and not result.get("clicked"):
        return f"❌ CLICK failed: {label} — {result['error']}", "error"
    target = result.get("target_desc") or "the found element"
    if not result.get("clickable"):
        why = []
        if not result.get("visible"):
            why.append("not visible (hidden/zero-size)")
        if result.get("disabled"):
            why.append("disabled or pointer-events:none")
        reason = ", ".join(why) or "not interactive"
        return (f"❌ CLICK failed: {target} is NOT clickable — {reason}", "error")
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
