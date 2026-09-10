"""Click the send button to submit the message.

Uses the shared visual-confirmation runner (RED outline on the element found,
pause, ORANGE outline on the click target, then click) per docs/AGENT_RULES.md,
and falls back to the mat-icon 'send' button when the submit button is absent —
which is the one thing this block adds over the plain find-and-click family.
"""

from backend.visual_click import find_and_click  # noqa: F401  (RULE 1)
from actions.base import BlockField, FindClickBlock, ms_floor
from backend.message_injector import SEND_SELECTOR

#: Fallback: the button wrapping a mat-icon whose text is exactly "send".
SEND_ICON_SELECTOR = "button:has(mat-icon)"


class ClickSend(FindClickBlock):
    block_id = "CLICK_SEND"
    name = "Click Send"
    icon = "📨"

    label_template = "send button"

    FIELDS = (
        BlockField("selector", "text", "Send button selector (CSS)",
                   request="selector"),
        # the two below are only for the retry, so they feed no keyword here
        BlockField("fallback_selector", "text",
                   "Fallback button selector (CSS)"),
        BlockField("fallback_text", "text", "Fallback icon text"),
        BlockField("highlight_enabled", "checkbox", "Draw confirmation outlines",
                   clean=bool, request="highlight_enabled"),
        BlockField("confirm_pause_ms", "number", "Pause after found (ms)",
                   clean=ms_floor, request="confirm_pause_ms"),
    )

    def __init__(self, selector: str = SEND_SELECTOR,
                 fallback_selector: str = SEND_ICON_SELECTOR,
                 fallback_text: str = "send",
                 highlight_enabled: bool = True, confirm_pause_ms: int = 700,
                 pre_delay_ms: int = 300, **kw):
        super().__init__(selector=selector, fallback_selector=fallback_selector,
                         fallback_text=fallback_text,
                         highlight_enabled=highlight_enabled,
                         confirm_pause_ms=confirm_pause_ms,
                         pre_delay_ms=pre_delay_ms, **kw)

    def fallback_attempts(self) -> tuple:
        """One retry on the icon, and what to say while doing it."""
        if not self.fallback_selector:
            return ()
        return (("↩ Submit button did not work — trying the "
                 f"mat-icon '{self.fallback_text}' fallback",
                 {"selector": self.fallback_selector,
                  "label_selector": "mat-icon",
                  "match_text": self.fallback_text,
                  "label": f"send icon “{self.fallback_text}”"}),)
