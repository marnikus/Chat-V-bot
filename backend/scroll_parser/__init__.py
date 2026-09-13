"""Virtual scroll parser: scroll → detect new persons → filter → collect.

The list is lazy-loaded through an Angular CDK virtual-scroll viewport, so a
slow response looks exactly like the end of the list. This package therefore
distinguishes the two explicitly:

  * after each scroll it *settles* — polling until either new people appear
    (lazy load finished) or the scroll position stops changing;
  * the end of the list is only declared when the viewport is geometrically at
    the bottom AND a further settle window produced nothing new.

Every decision is reported through the log callback so the run is observable.

## What each module owns, and which way the imports go

| Module | Owns | Imports from this package |
|---|---|---|
| `probe.py` | the `_EXTRACT_JS` payload, `STOPPED`, the pure item mappers | — |
| `options.py` | `ScrollOptions` — the 17 knobs, immutable | — |
| `results.py` | `CollectResult`, `_Pass` — pure run state | `options` |
| `viewport.py` | `Viewport` — the ONLY caller of `cdp.*`: probe, scroll, settle | `probe` |
| `judge.py` | `Judge` — seek / reject / collect verdicts per person | `probe` |
| `loop.py` | `ScrollLoop` — pass sequencing, end-of-list, stop checks | `probe` |
| `parser.py` | `ScrollParser` — the public class and the shared state | all of the above |

Imports only ever point *down* that table. The three collaborators reach the
parser back through a host protocol (`host.options`, `host._say()`,
`host.known_nicks`, `host.viewport`, `host.judge`) — the same shape
`services/collector_*` uses — so none of them imports `parser.py` and there is
no cycle.

## Why this is a package (Round G, step G2)

It was one 706-line module at maintainability index 28.6, whose `ScrollParser`
class was 532 LOC across 39 methods with LCOM 0.88 — the largest genuine god
class in the repository and a §16.5 landmine. It could not be split until step
G0 taught the AREA D snapshot to walk into packages and to treat a symbol
defined in a submodule as still owned by the package. Design and the empty-diff
proof: `docs/archive/2026-09-13-round-g/AREA_D_DECISION_2026-09-13.md` and
`SCROLL_PARSER_SPLIT_2026-09-13.md`.

**The rule that keeps the contract:** this `__init__` re-exports the module's
previous public surface verbatim. Split the file, keep the front door.
"""

from backend.scroll_parser.judge import Judge
from backend.scroll_parser.loop import ScrollLoop
from backend.scroll_parser.options import ScrollOptions
from backend.scroll_parser.parser import ScrollParser
from backend.scroll_parser.probe import STOPPED
from backend.scroll_parser.results import CollectResult
from backend.scroll_parser.viewport import Viewport

__all__ = [
    "STOPPED", "CollectResult", "Judge", "ScrollLoop", "ScrollOptions",
    "ScrollParser", "Viewport",
]
