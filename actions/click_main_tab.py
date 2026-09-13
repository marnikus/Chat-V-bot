"""Click a chat room tab by configurable selector and text match.

Streams step-by-step debugger detail through `engine.report(...)`: element
search count, "Tab found" / "Failed to find element", whether the found element
was clickable, and whether the click succeeded — all of it produced by the
shared two-phase runner, not by this file.
"""

from actions.find_click_runner import find_and_click  # noqa: F401  (RULE 1: the shared runner)
from actions.base import FindClickBlock, tab_fields


class ClickMainTab(FindClickBlock):
    block_id = "CLICK_MAIN_TAB"
    name = "Click Main Tab"
    icon = "🏠"

    label_template = "tab “{tab_name}”"
    find_defaults = {"click_enabled": True}

    FIELDS = tab_fields()

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
