"""Click back to the main room tab to return from private chat.

Same two-phase visual confirmation as ClickMainTab: a RED outline on the
element found, a pause, then an ORANGE outline on the click target and the
click itself — each phase logged separately. Both phases are the shared runner's
(``visual_click``), so this file is only the block's own settings.
"""

from actions.find_click_runner import find_and_click  # noqa: F401  (RULE 1: the shared runner)
from actions.base import FindClickBlock, tab_fields


class ClickBack(FindClickBlock):
    block_id = "CLICK_BACK"
    name = "Return to Main"
    icon = "🔙"

    label_template = "back tab “{tab_name}”"
    #: the tab is only ever a landing spot — the click is the whole point
    find_defaults = {"click_enabled": True}

    FIELDS = tab_fields()

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
