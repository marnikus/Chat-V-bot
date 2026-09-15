"""The vocabulary of the DOM probes: match modes, colours, knob bundles.

Leaf module of the probe family (`dom_probe` builds the plain probe,
`dom_highlight` the highlight/find/click phases, `visual_click` runs them).
The constants moved here from those two modules — both re-export them, so
every existing import site is unchanged — because the spec dataclasses
below carry them as defaults and a dataclass module cannot import from its
consumers (Round G step 4 design §1b wave 2: builder signatures drop to
selector + one spec, RULE 16 width).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# Match modes for the (optional) text comparison
MATCH_CONTAINS = "contains"
MATCH_EXACT = "exact"

#: Outline colour used for the FIND phase.
COLOR_FIND = "#ff2d2d"      # red
#: Outline colour used for the CLICK phase.
COLOR_CLICK = "#ff9500"     # orange
#: Outline colour used when a person matches the filter and is collected.
COLOR_COLLECT = "#00c853"   # green


@dataclass(frozen=True, slots=True)
class ProbeSpec:
    """The knobs of one plain `build_probe()` call."""

    #: optional child CSS selector whose text is used for the label / text
    #: match (falls back to the node itself).
    label_selector: Optional[str] = None
    #: if set, only elements whose label contains (or exactly equals) this
    #: text are considered matches.
    match_text: Optional[str] = None
    match_mode: str = MATCH_CONTAINS
    #: click the resolved click target when a match is found and clickable.
    click: bool = False
    #: optional child CSS selector used as the click target.
    click_selector: Optional[str] = None
    #: click the root matched node instead of the label element.
    click_root: bool = False
    #: how many candidate rows to include in the result.
    max_candidates: int = 6


@dataclass(frozen=True, slots=True)
class FindProbeSpec:
    """The knobs of one phase-1 `build_find_probe()` call (RED, no click)."""

    label_selector: Optional[str] = None
    match_text: Optional[str] = None
    match_mode: str = MATCH_CONTAINS
    highlight: bool = True
    highlight_ms: int = 1200
    color: str = COLOR_FIND
    caption: str = "FOUND"
    max_candidates: int = 6


@dataclass(frozen=True, slots=True)
class ClickProbeSpec:
    """The knobs of one phase-2 `build_click_probe()` call (ORANGE, click)."""

    highlight: bool = True
    highlight_ms: int = 1200
    color: str = COLOR_CLICK
    caption: str = "CLICK"
    do_click: bool = True


@dataclass(frozen=True, slots=True)
class HighlightSpec:
    """The knobs of one `build_highlight_probe()` call (no click, no stash)."""

    label_selector: Optional[str] = None
    match_text: Optional[str] = None
    match_mode: str = MATCH_EXACT
    color: str = COLOR_COLLECT
    caption: str = "MATCH"
    highlight_ms: int = 900
    clear_first: bool = True
