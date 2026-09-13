"""Virtual scroll parser: scroll → detect new persons → filter → collect.

The list is lazy-loaded through an Angular CDK virtual-scroll viewport, so a
slow response looks exactly like the end of the list. This parser therefore
distinguishes the two explicitly:

  * after each scroll it *settles* — polling until either new people appear
    (lazy load finished) or the scroll position stops changing;
  * the end of the list is only declared when the viewport is geometrically at
    the bottom AND a further settle window produced nothing new.

Every decision is reported through the log callback so the run is observable.

The class was split by single responsibility (one mixin per phase) — see
`docs/archive/2026-09-12-god-classes/STEP3_SCROLL_PARSER_DESIGN_2026-09-12.md`.
This `__init__` re-exports the frozen seam other areas import verbatim, plus
the `asyncio` module so `tests/test_collect_visual_and_live_refresh.py`'s
``import backend.scroll_parser as sp; sp.asyncio.sleep = spy`` patch keeps
landing on the one module every phase sleeps through.
"""

import asyncio

from .options import ScrollOptions
from .parser import ScrollParser
from .result import CollectResult

__all__ = [
    "CollectResult",
    "ScrollOptions",
    "ScrollParser",
    "asyncio",
]
