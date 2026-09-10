"""Block-execution outcomes — the one shared vocabulary.

Home: `core/` (moved from `actions/base.py` by INTEGRATION-01/I7).
`backend/visual_click.py` needs these constants, and importing them from
`actions.*` was a genuine import cycle (`backend.visual_click` ⇄
`actions/__init__.scan()`): whichever side the interpreter read first,
the other half was still partially initialised. A three-constant leaf
belongs at the bottom layer, where every package can reach it downward.

`actions.base` and `actions.base_action` re-export this same object, so
every historical import path keeps working with identical identity.
"""

from __future__ import annotations


class ActionResult:
    OK = "ok"
    FAIL = "fail"
    SKIP = "skip"
