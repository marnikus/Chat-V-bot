"""The label vocabulary: the palette, the ids and the normalising reads.

Extracted from `stores/label_store.py` by the AREA B2 split (design §2.5).
These four functions and four constants are shared by every half of the label
store (state, world sync, assignments, filter) and by the bridges: pure text
and colour rules with no state, which is exactly what belongs in a leaf module.
`stores/label_store.py` re-exports all of them because `backend/label_store.py`
(a frozen shim) and the tests import `PALETTE`, `DEFAULT_COLOR`, `MAX_NAME`,
`normalize_color` and `FILTER_KEY` from there.
"""

from __future__ import annotations

import re

#: The 20 bright presets the Color Picker offers (5 × 4 grid, row major).
PALETTE = [
    "#ff3b30", "#ff9500", "#ffcc00", "#a3e635", "#34c759",
    "#14b8a6", "#22d3ee", "#38bdf8", "#0a84ff", "#5856d6",
    "#7c3aed", "#af52de", "#e935c1", "#ff2d95", "#ff375f",
    "#ff7a5c", "#f59e0b", "#7fff00", "#00ff7f", "#00e5ff",
]

DEFAULT_COLOR = PALETTE[0]
MAX_NAME = 40
_HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")

#: app_settings key that holds the world's include/exclude label filter.
FILTER_KEY = "label_filter"


def normalize_color(value, fallback: str = DEFAULT_COLOR) -> str:
    """Return a safe `#rrggbb` string (never anything a stylesheet chokes on)."""
    text = str(value or "").strip()
    if not _HEX.match(text):
        return fallback
    text = text.lower()
    if len(text) == 4:                      # #abc → #aabbcc
        text = "#" + "".join(ch * 2 for ch in text[1:])
    return text


def normalize_name(value) -> str:
    """Trim/collapse whitespace and cap the length; '' means 'not a label'."""
    return " ".join(str(value or "").split())[:MAX_NAME].strip()


def normalize_nick(value) -> str:
    return " ".join(str(value or "").split()).strip()


def normalize_id(value) -> str:
    """Label ids never contain spaces — trim whatever the UI sent."""
    return str(value or "").strip()
