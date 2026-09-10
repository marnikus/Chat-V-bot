"""Skip current user if already messaged (marker block).

This is a sentinel — the engine checks the user's messaged status during the
per-user loop and reports the skip decision there, so `execute` is never
called for it during a run.
"""

from actions.base import MarkerBlock


class ConditionalSkip(MarkerBlock):
    block_id = "CONDITIONAL_SKIP"
    name = "If Already Messaged → Skip"
    icon = "🔀"

    #: it has no settings of its own, so the panel keeps the inherited
    #: pre-delay row that saved stacks were built against
    panel_shows_pre_delay = True

    def __init__(self, **kw):
        super().__init__(**kw)

    def marker_message(self, user_nick: str) -> str:
        return (f"⏭ Conditional skip marker for {user_nick} — handled by the "
                "engine")
