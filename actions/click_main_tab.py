"""Click a chat room tab by configurable selector and text match.

Streams step-by-step debugger detail through `engine.report(...)`: element
search count, "Tab found" / "Failed to find element", whether the found element
was clickable, and whether the click succeeded — all of it produced by the
shared two-phase runner, not by this file.
"""

from actions.base import BlockField, FindClickBlock, ms_floor


class ClickMainTab(FindClickBlock):
    block_id = "CLICK_MAIN_TAB"
    name = "Click Main Tab"
    icon = "🏠"

    label_template = "tab “{tab_name}”"
    find_defaults = {"click_enabled": True}

    FIELDS = (
        BlockField("selector", "text", "Tab element selector",
                   request="selector"),
        BlockField("child_selector", "text", "Child text selector",
                   request="label_selector"),
        BlockField("tab_name", "text",
                   "Tab name (text match) — {{nick}} = selected user",
                   request="match_text"),
        BlockField("highlight_enabled", "checkbox", "Draw confirmation outlines",
                   clean=bool, request="highlight_enabled"),
        BlockField("confirm_pause_ms", "number", "Pause after found (ms)",
                   clean=ms_floor, request="confirm_pause_ms"),
    )

    def __init__(self, selector: str = "div[role='tab'].tab-item",
                 child_selector: str = "p.chat-title",
                 tab_name: str = "Гостиная",
                 highlight_enabled: bool = True, confirm_pause_ms: int = 700,
                 pre_delay_ms: int = 500, **kw):
        super().__init__(selector=selector, child_selector=child_selector,
                         tab_name=tab_name,
                         highlight_enabled=highlight_enabled,
                         confirm_pause_ms=confirm_pause_ms,
                         pre_delay_ms=pre_delay_ms, **kw)
