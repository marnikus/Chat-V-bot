"""Actions package — auto-discovery via registry.

No manual import list: `discover()` scans the package and fires @register
decorators (or __init_subclass__ hooks). Keeps Open/Closed principle.
"""

from actions.base_action import BaseAction, ActionResult  # noqa: F401
from actions.registry import ActionContext, register, discover, get_action_class, all_action_ids  # noqa: F401

# Keep legacy explicit imports for backward compat, but new code relies on discover()
try:
    from actions import (  # noqa: F401
        attach_image,
        click_back,
        click_main_tab,
        click_send,
        click_user,
        collect_history,
        conditional_skip,
        custom_find,
        mark_messaged,
        pause,
        repeat_loop,
        scroll_parse,
        search_users,
        take_person,
        type_message,
        wait_page,
    )
except Exception:  # noqa: BLE001
    pass

# Ensure auto-scan runs even if legacy imports fail
try:
    discover()
except Exception:  # noqa: BLE001
    pass
