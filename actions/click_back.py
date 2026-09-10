"""Click back to the main room tab to return from private chat.

Same two-phase visual confirmation as ClickMainTab: a RED outline on the
element found, a pause, then an ORANGE outline on the click target and the
click itself — each phase logged separately. Both phases are the shared runner's
(``visual_click``), so this file is only the block's own settings.
"""

from actions.find_click_runner import find_and_click  # noqa: F401  (RULE 1: the shared runner)
from actions.base import BlockField, FindClickBlock, ms_floor


class ClickBack(FindClickBlock):
    block_id = "CLICK_BACK"
    name = "Return to Main"
    icon = "🔙"

    label_template = "back tab “{tab_name}”"
    #: the tab is only ever a landing spot — the click is the whole point
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
                 pre_delay_ms: int = 800, **kw):
        super().__init__(selector=selector, child_selector=child_selector,
                         tab_name=tab_name,
                         highlight_enabled=highlight_enabled,
                         confirm_pause_ms=confirm_pause_ms,
                         pre_delay_ms=pre_delay_ms, **kw)
