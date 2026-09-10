"""Configurable "Find & Click" block (CUSTOM_FIND).

A generic, reusable search-and-click action: `selector` is the clickable
rectangle to find, `label_selector` the element inside it whose text is
searched, `match_text` the text to find (empty = the first one), `click_selector`
the element INSIDE to click (empty = the found element itself), and
`click_enabled` whether to click at all. `custom_name` is what the stack shows.

Execution is the shared two-phase runner (docs/AGENT_RULES.md RULE 1):

  1. FIND  — logs success/failure and draws a thin RED outline on the detected
     element, then pauses so the user can confirm it is the right one.
  2. CLICK — logs whether the element is clickable, draws a thin ORANGE outline
     over the click target area, then performs the click.

The block is a constructor: every instance can be customised through the UI
config panel and saved as a reusable preset, so its settings are declared as
`BlockField`s and the panel schema is derived from them (RULE 4 for blocks: the
schema and the saved dictionary come from one list and cannot drift).
"""

from actions.base import BlockField, FindClickBlock, ms_floor


class CustomFind(FindClickBlock):
    block_id = "CUSTOM_FIND"
    name = "Find & Click"
    icon = "🔎"

    FIELDS = (
        BlockField("custom_name", "text", "Block name (shown in stack)"),
        BlockField("selector", "text", "Element to find (CSS)",
                   clean=lambda v: v or "", request="selector"),
        BlockField("label_selector", "text", "Text element inside (CSS)",
                   clean=lambda v: v or "", request="label_selector"),
        BlockField("match_text", "text",
                   "Text to match inside (optional — {{nick}} = selected user)",
                   clean=lambda v: v or "", request="match_text"),
        BlockField("click_enabled", "checkbox", "Click after found",
                   clean=bool, request="click_enabled"),
        BlockField("click_selector", "text", "Element inside to click (optional)",
                   clean=lambda v: v or "", request="click_selector"),
        BlockField("highlight_enabled", "checkbox",
                   "Draw confirmation outlines (red = found, orange = click)",
                   clean=bool, request="highlight_enabled"),
        BlockField("confirm_pause_ms", "number", "Pause after found (ms)",
                   clean=ms_floor, request="confirm_pause_ms"),
        BlockField("highlight_ms", "number", "Outline duration (ms)",
                   clean=ms_floor, request="highlight_ms"),
    )

    def __init__(self, custom_name: str = "", selector: str = "",
                 label_selector: str = "", match_text: str = "",
                 click_enabled: bool = True, click_selector: str = "",
                 highlight_enabled: bool = True, confirm_pause_ms: int = 700,
                 highlight_ms: int = 1200,
                 pre_delay_ms: int = 500, **kw):
        super().__init__(custom_name=custom_name, selector=selector,
                         label_selector=label_selector, match_text=match_text,
                         click_enabled=click_enabled,
                         click_selector=click_selector,
                         highlight_enabled=highlight_enabled,
                         confirm_pause_ms=confirm_pause_ms,
                         highlight_ms=highlight_ms,
                         pre_delay_ms=pre_delay_ms, **kw)

    def find_label(self) -> str:
        """Human-readable search description used in the two log lines."""
        parts = [f"element '{self.selector}'"]
        if self.label_selector:
            parts.append(f"text inside '{self.label_selector}'")
        if self.match_text:
            parts.append(f"matching \"{self.match_text}\"")
        return " ".join(parts)
